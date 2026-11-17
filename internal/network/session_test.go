package network

import (
	"errors"
	"reflect"
	"strings"
	"testing"
)

type fakeRunner struct {
	calls []string
	fail  int
}

func (f *fakeRunner) Run(tool string, args ...string) ([]byte, error) {
	f.calls = append(f.calls, tool+" "+strings.Join(args, " "))
	if len(f.calls) == f.fail {
		return nil, errors.New("injected failure")
	}
	return []byte("[]"), nil
}
func TestRollbackEveryFailure(t *testing.T) {
	plan, err := Plan([]string{"10.77.0.2/32"}, []string{"1.1.1.1"}, []string{"0.0.0.0/0"}, 1280)
	if err != nil {
		t.Fatal(err)
	}
	for failure := 1; failure <= len(plan); failure++ {
		r := &fakeRunner{fail: failure}
		s := New(r)
		if s.Apply(plan) == nil {
			t.Fatalf("failure %d ignored", failure)
		}
		var expected []string
		for i := failure - 2; i >= 0; i-- {
			if len(plan[i].Undo) > 0 {
				expected = append(expected, plan[i].Tool+" "+strings.Join(plan[i].Undo, " "))
			}
		}
		if !reflect.DeepEqual(r.calls[failure:], expected) && !(len(expected) == 0 && len(r.calls[failure:]) == 0) {
			t.Fatalf("failure %d rollback: %v want %v", failure, r.calls[failure:], expected)
		}
		if len(s.undo) != 0 {
			t.Fatal("rollback incomplete")
		}
	}
}
func TestPlanProtectsTransportAndIPv6(t *testing.T) {
	p, e := Plan([]string{"10.77.0.2/32"}, []string{"1.1.1.1"}, []string{"0.0.0.0/0"}, 1280)
	if e != nil {
		t.Fatal(e)
	}
	all := ""
	for _, s := range p {
		all += strings.Join(s.Args, " ") + "\n"
	}
	for _, want := range []string{"fwmark 0xb11 lookup main", "lookup main suppress_prefixlength 0", "unreachable default", "domain blink0 ~."} {
		if !strings.Contains(all, want) {
			t.Fatal(want)
		}
	}
}
func TestRejectNetworkArguments(t *testing.T) {
	for _, bad := range []string{"1.1.1.1;echo", "-4", "example.org", "1.1.1.1\n"} {
		if _, e := Plan([]string{"10.77.0.2/32"}, []string{bad}, []string{"0.0.0.0/0"}, 1280); e == nil {
			t.Fatal(bad)
		}
	}
}
func TestCleanupRetriesFailedUndo(t *testing.T) {
	r := &fakeRunner{}
	s := New(r)
	p := []Step{{"ip", []string{"add"}, []string{"del"}}}
	if e := s.Apply(p); e != nil {
		t.Fatal(e)
	}
	r.fail = 2
	if s.Close() == nil || len(s.undo) != 1 {
		t.Fatal("must retain failed cleanup")
	}
	if e := s.Close(); e != nil || len(s.undo) != 0 {
		t.Fatal("retry failed")
	}
}
