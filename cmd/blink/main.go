// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/remzone/blink-android/native/mobile"
	"github.com/remzone/blink_ubuntu/internal/app"
	"github.com/remzone/blink_ubuntu/internal/network"
)

const version = "0.2.1"

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "Blink:", err)
		os.Exit(1)
	}
}
func run(args []string) error {
	if len(args) == 0 {
		help()
		return nil
	}
	switch args[0] {
	case "help", "--help", "-h":
		help()
		return nil
	case "version", "--version":
		fmt.Println("Blink Ubuntu", version)
		return nil
	case "captcha":
		return captchaCommand()
	case "gui":
		return gui()
	case "session":
		return session()
	case "doctor":
		return doctor()
	case "import":
		return importCommand(args[1:])
	case "list":
		return app.WithStore(app.ConfigDir(), func(s *app.Store) error {
			type summary struct {
				ID   string `json:"id"`
				Name string `json:"name"`
				Kind string `json:"kind"`
			}
			out := []summary{}
			for _, p := range s.Profiles {
				kind := p.Kind
				if kind == "vk" {
					kind = "turn"
				}
				out = append(out, summary{p.ID, p.Name, kind})
			}
			return json.NewEncoder(os.Stdout).Encode(out)
		})
	case "export":
		if len(args) != 2 {
			return errors.New("укажите ID профиля")
		}
		return app.WithStore(app.ConfigDir(), func(s *app.Store) error {
			for _, p := range s.Profiles {
				if p.ID == args[1] {
					return json.NewEncoder(os.Stdout).Encode(p)
				}
			}
			return errors.New("профиль не найден")
		})
	case "refresh":
		return refresh()
	case "remove":
		if len(args) != 2 {
			return errors.New("укажите ID профиля")
		}
		return app.WithStore(app.ConfigDir(), func(s *app.Store) error {
			for i, p := range s.Profiles {
				if p.ID == args[1] {
					s.Profiles = append(s.Profiles[:i], s.Profiles[i+1:]...)
					return nil
				}
			}
			return errors.New("профиль не найден")
		})
	case "connect":
		if len(args) != 2 {
			return errors.New("укажите ID профиля из blink list")
		}
		return connect(args[1])
	default:
		return errors.New("неизвестная команда; выполните blink help")
	}
}
func help() {
	fmt.Print(`Blink Ubuntu 0.2.1 — Ubuntu 20.04+
  blink gui                         Графический клиент
  blink captcha                     Окно проверки подключения, JSON challenge по stdin
  blink import --file PATH          Импорт файла
  blink import                      Импорт профиля/HTTPS-ссылки из stdin
  blink list                        Профили (JSON без секретов)
  blink refresh                     Обновить сохранённые HTTPS-подписки
  blink remove ID                   Удалить профиль
  blink export ID                   Вывести секретный профиль (для резервной копии)
  blink connect ID                  Подключить VPN; Ctrl+C — отключить
  blink doctor                      Проверка зависимостей
  blink version

Ссылку с токеном передавайте через stdin, не аргументы командной строки.
Во время connect доступны JSON-команды stdin: {"command":"stop"} и
{"command":"captcha","id":"...","kind":"key","value":"..."}.
session — внутренний протокол GUI: JSON-профиль, затем команды по stdin.
`)
}
func readBounded(r io.Reader) (string, error) {
	b, e := io.ReadAll(io.LimitReader(r, app.Limit+1))
	if e != nil {
		return "", e
	}
	if len(b) > app.Limit {
		return "", errors.New("лимит 1 МиБ")
	}
	return string(b), nil
}
func importCommand(args []string) error {
	fs := flag.NewFlagSet("import", flag.ContinueOnError)
	file := fs.String("file", "", "profile file")
	if e := fs.Parse(args); e != nil {
		return e
	}
	if fs.NArg() != 0 {
		return errors.New("данные профиля передавайте через stdin или --file")
	}
	input := io.Reader(os.Stdin)
	if *file != "" {
		f, e := os.Open(*file)
		if e != nil {
			return e
		}
		defer f.Close()
		input = f
	}
	data, e := readBounded(input)
	if e != nil {
		return e
	}
	feed := ""
	if u, err := app.NormalizeURL(data); err == nil {
		feed = u
		data, e = app.Fetch(context.Background(), u)
		if e != nil {
			return e
		}
	}
	result, e := app.Import(data, time.Now())
	if e != nil {
		return e
	}
	e = app.WithStore(app.ConfigDir(), func(s *app.Store) error { return s.Merge(result, feed) })
	if e != nil {
		return e
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"imported": len(result.Profiles), "rejected": len(result.Rejected), "notice": result.Notice})
}
func refresh() error {
	var feeds []string
	if e := app.WithStore(app.ConfigDir(), func(s *app.Store) error {
		seen := map[string]bool{}
		for _, p := range s.Profiles {
			if p.Feed != "" && !seen[p.Feed] {
				seen[p.Feed] = true
				feeds = append(feeds, p.Feed)
			}
		}
		return nil
	}); e != nil {
		return e
	}
	updated, failed := 0, 0
	for _, feed := range feeds {
		data, e := app.Fetch(context.Background(), feed)
		if e == nil {
			var result app.ImportResult
			result, e = app.Import(data, time.Now())
			if e == nil {
				e = app.WithStore(app.ConfigDir(), func(s *app.Store) error { return s.Merge(result, feed) })
			}
		}
		if e != nil {
			failed++
		} else {
			updated++
		}
	}
	_ = json.NewEncoder(os.Stdout).Encode(map[string]int{"updated": updated, "failed": failed})
	if failed > 0 {
		return errors.New("часть подписок не обновлена; прежние профили сохранены")
	}
	return nil
}
func connect(id string) error {
	var profile app.Profile
	if e := app.WithStore(app.ConfigDir(), func(s *app.Store) error {
		for _, p := range s.Profiles {
			if p.ID == id {
				profile = p
				return nil
			}
		}
		return errors.New("профиль не найден")
	}); e != nil {
		return e
	}
	if e := profile.Validate(); e != nil {
		return e
	}
	binary, e := os.Executable()
	if e != nil {
		return e
	}
	binary, e = filepath.EvalSymlinks(binary)
	if e != nil {
		return e
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	cmd := exec.Command("sudo", "--", binary, "session")
	if os.Geteuid() == 0 {
		cmd = exec.Command(binary, "session")
	}
	pipe, e := cmd.StdinPipe()
	if e != nil {
		return e
	}
	defer pipe.Close()
	output, e := cmd.StdoutPipe()
	if e != nil {
		return e
	}
	cmd.Stderr = os.Stderr
	if e = cmd.Start(); e != nil {
		return e
	}
	var writeMu sync.Mutex
	send := func(value any) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		return json.NewEncoder(pipe).Encode(value)
	}
	if e = send(profile); e != nil {
		_ = pipe.Close()
		_ = cmd.Wait()
		return e
	}
	go func() {
		input := bufio.NewScanner(os.Stdin)
		input.Buffer(make([]byte, 4096), 65536)
		for input.Scan() {
			if json.Valid(input.Bytes()) {
				_ = send(json.RawMessage(append([]byte{}, input.Bytes()...)))
			}
		}
	}()
	go func() { <-ctx.Done(); _ = pipe.Close() }()
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		var stopCaptcha context.CancelFunc
		defer func() {
			if stopCaptcha != nil {
				stopCaptcha()
			}
		}()
		scanner := bufio.NewScanner(output)
		scanner.Buffer(make([]byte, 4096), 131072)
		for scanner.Scan() {
			raw := append([]byte{}, scanner.Bytes()...)
			var event map[string]json.RawMessage
			if json.Unmarshal(raw, &event) == nil && event["captcha"] != nil && os.Geteuid() != 0 && (os.Getenv("DISPLAY") != "" || os.Getenv("WAYLAND_DISPLAY") != "") {
				if stopCaptcha != nil {
					stopCaptcha()
				}
				helperContext, stop := context.WithCancel(ctx)
				stopCaptcha = stop
				challenge := append(json.RawMessage{}, event["captcha"]...)
				delete(event, "captcha")
				event["captcha_ui"] = json.RawMessage(`"opening"`)
				raw, _ = json.Marshal(event)
				go func() {
					answer, err := solveCaptcha(helperContext, challenge)
					if helperContext.Err() != nil {
						return
					}
					if err != nil {
						fmt.Fprintln(os.Stderr, "Blink: проверка подключения не завершена. Повторите подключение и проверьте установку WebKit.")
						_ = send(command{Command: "stop"})
						return
					}
					_ = send(answer)
				}()
			}
			fmt.Fprintln(os.Stdout, string(raw))
		}
	}()
	err := cmd.Wait()
	cancel()
	_ = pipe.Close()
	<-finished
	return err
}
func gui() error {
	file, e := guiFile("blink_gui.py")
	if e != nil {
		return e
	}
	binary, e := os.Executable()
	if e != nil {
		return e
	}
	cmd := exec.Command("/usr/bin/python3", file)
	cmd.Env = append(os.Environ(), "BLINK_BINARY="+binary)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}
func doctor() error {
	checks := map[string]bool{}
	_, e := os.Stat("/dev/net/tun")
	checks["tun"] = e == nil
	for _, tool := range []string{"ip", "resolvectl", "pkexec", "sudo", "python3"} {
		_, e := exec.LookPath(tool)
		checks[tool] = e == nil
	}
	cmd := exec.Command("/usr/bin/python3", "-c", "import tkinter")
	checks["tkinter"] = cmd.Run() == nil
	_ = json.NewEncoder(os.Stdout).Encode(checks)
	for _, tool := range []string{"tun", "ip", "resolvectl"} {
		if !checks[tool] {
			return errors.New("не хватает зависимостей; см. README")
		}
	}
	return nil
}

type command struct {
	Command string `json:"command"`
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Value   string `json:"value"`
}

func session() (result error) {
	signal.Ignore(syscall.SIGPIPE)
	if os.Geteuid() != 0 {
		return errors.New("для TUN нужны права root; используйте blink connect или GUI")
	}
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 4096), 2*app.Limit)
	if !scanner.Scan() {
		return errors.New("ожидался профиль по stdin")
	}
	var p app.Profile
	if json.Unmarshal(scanner.Bytes(), &p) != nil {
		return errors.New("некорректный профиль")
	}
	if e := p.Validate(); e != nil {
		return e
	}
	addresses, dns, routes, mtu, e := p.Network()
	if e != nil {
		return e
	}
	plan, e := network.Plan(addresses, dns, routes, mtu)
	if e != nil {
		return e
	}
	lock, e := network.Lock()
	if e != nil {
		return e
	}
	defer lock.Close()
	netSession := network.New(network.SystemRunner{})
	if e = netSession.Preflight(); e != nil {
		return e
	}
	tun, e := network.OpenTUN()
	if e != nil {
		return e
	}
	defer tun.Close()
	assets, e := os.MkdirTemp("", "blink-assets-")
	if e != nil {
		return e
	}
	defer os.RemoveAll(assets)
	if e = mobile.PrepareAssets(assets); e != nil {
		return errors.New("не удалось подготовить geodata")
	}
	mobile.ConfigureRuntime(256<<20, 100)
	var engine *mobile.Engine
	if p.Kind == "vk" {
		engine, e = mobile.StartVK(string(p.Raw), tun, network.Protector{})
	} else {
		engine, e = mobile.StartProfile(string(p.Raw), tun, network.Protector{})
	}
	if e != nil {
		return e
	}
	defer engine.Stop()
	defer func() { result = errors.Join(result, netSession.Close()) }()
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGHUP)
	defer cancel()
	commands := make(chan command, 8)
	go func() {
		defer cancel()
		for scanner.Scan() {
			var c command
			if json.Unmarshal(scanner.Bytes(), &c) != nil {
				continue
			}
			select {
			case commands <- c:
			case <-ctx.Done():
				return
			}
		}
	}()
	packetError := make(chan error, 1)
	startPackets := func() {
		go func() {
			buffer := make([]byte, 65535)
			for {
				n, err := tun.Read(buffer)
				if err != nil {
					packetError <- err
					return
				}
				if err = engine.Input(buffer[:n]); err != nil {
					packetError <- err
					return
				}
			}
		}()
	}

	encoder := json.NewEncoder(os.Stdout)
	emit := func(v any) error { return encoder.Encode(v) }
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	ready := false
	start := time.Now()
	captchaID := ""
	for {
		state := engine.Status()
		if (state == "running" || state == "ready") && !ready {
			if e = netSession.Apply(plan); e != nil {
				return e
			}
			ready = true
			startPackets()
		}
		event := map[string]any{"state": state, "routed": ready, "stats": json.RawMessage(engine.StatsJSON())}
		if raw := engine.CaptchaJSON(); raw != "{}" {
			var c map[string]any
			if json.Unmarshal([]byte(raw), &c) == nil {
				if id, _ := c["id"].(string); id != captchaID {
					event["captcha"] = c
					captchaID = id
				}
			}
		}
		if e = emit(event); e != nil {
			return nil
		}
		if state == "stopped" {
			return errors.New("VPN-ядро остановлено")
		}
		if !ready && state != "captcha_required" && time.Since(start) > 45*time.Second {
			return errors.New("транспорт не готов за 45 секунд")
		}
		select {
		case <-ctx.Done():
			_ = emit(map[string]any{"state": "stopping"})
			return nil
		case e = <-packetError:
			return fmt.Errorf("TUN: %w", e)
		case c := <-commands:
			switch c.Command {
			case "stop":
				return nil
			case "captcha":
				accepted := engine.SubmitCaptcha(c.ID, c.Kind, c.Value)
				_ = emit(map[string]any{"captcha_accepted": accepted})
				start = time.Now()
			}
		case <-tick.C:
		}
	}
}
