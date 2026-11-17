package network

import (
	"bytes"
	"os"
	"strings"
	"testing"
)

type isolatedRunner struct{ SystemRunner }

func (r isolatedRunner) Run(tool string, args ...string) ([]byte, error) {
	if tool == "resolvectl" {
		return []byte("test resolver"), nil
	}
	return r.SystemRunner.Run(tool, args...)
}

// Run ONLY in a disposable network namespace; never changes the host's network.
func TestIsolatedLinuxTUNAndPolicyRouting(t *testing.T) {
	if os.Getenv("BLINK_NETNS_TEST") != "1" {
		t.Skip("requires unshare --user --map-root-user --net")
	}
	host := os.Getenv("BLINK_HOST_NETNS")
	if host == "" {
		t.Fatal("use tools/test-netns.sh to capture the original namespace")
	}
	self, e := os.Readlink("/proc/self/ns/net")
	if e != nil || host == self {
		t.Fatal("refusing to test host network")
	}
	r := isolatedRunner{}
	before4, e := r.Run("ip", "-4", "-j", "rule", "show")
	if e != nil {
		t.Fatal(e)
	}
	before6, e := r.Run("ip", "-6", "-j", "rule", "show")
	if e != nil {
		t.Fatal(e)
	}
	session := New(r)
	if e = session.Preflight(); e != nil {
		t.Fatal(e)
	}
	tun, e := OpenTUN()
	if e != nil {
		t.Fatal(e)
	}
	defer tun.Close()
	plan, e := Plan([]string{"10.77.0.2/32"}, []string{"1.1.1.1"}, []string{"0.0.0.0/0"}, 1280)
	if e != nil {
		t.Fatal(e)
	}
	if e = session.Apply(plan); e != nil {
		t.Fatal(e)
	}
	defer session.Close()
	routes, e := r.Run("ip", "-4", "route", "show", "table", Table)
	if e != nil || !strings.Contains(string(routes), Device) {
		t.Fatalf("%s %v", routes, e)
	}
	if e = session.Close(); e != nil {
		t.Fatal(e)
	}
	after4, _ := r.Run("ip", "-4", "-j", "rule", "show")
	after6, _ := r.Run("ip", "-6", "-j", "rule", "show")
	if !bytes.Equal(before4, after4) || !bytes.Equal(before6, after6) {
		t.Fatal("policy rules were not restored")
	}
}
