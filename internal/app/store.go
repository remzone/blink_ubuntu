// SPDX-License-Identifier: GPL-3.0-only
package app

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

type Store struct {
	Profiles []Profile `json:"profiles"`
}

func ConfigDir() string {
	if d := os.Getenv("XDG_CONFIG_HOME"); filepath.IsAbs(d) {
		return filepath.Join(d, "blink")
	}
	d, _ := os.UserHomeDir()
	return filepath.Join(d, ".config", "blink")
}
func WithStore(dir string, fn func(*Store) error) error {
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	if err := os.Chmod(dir, 0700); err != nil {
		return err
	}
	f, err := os.OpenFile(filepath.Join(dir, ".lock"), os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return err
	}
	defer f.Close()
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		return err
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	store := Store{}
	path := filepath.Join(dir, "profiles.json")
	data, err := os.ReadFile(path)
	if err == nil {
		if len(data) > 8*Limit || json.Unmarshal(data, &store) != nil {
			return errors.New("хранилище профилей повреждено")
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	if err = fn(&store); err != nil {
		return err
	}
	data, err = json.MarshalIndent(store, "", "  ")
	if err != nil {
		return err
	}
	if len(data) > 8*Limit {
		return errors.New("хранилище превышает 8 МиБ")
	}
	temp, err := os.CreateTemp(dir, ".profiles-")
	if err != nil {
		return err
	}
	defer os.Remove(temp.Name())
	defer temp.Close()
	if _, err = temp.Write(data); err != nil {
		return err
	}
	if err = temp.Sync(); err != nil {
		return err
	}
	if err = temp.Close(); err != nil {
		return err
	}
	return os.Rename(temp.Name(), path)
}
func (s *Store) Merge(r ImportResult, feed string) error {
	var highest int64
	for _, p := range s.Profiles {
		if feed != "" && p.Feed == feed && p.Revision > highest {
			highest = p.Revision
		}
	}
	for _, p := range r.Profiles {
		if feed != "" && p.Revision < highest {
			return errors.New("сервер вернул устаревшую ревизию подписки")
		}
	}
	next := []Profile{}
	for _, p := range s.Profiles {
		if feed == "" || p.Feed != feed {
			next = append(next, p)
		}
	}
	for _, p := range r.Profiles {
		p.Feed = feed
		identify(&p)
		found := false
		for _, old := range next {
			if old.ID == p.ID {
				found = true
				break
			}
		}
		if !found {
			next = append(next, p)
		}
	}
	if len(next) > 1024 {
		return errors.New("не более 1024 профилей")
	}
	s.Profiles = next
	return nil
}
func Fetch(ctx context.Context, raw string) (string, error) {
	canonical, err := NormalizeURL(raw)
	if err != nil {
		return "", err
	}
	req, err := http.NewRequestWithContext(ctx, "GET", canonical, nil)
	if err != nil {
		return "", errors.New("некорректная ссылка")
	}
	origin := req.URL
	req.Header.Set("Accept", "*/*")
	req.Header.Set("User-Agent", "Blink-Ubuntu/0.1.0")
	client := &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(r *http.Request, via []*http.Request) error {
		if len(via) > 5 || r.URL.Scheme != "https" || !strings.EqualFold(r.URL.Host, origin.Host) || r.URL.User != nil {
			return errors.New("перенаправление за пределы HTTPS-источника запрещено")
		}
		return nil
	}}
	resp, err := client.Do(req)
	if err != nil {
		return "", errors.New("не удалось безопасно загрузить подписку")
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", errors.New("сервер отказал в загрузке подписки")
	}
	b, err := io.ReadAll(io.LimitReader(resp.Body, Limit+1))
	if err != nil || len(b) > Limit {
		return "", errors.New("подписка превышает лимит или загружена не полностью")
	}
	return string(b), nil
}
