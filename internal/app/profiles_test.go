package app

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

const link = "vless://00000000-0000-4000-8000-000000000001@192.0.2.1:443?security=tls&sni=example.org#Test"

func TestImportAndPrivateAtomicStore(t *testing.T) {
	r, e := Import(link, time.Now())
	if e != nil || len(r.Profiles) != 1 {
		t.Fatal(r, e)
	}
	dir := t.TempDir()
	if e = WithStore(dir, func(s *Store) error { return s.Merge(r, "") }); e != nil {
		t.Fatal(e)
	}
	for _, entry := range []struct {
		path string
		mode os.FileMode
	}{{dir, 0700}, {filepath.Join(dir, "profiles.json"), 0600}} {
		stat, e := os.Stat(entry.path)
		if e != nil || stat.Mode().Perm() != entry.mode {
			t.Fatal(stat, e)
		}
	}
	if e = WithStore(dir, func(s *Store) error {
		if len(s.Profiles) != 1 {
			t.Fatal(s)
		}
		return s.Merge(r, "")
	}); e != nil {
		t.Fatal(e)
	}
	if e = WithStore(dir, func(s *Store) error {
		if len(s.Profiles) != 1 {
			t.Fatal("duplicate")
		}
		return nil
	}); e != nil {
		t.Fatal(e)
	}
}
func TestVokopFixtureExpirationAndMapping(t *testing.T) {
	b, e := os.ReadFile("../../fixtures/vokop.subscription.v1.json")
	if e != nil {
		t.Fatal(e)
	}
	var doc map[string]any
	_ = json.Unmarshal(b, &doc)
	now := time.Unix(1793300100, 0)
	r, e := Import(string(b), now)
	if e != nil || len(r.Profiles) != 1 {
		t.Fatal(e)
	}
	var raw map[string]any
	_ = json.Unmarshal(r.Profiles[0].Raw, &raw)
	if raw["turnTransport"] != "auto" || raw["mode"] != "vk" || raw["vkCallURL"] != "https://vk.com/call/join/DEMO_TOKEN" {
		t.Fatal(raw)
	}
	if _, e = Import(string(b), now.Add(2*time.Hour)); e == nil {
		t.Fatal("expired document accepted")
	}
	for _, schema := range []string{"vokop.subscription.v2", "invalid"} {
		doc["schema"] = schema
		b, _ = json.Marshal(doc)
		_, e = Import(string(b), now)
		if schema == "invalid" && e == nil {
			t.Fatal("schema accepted")
		}
	}
}
func TestVokopDuplicateIDAndCallURL(t *testing.T) {
	b, _ := os.ReadFile("../../fixtures/vokop.subscription.v1.json")
	var doc map[string]any
	_ = json.Unmarshal(b, &doc)
	profiles := doc["profiles"].([]any)
	doc["profiles"] = append(profiles, profiles[0])
	b, _ = json.Marshal(doc)
	if _, e := Import(string(b), time.Unix(1793300100, 0)); e == nil {
		t.Fatal("duplicate ID accepted")
	}
}
func TestFeedUpdateRejectsRollbackAndKeepsOtherFeed(t *testing.T) {
	r, e := Import(link, time.Now())
	if e != nil {
		t.Fatal(e)
	}
	r.Profiles[0].Revision = 5
	s := Store{}
	_ = s.Merge(r, "https://one.example/key")
	_ = s.Merge(r, "https://two.example/key")
	r.Profiles[0].Revision = 4
	if s.Merge(r, "https://one.example/key") == nil || len(s.Profiles) != 2 {
		t.Fatal("rollback")
	}
	r.Profiles[0].Revision = 6
	if e = s.Merge(r, "https://one.example/key"); e != nil || len(s.Profiles) != 2 {
		t.Fatal(e)
	}
}
func TestBoundedImportAndRedaction(t *testing.T) {
	for _, source := range []string{strings.Repeat("x", Limit+1), "vless://SECRET@example.org:443?unknown=SECRET"} {
		_, e := Import(source, time.Now())
		if e == nil || strings.Contains(e.Error(), "SECRET") {
			t.Fatal(e)
		}
	}
}
func TestURLValidation(t *testing.T) {
	for _, s := range []string{"http://example.org/key", "https://user:secret@example.org/key", "https://example.org/key#secret", "file:///etc/passwd"} {
		if _, e := NormalizeURL(s); e == nil {
			t.Fatal(s)
		}
	}
	got, e := NormalizeURL("[test](https://example.org/a?token=a%2Fb)")
	if e != nil || got != "https://example.org/a?token=a%2Fb" {
		t.Fatal(got, e)
	}
}
func TestFetchRejectsHTTPAndRedactsToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Error("HTTP request must not be made") }))
	defer server.Close()
	_, e := Fetch(context.Background(), server.URL+"/SECRET")
	if e == nil || strings.Contains(e.Error(), "SECRET") {
		t.Fatal(e)
	}
}

func TestHiddifyDoesNotDecodeTokenTwice(t *testing.T) {
	expected := "https://example.org/path?token=a%2Fb%252Fc"
	got, e := NormalizeURL("hiddify://import/" + expected + "#Name")
	if e != nil || got != expected {
		t.Fatal(got, e)
	}
	got, e = NormalizeURL("clash://install-config?url=https%3A%2F%2Fexample.org%2Fpath%3Ftoken%3Da%252Fb%25252Fc")
	if e != nil || got != expected {
		t.Fatal(got, e)
	}
}
func TestVokopRejectsDuplicateJSONKeys(t *testing.T) {
	data, _ := os.ReadFile("../../fixtures/vokop.subscription.v1.json")
	data = []byte(strings.Replace(string(data), `"revision":1`, `"revision":2,"revision":1`, 1))
	if _, e := Import(string(data), time.Unix(1793300100, 0)); e == nil {
		t.Fatal("duplicate key accepted")
	}
}
