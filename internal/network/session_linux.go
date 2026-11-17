// SPDX-License-Identifier: GPL-3.0-only
package network

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

const Device = "blink0"
const Table = "51831"
const Mark = 0xb11

var priorities = []string{"10101", "10102", "10103"}

type Runner interface {
	Run(tool string, args ...string) ([]byte, error)
}
type SystemRunner struct{}

func (SystemRunner) Run(tool string, args ...string) ([]byte, error) {
	var path string
	for _, base := range []string{"/usr/sbin/", "/sbin/", "/usr/bin/", "/bin/"} {
		if s, e := os.Stat(base + tool); e == nil && s.Mode().IsRegular() && s.Mode()&0111 != 0 {
			path = base + tool
			break
		}
	}
	if path == "" {
		return nil, fmt.Errorf("не найдена команда %s", tool)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, path, args...)
	cmd.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL=C"}
	b, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("%s: операция не выполнена (%v)", tool, err)
	}
	return b, nil
}

type Step struct {
	Tool string
	Args []string
	Undo []string
}
type Session struct {
	Run  Runner
	undo []Step
	mu   sync.Mutex
}

func New(r Runner) *Session { return &Session{Run: r} }
func (s *Session) Preflight() error {
	for _, family := range []string{"-4", "-6"} {
		b, err := s.Run.Run("ip", family, "-j", "rule", "show")
		if err != nil {
			return err
		}
		var rules []struct {
			Priority int `json:"priority"`
			Table    any `json:"table"`
		}
		if json.Unmarshal(b, &rules) != nil {
			return errors.New("не удалось прочитать policy routing")
		}
		for _, r := range rules {
			if r.Priority >= 10101 && r.Priority <= 10103 || fmt.Sprint(r.Table) == Table {
				return errors.New("таблица 51831 или приоритеты 10101–10103 уже заняты")
			}
		}
		b, err = s.Run.Run("ip", family, "-j", "route", "show", "table", Table)
		if err != nil { // An absent FIB table is normal on older iproute2.
			b = nil
		}
		if len(b) > 0 && strings.TrimSpace(string(b)) != "[]" {
			return errors.New("таблица маршрутизации 51831 уже занята")
		}
	}
	_, err := s.Run.Run("resolvectl", "status")
	return err
}
func Validate(addresses, dns, routes []string, mtu int) error {
	if len(addresses) < 1 || len(dns) < 1 || len(routes) < 1 || len(addresses) > 32 || len(dns) > 32 || len(routes) > 1024 || mtu < 576 || mtu > 9000 {
		return errors.New("некорректная конфигурация интерфейса")
	}
	for _, v := range append(append([]string{}, addresses...), routes...) {
		if _, e := netip.ParsePrefix(v); e != nil {
			return errors.New("некорректный IP-префикс")
		}
	}
	for _, v := range dns {
		if _, e := netip.ParseAddr(v); e != nil {
			return errors.New("некорректный DNS-адрес")
		}
	}
	return nil
}

// Plan touches only our TUN, private routing table and exact owned rules.
func Plan(addresses, dns, routes []string, mtu int) ([]Step, error) {
	if err := Validate(addresses, dns, routes, mtu); err != nil {
		return nil, err
	}
	steps := []Step{{"ip", []string{"link", "set", "dev", Device, "mtu", strconv.Itoa(mtu), "up"}, nil}}
	for _, address := range addresses {
		steps = append(steps, Step{"ip", []string{"address", "add", address, "dev", Device}, nil})
	}
	for _, route := range routes {
		family := "-4"
		if strings.Contains(route, ":") {
			family = "-6"
		}
		steps = append(steps, Step{"ip", []string{family, "route", "add", route, "dev", Device, "table", Table}, []string{family, "route", "del", route, "dev", Device, "table", Table}})
	}
	// Never let unconfigured IPv6 use the physical default route. More specific WG
	// routes still win. Connected LAN routes are deliberately preserved below.
	steps = append(steps, Step{"ip", []string{"-6", "route", "add", "unreachable", "default", "metric", "42760", "table", Table}, []string{"-6", "route", "del", "unreachable", "default", "metric", "42760", "table", Table}})
	for _, family := range []string{"-4", "-6"} {
		rules := [][]string{{"priority", priorities[0], "fwmark", fmt.Sprintf("0x%x", Mark), "lookup", "main"}, {"priority", priorities[1], "lookup", "main", "suppress_prefixlength", "0"}, {"priority", priorities[2], "lookup", Table}}
		for _, r := range rules {
			args := append([]string{family, "rule", "add"}, r...)
			undo := append([]string{family, "rule", "del"}, r...)
			steps = append(steps, Step{"ip", args, undo})
		}
	}
	steps = append(steps, Step{"resolvectl", append([]string{"dns", Device}, dns...), []string{"revert", Device}}, Step{"resolvectl", []string{"domain", Device, "~."}, nil}, Step{"resolvectl", []string{"default-route", Device, "yes"}, nil})
	return steps, nil
}
func (s *Session) Apply(steps []Step) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, step := range steps {
		if _, err := s.Run.Run(step.Tool, step.Args...); err != nil {
			return errors.Join(err, s.closeLocked())
		}
		if len(step.Undo) > 0 {
			s.undo = append(s.undo, step)
		}
	}
	return nil
}
func (s *Session) Close() error { s.mu.Lock(); defer s.mu.Unlock(); return s.closeLocked() }
func (s *Session) closeLocked() error {
	var result error
	var failed []Step
	for i := len(s.undo) - 1; i >= 0; i-- {
		step := s.undo[i]
		if _, err := s.Run.Run(step.Tool, step.Undo...); err != nil {
			result = errors.Join(result, err)
			failed = append([]Step{step}, failed...)
		}
	}
	s.undo = failed
	return result
}

type TUN struct{ *os.File }

func OpenTUN() (*TUN, error) {
	if _, err := net.InterfaceByName(Device); err == nil {
		return nil, errors.New("интерфейс blink0 уже существует")
	}
	fd, err := unix.Open("/dev/net/tun", unix.O_RDWR|unix.O_CLOEXEC|unix.O_NONBLOCK, 0)
	if err != nil {
		return nil, err
	}
	req, err := unix.NewIfreq(Device)
	if err == nil {
		req.SetUint16(unix.IFF_TUN | unix.IFF_NO_PI)
		err = unix.IoctlIfreq(fd, unix.TUNSETIFF, req)
	}
	if err != nil {
		unix.Close(fd)
		return nil, err
	}
	return &TUN{os.NewFile(uintptr(fd), "blink-tun")}, nil
}
func (t *TUN) WritePacket(b []byte) bool { n, err := t.Write(b); return err == nil && n == len(b) }

type Protector struct{}

func (Protector) Protect(fd int64) bool {
	return unix.SetsockoptInt(int(fd), unix.SOL_SOCKET, unix.SO_MARK, Mark) == nil
}
func Lock() (*os.File, error) {
	f, err := os.OpenFile("/run/blink-ubuntu.lock", os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, err
	}
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, errors.New("Blink уже подключён")
	}
	return f, nil
}
