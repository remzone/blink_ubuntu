// SPDX-License-Identifier: GPL-3.0-only
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

func guiFile(name string) (string, error) {
	binary, e := os.Executable()
	if e != nil {
		return "", e
	}
	binary, e = filepath.EvalSymlinks(binary)
	if e != nil {
		return "", e
	}
	for _, directory := range []string{filepath.Join(filepath.Dir(binary), "..", "gui"), "/usr/share/blink"} {
		p := filepath.Join(directory, name)
		if f, e := os.Stat(p); e == nil && f.Mode().IsRegular() {
			return p, nil
		}
	}
	return "", errors.New("GUI-компоненты Blink не установлены")
}
func captchaCommand() error {
	if os.Geteuid() == 0 {
		return errors.New("проверку VK запускайте от обычного пользователя")
	}
	helper, e := guiFile("captcha_window.py")
	if e != nil {
		return e
	}
	cmd := exec.Command("/usr/bin/python3", helper, "--standalone")
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	return cmd.Run()
}

type captchaResponse struct {
	Status string `json:"status"`
	ID     string `json:"id"`
	Kind   string `json:"kind"`
	Value  string `json:"value"`
}

func captchaAnswer(raw []byte, challenge json.RawMessage, now time.Time) (command, error) {
	var answer captchaResponse
	var c struct {
		ID      string `json:"id"`
		URL     string `json:"url"`
		Expires int64  `json:"expires_at"`
	}
	if len(raw) > 65536 || json.Unmarshal(raw, &answer) != nil || json.Unmarshal(challenge, &c) != nil {
		return command{}, errors.New("некорректный результат проверки VK")
	}
	expected := "key"
	if c.URL != "" {
		expected = "token"
	}
	if answer.Status != "success" || answer.ID != c.ID || answer.Kind != expected || c.Expires <= now.Unix() || len(answer.Value) < 1 || len(answer.Value) > 16384 || strings.ContainsAny(answer.Value, "\r\n\x00") {
		return command{}, errors.New("проверка VK отменена или устарела")
	}
	return command{Command: "captcha", ID: answer.ID, Kind: answer.Kind, Value: answer.Value}, nil
}
func solveCaptcha(ctx context.Context, challenge json.RawMessage) (command, error) {
	helper, e := guiFile("captcha_window.py")
	if e != nil {
		return command{}, e
	}
	child := exec.CommandContext(ctx, "/usr/bin/python3", helper)
	pipe, e := child.StdinPipe()
	if e != nil {
		return command{}, e
	}
	defer pipe.Close()
	var output bytes.Buffer
	child.Stdout = &output
	if e = child.Start(); e != nil {
		return command{}, e
	}
	if _, e = pipe.Write(append(append([]byte{}, challenge...), '\n')); e != nil {
		_ = child.Process.Kill()
		_ = child.Wait()
		return command{}, errors.New("окно проверки VK не открылось")
	}
	if e = child.Wait(); e != nil {
		return command{}, errors.New("проверка VK не завершена; проверьте установку WebKit")
	}
	return captchaAnswer(output.Bytes(), challenge, time.Now())
}
