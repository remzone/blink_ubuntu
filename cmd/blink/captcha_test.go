package main

import (
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestCaptchaAnswerBoundToChallengeAndTime(t *testing.T) {
	now := time.Unix(1000, 0)
	challenge := json.RawMessage(`{"id":"challenge","url":"https://vk.com/check","expires_at":1100}`)
	valid := `{"status":"success","id":"challenge","kind":"token","value":"private-token"}`
	answer, e := captchaAnswer([]byte(valid), challenge, now)
	if e != nil || answer.Command != "captcha" || answer.Value != "private-token" {
		t.Fatal(e)
	}
	for _, raw := range []string{strings.Replace(valid, `"challenge"`, `"other"`, 1), strings.Replace(valid, `"token"`, `"key"`, 1), strings.Replace(valid, `"success"`, `"cancelled"`, 1), strings.Replace(valid, `"private-token"`, `"bad\nvalue"`, 1)} {
		if _, e := captchaAnswer([]byte(raw), challenge, now); e == nil {
			t.Fatal("invalid answer accepted")
		}
	}
	if _, e := captchaAnswer([]byte(valid), challenge, time.Unix(1100, 0)); e == nil {
		t.Fatal("expired answer accepted")
	}
}
