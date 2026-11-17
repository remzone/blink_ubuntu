// SPDX-License-Identifier: GPL-3.0-only
package app

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode"

	"github.com/remzone/blink-android/native/mobile"
	"github.com/remzone/blink-android/native/vkturn"
)

const Limit = 1048576

type Profile struct {
	ID       string          `json:"id"`
	Name     string          `json:"name"`
	Kind     string          `json:"kind"`
	Raw      json.RawMessage `json:"raw"`
	Feed     string          `json:"feed,omitempty"`
	Revision int64           `json:"revision,omitempty"`
}
type ImportResult struct {
	Profiles []Profile         `json:"profiles"`
	Rejected []json.RawMessage `json:"rejected"`
	Notice   string            `json:"notice"`
}

func identify(p *Profile) {
	h := sha256.Sum256(append([]byte(p.Feed+"\x00"), p.Raw...))
	p.ID = hex.EncodeToString(h[:8])
}
func Import(data string, now time.Time) (ImportResult, error) {
	if len(data) > Limit {
		return ImportResult{}, errors.New("превышен лимит подписки 1 МиБ")
	}
	var head struct {
		Schema string `json:"schema"`
	}
	_ = json.Unmarshal([]byte(data), &head)
	if strings.HasPrefix(head.Schema, "vokop.subscription.") {
		return importVokop(data, now)
	}
	raw, err := mobile.ImportProfiles(data)
	if err != nil {
		return ImportResult{}, err
	}
	var imported struct {
		Profiles []mobile.ImportedProfile `json:"profiles"`
		Rejected []json.RawMessage        `json:"rejected"`
		Notice   string                   `json:"notice"`
	}
	if err = json.Unmarshal([]byte(raw), &imported); err != nil {
		return ImportResult{}, err
	}
	result := ImportResult{Rejected: imported.Rejected, Notice: imported.Notice}
	for _, p := range imported.Profiles {
		b, _ := json.Marshal(p)
		entry := Profile{Name: p.Name, Kind: p.Kind, Raw: b}
		identify(&entry)
		result.Profiles = append(result.Profiles, entry)
	}
	return result, nil
}

var profileID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`)
var uuidPattern = regexp.MustCompile(`^[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$`)

type subscription struct {
	Schema      string                `json:"schema"`
	Revision    int64                 `json:"revision"`
	Issued      int64                 `json:"issued_at"`
	Expires     int64                 `json:"expires_at"`
	Routing     *mobile.RoutingPolicy `json:"routing"`
	VPNProfiles []string              `json:"vpn_profiles"`
	Profiles    []struct {
		ID        string `json:"id"`
		Name      string `json:"name"`
		Backend   string `json:"backend"`
		WireGuard string `json:"wireguard"`
		Vless     struct {
			UUID string `json:"uuid"`
		} `json:"vless"`
		Turn struct {
			Protocol string `json:"protocol"`
			WrapKey  string `json:"wrap_key"`
			PeerHost string `json:"peer_host"`
			PeerPort int    `json:"peer_port"`
			CallURL  string `json:"vk_call_url"`
			Streams  int    `json:"streams"`
			Options  struct {
				Transport  string `json:"transport"`
				Preset     string `json:"preset"`
				DNS        string `json:"dns"`
				Relay      string `json:"relay"`
				MTU        int    `json:"mtu"`
				Pace       int    `json:"pace"`
				Window     int    `json:"window"`
				Interval   int    `json:"interval"`
				Congestion bool   `json:"congestion"`
			} `json:"options"`
		} `json:"turn"`
	} `json:"profiles"`
}

func importVokop(data string, now time.Time) (ImportResult, error) {
	var s subscription
	bad := errors.New("некорректная или просроченная подписка Vokop")
	if !uniqueJSON([]byte(data)) || json.Unmarshal([]byte(data), &s) != nil {
		return ImportResult{}, bad
	}
	if (s.Schema != "vokop.subscription.v1" && s.Schema != "vokop.subscription.v2" && s.Schema != "vokop.subscription.v3") || s.Revision < 1 || s.Revision > 9007199254740991 || s.Issued < 0 || s.Issued > now.Unix()+300 || s.Expires <= s.Issued || s.Expires <= now.Unix() || s.Expires > 253402300799 || len(s.Profiles) < 1 || len(s.Profiles) > 16 {
		return ImportResult{}, bad
	}
	if s.Routing != nil {
		if err := s.Routing.Validate(); err != nil {
			return ImportResult{}, bad
		}
	}
	if s.Schema == "vokop.subscription.v3" && (s.Routing == nil || s.Routing.Mode != "selected") {
		return ImportResult{}, bad
	}
	result := ImportResult{}
	seen := map[string]bool{}
	for _, p := range s.Profiles {
		if !profileID.MatchString(p.ID) || seen[p.ID] || len([]rune(p.Name)) > 100 || strings.IndexFunc(p.Name, unicode.IsControl) >= 0 || !uuidPattern.MatchString(p.Vless.UUID) || !validPeer(p.Turn.PeerHost) || p.Turn.PeerPort < 1 || p.Turn.PeerPort > 65535 || p.Turn.Streams < 1 || p.Turn.Streams > 16 {
			return ImportResult{}, bad
		}
		seen[p.ID] = true
		if !regexp.MustCompile(`^https://(www\.)?vk\.(com|ru)/call/join/[A-Za-z0-9_=-]+$`).MatchString(p.Turn.CallURL) || len(p.Turn.CallURL) > 2048 {
			return ImportResult{}, bad
		}
		backend := p.Backend
		if backend == "" {
			backend = "vless"
		}
		protocol := p.Turn.Protocol
		if protocol == "" {
			protocol = "kcp"
		}
		if backend == "vless" {
			if protocol != "kcp" || p.WireGuard != "" {
				return ImportResult{}, bad
			}
		} else if backend == "wireguard" {
			if s.Schema == "vokop.subscription.v1" || (protocol != "dtls" && protocol != "srtp" && protocol != "wrap") {
				return ImportResult{}, bad
			}
			if _, err := mobile.ImportProfile(p.WireGuard); err != nil {
				return ImportResult{}, bad
			}
		} else {
			return ImportResult{}, bad
		}
		if protocol == "wrap" {
			key, err := hex.DecodeString(p.Turn.WrapKey)
			if err != nil || len(key) != 32 {
				return ImportResult{}, bad
			}
		} else if p.Turn.WrapKey != "" {
			return ImportResult{}, bad
		}
		o := p.Turn.Options
		transport := o.Transport
		if transport == "" {
			transport = "auto"
		}
		if transport != "auto" && transport != "tcp" && transport != "udp" {
			return ImportResult{}, bad
		}
		tuning := vkturn.Tuning{Preset: o.Preset, MTU: o.MTU, PaceKiB: o.Pace}
		if o.Preset == "custom" {
			tuning.Window = o.Window
			tuning.IntervalMS = o.Interval
			tuning.Congestion = o.Congestion
		}
		if tuning.MTU != 0 && (tuning.MTU < 576 || tuning.MTU > 1200) || tuning.PaceKiB != 0 && (tuning.PaceKiB < 16 || tuning.PaceKiB > 4096) {
			return ImportResult{}, bad
		}
		if tuning.Preset != "" && tuning.Preset != "custom" && tuning.Preset != "compatibility" && tuning.Preset != "balanced" && tuning.Preset != "conservative" {
			return ImportResult{}, bad
		}
		if tuning.Preset == "custom" && (o.Window < 16 || o.Window > 256 || o.Interval < 10 || o.Interval > 100) {
			return ImportResult{}, bad
		}
		v := mobile.VKProfile{Backend: backend, Protocol: protocol, WireGuard: p.WireGuard, WrapKey: p.Turn.WrapKey, Routing: s.Routing, TURNTransport: transport, TURNServer: o.Relay, DNSServer: o.DNS, Tuning: tuning, ManualCaptcha: true, Mode: "vk", UUID: p.Vless.UUID, PeerHost: p.Turn.PeerHost, PeerPort: p.Turn.PeerPort, VKCallURL: p.Turn.CallURL, Streams: p.Turn.Streams, ExpiresAt: s.Expires}
		b, _ := json.Marshal(v)
		entry := Profile{Name: p.Name, Kind: "vk", Raw: b, Revision: s.Revision}
		identify(&entry)
		result.Profiles = append(result.Profiles, entry)
	}
	for _, source := range s.VPNProfiles {
		r, err := Import(source, now)
		if err != nil {
			return ImportResult{}, bad
		}
		for _, p := range r.Profiles {
			p.Revision = s.Revision
			result.Profiles = append(result.Profiles, p)
		}
	}
	return result, nil
}
func validPeer(s string) bool {
	if len(s) > 253 || !strings.Contains(s, ".") || strings.HasSuffix(strings.ToLower(s), ".localhost") {
		return false
	}
	if ip := net.ParseIP(s); ip != nil {
		v4 := ip.To4()
		return v4 != nil && v4[0] != 0 && v4[0] < 224 && !(v4[0] == 100 && v4[1] >= 64 && v4[1] <= 127) && ip.IsGlobalUnicast() && !ip.IsPrivate() && !ip.IsLoopback()
	}
	if regexp.MustCompile(`^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$`).MatchString(s) {
		return false
	}
	for _, label := range strings.Split(s, ".") {
		if len(label) < 1 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
			return false
		}
		for _, c := range label {
			if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-') {
				return false
			}
		}
	}
	return true
}
func (p Profile) Validate() error {
	if p.Kind == "vk" {
		var v mobile.VKProfile
		if json.Unmarshal(p.Raw, &v) != nil || v.Mode != "vk" || v.ExpiresAt <= time.Now().Unix() {
			return errors.New("VK-профиль повреждён или просрочен")
		}
		return nil
	}
	var v mobile.ImportedProfile
	if json.Unmarshal(p.Raw, &v) != nil {
		return errors.New("профиль повреждён")
	}
	_, err := mobile.ImportProfile(v.Source)
	return err
}
func (p Profile) Network() (addresses, dns, routes []string, mtu int, err error) {
	if p.Kind == "vk" {
		var v mobile.VKProfile
		if json.Unmarshal(p.Raw, &v) != nil {
			return nil, nil, nil, 0, errors.New("invalid VK profile")
		}
		if v.Backend == "wireguard" {
			raw, e := mobile.ImportProfile(v.WireGuard)
			if e != nil {
				return nil, nil, nil, 0, e
			}
			var w mobile.ImportedProfile
			if e = json.Unmarshal([]byte(raw), &w); e != nil {
				return nil, nil, nil, 0, e
			}
			return w.Addresses, w.DNS, w.Routes, w.MTU, nil
		}
		return []string{"10.77.0.2/32"}, []string{"1.1.1.1"}, []string{"0.0.0.0/0"}, 1280, nil
	}
	var saved mobile.ImportedProfile
	if json.Unmarshal(p.Raw, &saved) != nil {
		return nil, nil, nil, 0, errors.New("invalid profile")
	}
	raw, e := mobile.ImportProfile(saved.Source)
	if e != nil {
		return nil, nil, nil, 0, e
	}
	var p2 mobile.ImportedProfile
	_ = json.Unmarshal([]byte(raw), &p2)
	return p2.Addresses, p2.DNS, p2.Routes, p2.MTU, nil
}
func NormalizeURL(input string) (string, error) {
	s := strings.TrimSpace(input)
	if strings.HasPrefix(s, "[") {
		if i := strings.Index(s, "]("); i >= 0 && strings.HasSuffix(s, ")") {
			s = s[i+2 : len(s)-1]
		}
	}
	u, e := url.Parse(s)
	if e != nil {
		return "", errors.New("некорректная ссылка")
	}
	if u.Scheme == "hiddify" || u.Scheme == "clash" {
		wrapped := u.Query().Get("url")
		if wrapped == "" && u.Scheme == "hiddify" && u.Host == "import" {
			wrapped = strings.TrimPrefix(s, "hiddify://import/")
			if i := strings.IndexByte(wrapped, '#'); i >= 0 {
				wrapped = wrapped[:i]
			}
		}
		u, e = url.Parse(wrapped)
	}
	if e != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.Fragment != "" {
		return "", fmt.Errorf("нужна полная HTTPS-ссылка подписки")
	}
	return u.String(), nil
}
