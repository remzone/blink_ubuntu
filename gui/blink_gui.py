#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Tk 8.6 GUI; all VPN and import logic lives in the Go executable."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import webbrowser
from urllib.parse import urlsplit

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
except ImportError:
    raise SystemExit("Установите GUI: sudo apt install python3-tk")

BG = "#101319"
PANEL = "#1b2029"
FG = "#eef3f8"
MUTED = "#98a7b9"
ACCENT = "#80ebba"


def binary_path():
    requested = os.environ.get("BLINK_BINARY")
    if requested:
        return str(Path(requested).resolve())
    installed = Path("/usr/bin/blink")
    return str(installed if installed.exists() else Path(__file__).resolve().parent.parent / "dist/blink")


def safe_vk_url(raw):
    try:
        u = urlsplit(raw)
        host = (u.hostname or "").lower()
        return (u.scheme == "https" and not u.username and not u.password
                and u.port in (None, 443) and not u.fragment
                and any(host == d or host.endswith("." + d) for d in ("vk.com", "vk.ru")))
    except ValueError:
        return False


class Blink:
    def __init__(self, root):
        self.root = root
        self.binary = binary_path()
        self.events = queue.Queue()
        self.proc = None
        self.busy = False
        self.closing = False
        self.profiles = []
        self.filtered = []
        self.status = tk.StringVar(value="Отключено")
        self.detail = tk.StringVar(value="Выберите профиль для подключения")
        self.search = tk.StringVar()
        self.selection = tk.StringVar()
        self.notice = tk.StringVar(value="Ubuntu 20.04+ · Xray / WireGuard / AmneziaWG / VK TURN")
        root.title("Blink · Ubuntu")
        root.geometry("840x680")
        root.minsize(620, 610)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=("DejaVu Sans", 11))
        style.configure("Muted.TLabel", foreground=MUTED, font=("DejaVu Sans", 10))
        style.configure("Title.TLabel", font=("DejaVu Sans", 26, "bold"))
        style.configure("Status.TLabel", font=("DejaVu Sans", 19, "bold"))
        style.configure("TButton", background=PANEL, foreground=FG, padding=(13, 10), font=("DejaVu Sans", 10))
        style.map("TButton", background=[("active", "#303c49")], foreground=[("disabled", "#667180")])
        style.configure("Connect.TButton", background=ACCENT, foreground=BG, font=("DejaVu Sans", 12, "bold"))
        style.map("Connect.TButton", background=[("active", "#a5f5d0")], foreground=[("disabled", "#667180")])
        style.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG, padding=8)
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG, padding=8)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)])
        frame = ttk.Frame(root, padding=28)
        frame.pack(fill="both", expand=True)
        heading = ttk.Frame(frame)
        heading.pack(fill="x")
        ttk.Label(heading, text="blink", style="Title.TLabel").pack(side="left")
        ttk.Label(heading, text="UBUNTU  /  0.1.0", style="Muted.TLabel").pack(side="right", pady=12)
        self.ring = tk.Canvas(frame, width=140, height=140, bg=BG, highlightthickness=0)
        self.ring.pack(pady=(15, 0))
        self.draw_ring(False)
        ttk.Label(frame, textvariable=self.status, style="Status.TLabel").pack()
        ttk.Label(frame, textvariable=self.detail, style="Muted.TLabel", wraplength=720, justify="center").pack(pady=(8, 22))
        ttk.Label(frame, text="ПРОФИЛЬ", style="Muted.TLabel").pack(anchor="w")
        search = ttk.Entry(frame, textvariable=self.search)
        search.pack(fill="x", pady=(8, 6))
        search.insert(0, "")
        self.combo = ttk.Combobox(frame, state="readonly", textvariable=self.selection)
        self.combo.pack(fill="x")
        self.search.trace_add("write", lambda *_: self.filter_profiles())
        self.connect_button = ttk.Button(frame, text="Подключить", style="Connect.TButton", command=self.toggle)
        self.connect_button.pack(fill="x", pady=16)
        row = ttk.Frame(frame)
        row.pack(fill="x")
        self.action_buttons = []
        for label, fn in (("Добавить", self.paste), ("Из файла", self.import_file), ("Обновить", self.refresh), ("Удалить", self.remove)):
            b = ttk.Button(row, text=label, command=fn)
            b.pack(side="left", fill="x", expand=True, padx=(0, 6))
            self.action_buttons.append(b)
        ttk.Label(frame, text="Поиск выше: название, страна или протокол", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(frame, textvariable=self.notice, style="Muted.TLabel", wraplength=740, justify="left").pack(anchor="w", pady=(24, 0))
        root.after(100, self.poll)
        self.load_profiles()

    def draw_ring(self, active):
        self.ring.delete("all")
        color = ACCENT if active else MUTED
        self.ring.create_oval(16, 16, 124, 124, outline=PANEL, width=10)
        self.ring.create_arc(16, 16, 124, 124, start=45, extent=270, style="arc", outline=color, width=5)
        self.ring.create_arc(51, 47, 89, 87, start=120, extent=300, style="arc", outline=color, width=4)
        self.ring.create_line(70, 41, 70, 67, fill=color, width=4)

    def worker(self, fn):
        def job():
            try:
                fn()
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("idle", None))
        self.busy = True
        self.update_buttons()
        threading.Thread(target=job, daemon=True).start()

    def invoke(self, args, data=None):
        p = subprocess.run([self.binary] + args, input=data, capture_output=True, text=True, timeout=180)
        if p.returncode:
            raise RuntimeError(p.stderr.strip()[-1200:] or "Команда не выполнена")
        return json.loads(p.stdout) if p.stdout.strip() else None

    def load_profiles(self):
        self.worker(lambda: self.events.put(("profiles", self.invoke(["list"]))))

    def filter_profiles(self):
        previous = self.selected_id()
        query = self.search.get().casefold().strip()
        self.filtered = [p for p in self.profiles if query in (p["name"] + " " + p["kind"]).casefold()]
        self.combo["values"] = [p["name"] + "  ·  " + p["kind"] for p in self.filtered]
        index = next((i for i, p in enumerate(self.filtered) if p["id"] == previous), 0)
        if self.filtered:
            self.combo.current(index)
        else:
            self.selection.set("")

    def selected_id(self):
        i = self.combo.current()
        return self.filtered[i]["id"] if 0 <= i < len(self.filtered) else None

    def import_data(self, args, data=None):
        def job():
            result = self.invoke(["import"] + args, data)
            text = "Добавлено: {}. Отклонено: {}.".format(result["imported"], result["rejected"])
            if result.get("notice"):
                text += " " + result["notice"]
            self.events.put(("notice", text))
            self.events.put(("profiles", self.invoke(["list"])))
        self.worker(job)

    def paste(self):
        win = tk.Toplevel(self.root)
        win.title("Импорт профиля или подписки")
        win.geometry("650x380")
        win.transient(self.root)
        ttk.Label(win, text="HTTPS-подписка, URI, Xray JSON, Clash YAML или WG/AWG .conf", wraplength=600).pack(padx=16, pady=12)
        text = tk.Text(win, wrap="word", bg=PANEL, fg=FG, insertbackground=FG, undo=False)
        text.pack(fill="both", expand=True, padx=16)
        def submit():
            data = text.get("1.0", "end-1c")
            win.destroy()
            if data.strip():
                self.import_data([], data)
        ttk.Button(win, text="Импортировать", command=submit).pack(pady=12)
        text.focus_set()

    def import_file(self):
        path = filedialog.askopenfilename(title="Конфигурация или подписка")
        if path:
            self.import_data(["--file", path])

    def refresh(self):
        def job():
            result = self.invoke(["refresh"])
            self.events.put(("notice", "Обновлено подписок: {}".format(result["updated"])))
            self.events.put(("profiles", self.invoke(["list"])))
        self.worker(job)

    def remove(self):
        chosen = self.selected_id()
        if chosen and messagebox.askyesno("Удалить профиль", "Удалить выбранный профиль из Blink?"):
            def job():
                self.invoke(["remove", chosen])
                self.events.put(("profiles", self.invoke(["list"])))
            self.worker(job)

    def toggle(self):
        if self.proc is not None:
            self.stop()
            return
        chosen = self.selected_id()
        if not chosen or self.busy:
            return
        self.status.set("Подключение…")
        self.detail.set("Подтвердите системный запрос прав для VPN")
        def job():
            profile = self.invoke(["export", chosen])
            # No shell, no secrets in argv, no root GUI or local HTTP server.
            proc = None
            try:
                proc = subprocess.Popen(["pkexec", self.binary, "session"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
                self.proc = proc
                proc.stdin.write(json.dumps(profile) + "\n")
                proc.stdin.flush()
                if self.closing:
                    self.stop()
                errors = []
                def drain():
                    for line in proc.stderr:
                        errors.append(line)
                        if len(errors) > 20:
                            del errors[0]
                reader = threading.Thread(target=drain, daemon=True)
                reader.start()
                for line in proc.stdout:
                    try:
                        self.events.put(("state", json.loads(line)))
                    except ValueError:
                        pass
                code = proc.wait()
                reader.join(timeout=1)
                if code and not self.closing:
                    self.events.put(("error", "".join(errors).strip()[-1200:] or "Подключение не выполнено (код {})".format(code)))
            finally:
                if proc is not None:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                    proc.wait()
                    proc.stdout.close()
                    proc.stderr.close()
                self.events.put(("disconnected", None))
        self.worker(job)

    def send(self, command):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.stdin.write(json.dumps(command) + "\n")
                self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def stop(self):
        self.status.set("Отключение…")
        self.send({"command": "stop"})
        if self.proc:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def captcha(self, challenge):
        url = challenge.get("image") or challenge.get("url")
        if url and safe_vk_url(url):
            if messagebox.askyesno("Проверка VK", "VK запросил ручную проверку. Открыть её в браузере?\n\nДля проверки с картинкой введите код. Современная CAPTCHA требует success token официального SDK; встроенного SDK в Linux-клиенте пока нет."):
                webbrowser.open(url)
        kind = "key" if challenge.get("image") else "token"
        value = simpledialog.askstring("Проверка VK", "Код с картинки:" if kind == "key" else "Success token официальной проверки VK (или Отмена):", show="*")
        if value:
            self.send({"command": "captcha", "id": challenge["id"], "kind": kind, "value": value})
        else:
            self.stop()

    def update_buttons(self):
        connected = self.proc is not None
        self.connect_button.configure(text="Отключить" if connected else "Подключить", state="normal" if connected or not self.busy else "disabled")
        for b in self.action_buttons:
            b.configure(state="disabled" if connected or self.busy else "normal")
        self.combo.configure(state="disabled" if connected or self.busy else "readonly")

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "profiles":
                    self.profiles = value
                    self.filter_profiles()
                elif kind == "notice":
                    self.notice.set(value)
                elif kind == "idle":
                    self.busy = False
                elif kind == "error" and not self.closing:
                    messagebox.showerror("Blink", value)
                    if self.proc is None:
                        self.status.set("Отключено")
                elif kind == "disconnected":
                    self.proc = None
                    self.status.set("Отключено")
                    self.detail.set("Маршруты VPN удалены; выберите профиль")
                    self.draw_ring(False)
                elif kind == "state":
                    state = value.get("state", "")
                    ready = value.get("routed", False)
                    self.status.set("Подключено" if ready else {"captcha_required": "Проверка VK", "stopping": "Отключение…"}.get(state, "Подключение…"))
                    stats = value.get("stats", {})
                    transferred = "↑ {:.1f} МиБ  ↓ {:.1f} МиБ".format(stats.get("tx", 0) / 1048576, stats.get("rx", 0) / 1048576)
                    self.detail.set(transferred + " · локальная сеть доступна" if ready else "Ожидание транспорта: " + state)
                    self.draw_ring(ready)
                    if "captcha" in value and not self.closing:
                        self.captcha(value["captcha"])
        except queue.Empty:
            pass
        self.update_buttons()
        if self.closing and self.proc is None and not self.busy:
            self.root.destroy()
            return
        self.root.after(100, self.poll)

    def close(self):
        self.closing = True
        self.stop()
        self.root.withdraw()


def main():
    if os.geteuid() == 0:
        raise SystemExit("Запускайте графический клиент от обычного пользователя: blink gui")
    root = tk.Tk()
    Blink(root)
    root.mainloop()


if __name__ == "__main__":
    main()
