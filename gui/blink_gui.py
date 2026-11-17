#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Tk 8.6 GUI; all VPN and import logic lives in the Go executable."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from captcha_protocol import validate_challenge, validate_answer, vk_origin
from theme import BG, PANEL, INK, FIELD, FG, MUTED, ACCENT, ICE, VK, Card, Orbit, configure

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
except ImportError:
    raise SystemExit("Установите GUI: sudo apt install python3-tk")


def binary_path():
    requested = os.environ.get("BLINK_BINARY")
    if requested:
        return str(Path(requested).resolve())
    installed = Path("/usr/bin/blink")
    return str(installed if installed.exists() else Path(__file__).resolve().parent.parent / "dist/blink")


def safe_vk_url(raw):
    try:
        vk_origin(raw)
        return True
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
        self.connection_generation = 0
        self.captcha_generation = 0
        self.captcha_proc = None
        self.captcha_challenge = None
        self.last_state = "stopped"
        self.routed = False
        self.status = tk.StringVar(value="Ваше подключение")
        self.detail = tk.StringVar(value="Выберите сервер и подключитесь в один шаг.")
        self.search = tk.StringVar()
        self.selection = tk.StringVar()
        self.route = tk.StringVar(value="vpn")
        self.notice = tk.StringVar(value="Добавьте профиль или подписку — серверы появятся здесь.")
        self.mode_hint = tk.StringVar(value="Обычный VPN · напрямую к вашему серверу")
        self.badge = tk.StringVar(value="VPN выключен")
        root.title("Blink · Ubuntu")
        root.geometry("{}x{}".format(min(1120, max(560, root.winfo_screenwidth()-100)), min(900, max(620, root.winfo_screenheight()-100))))
        root.minsize(560, 620)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.style = configure(root)
        self.viewport = tk.Canvas(root, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=self.viewport.yview)
        self.viewport.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.viewport.pack(fill="both", expand=True)
        self.page = ttk.Frame(self.viewport, padding=(26, 24))
        self.page_window = self.viewport.create_window(0, 0, window=self.page, anchor="nw")
        self.page.bind("<Configure>", lambda _: self.viewport.configure(scrollregion=self.viewport.bbox("all")))
        self.viewport.bind("<Configure>", self.responsive)
        root.bind("<Button-4>", lambda _: self.viewport.yview_scroll(-2, "units"))
        root.bind("<Button-5>", lambda _: self.viewport.yview_scroll(2, "units"))
        root.bind("<MouseWheel>", lambda e: self.viewport.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        masthead = ttk.Frame(self.page)
        masthead.pack(fill="x")
        ttk.Label(masthead, text="◈  B L I N K", foreground=ACCENT, font=("DejaVu Sans", 11, "bold")).pack(side="left")
        ttk.Label(masthead, text="UBUNTU  /  0.2.0", style="Muted.TLabel").pack(side="right")
        self.headline = ttk.Label(self.page, text="Ваша сеть,\nпод вашим контролем.", font=("DejaVu Sans", 29, "bold"))
        self.headline.pack(anchor="w", pady=(22, 9))
        ttk.Label(self.page, text="Выберите маршрут. Остальное — в Blink.", style="Muted.TLabel").pack(anchor="w", pady=(0, 24))
        self.columns = ttk.Frame(self.page)
        self.columns.pack(fill="x")
        self.columns.columnconfigure(0, weight=11, uniform="panels")
        self.columns.columnconfigure(1, weight=10, uniform="panels")
        self.hero = Card(self.columns, hero=True)
        body = self.hero.body
        top = ttk.Frame(body, style="Hero.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="BLINK CONNECT", style="HeroMuted.TLabel", font=("DejaVu Sans", 9, "bold")).pack(side="left")
        ttk.Label(top, textvariable=self.badge, style="HeroMuted.TLabel").pack(side="right")
        self.ring = Orbit(body, root)
        self.ring.pack(pady=(9, 4))
        self.mode_buttons = []
        self.style.configure("Route.Toolbutton", background=FIELD, bordercolor=FIELD, lightcolor=FIELD, darkcolor=FIELD, foreground=MUTED, padding=(14, 10), font=("DejaVu Sans", 10, "bold"))
        self.style.map("Route.Toolbutton", background=[("selected", "#30495b"), ("active", "#263e50")], foreground=[("selected", FG)])
        mode = ttk.Frame(body, style="Hero.TFrame")
        mode.pack(fill="x", pady=(0, 16))
        for label, value in (("Обычный VPN", "vpn"), ("Через VK · TURN", "vk")):
            button = ttk.Radiobutton(mode, text=label, variable=self.route, value=value, style="Route.Toolbutton", command=self.filter_profiles)
            button.pack(side="left", fill="x", expand=True, padx=2)
            self.mode_buttons.append(button)
        ttk.Label(body, textvariable=self.status, style="Status.TLabel", anchor="center").pack(fill="x")
        self.detail_label = ttk.Label(body, textvariable=self.detail, style="HeroMuted.TLabel", justify="center", anchor="center", wraplength=380)
        self.detail_label.pack(fill="x", pady=(9, 15))
        self.combo = ttk.Combobox(body, state="readonly", textvariable=self.selection)
        self.combo.pack(fill="x")
        self.connect_button = ttk.Button(body, text="Подключить", style="Connect.TButton", command=self.toggle)
        self.connect_button.pack(fill="x", pady=(16, 10))
        self.hint_label = ttk.Label(body, textvariable=self.mode_hint, style="HeroMuted.TLabel", justify="center", anchor="center", wraplength=380)
        self.hint_label.pack(fill="x")
        self.side = ttk.Frame(self.columns)
        library = Card(self.side)
        library.pack(fill="x")
        box = library.body
        ttk.Label(box, text="Всё начинается с сервера", style="Card.TLabel", font=("DejaVu Sans", 16, "bold")).pack(anchor="w")
        ttk.Label(box, text="Ваша библиотека профилей", style="CardMuted.TLabel").pack(anchor="w", pady=(6, 16))
        ttk.Entry(box, textvariable=self.search).pack(fill="x")
        ttk.Label(box, text="Поиск по названию, стране и протоколу", style="CardMuted.TLabel", font=("DejaVu Sans", 9)).pack(anchor="w", pady=(7, 16))
        grid = ttk.Frame(box, style="Card.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure((0, 1), weight=1)
        self.action_buttons = []
        for i, (label, fn) in enumerate((("+  Добавить", self.paste), ("Из файла", self.import_file), ("Обновить", self.refresh), ("Удалить", self.remove))):
            button = ttk.Button(grid, text=label, style="Blink.TButton", command=fn)
            button.grid(row=i//2, column=i%2, sticky="ew", padx=(0, 5) if i%2 == 0 else (5, 0), pady=5)
            self.action_buttons.append(button)
        self.notice_label = ttk.Label(box, textvariable=self.notice, style="CardMuted.TLabel", wraplength=370, justify="left")
        self.notice_label.pack(fill="x", pady=(16, 0))
        self.captcha_card = Card(self.side)
        self.captcha_card.pack(fill="x", pady=(18, 0))
        box = self.captcha_card.body
        ttk.Label(box, text="Один небольшой шаг.", style="Card.TLabel", font=("DejaVu Sans", 16, "bold")).pack(anchor="w")
        self.captcha_note = tk.StringVar(value="Если VK попросит проверку, она откроется прямо в Blink. Вручную, без копирования токенов.")
        self.captcha_label = ttk.Label(box, textvariable=self.captcha_note, style="CardMuted.TLabel", wraplength=370, justify="left")
        self.captcha_label.pack(fill="x", pady=(8, 16))
        self.captcha_button = ttk.Button(box, text="Открыть проверку VK", style="Blink.TButton", command=self.reopen_captcha, state="disabled")
        self.captcha_button.pack(fill="x")
        self.search.trace_add("write", lambda *_: self.filter_profiles())
        footer = ttk.Frame(self.page)
        footer.pack(fill="x", pady=(22, 0))
        self.footer_label = ttk.Label(footer, text="◈  Ключи остаются на вашем компьютере. Вся сеть — под вашим контролем.", style="Muted.TLabel", wraplength=900)
        self.footer_label.pack(anchor="w")
        self.layout_wide = None
        self.poll_timer = root.after(100, self.poll, True)
        root.bind("<Destroy>", self.on_destroy, add="+")
        self.load_profiles()

    def responsive(self, event):
        width = min(event.width, 1200)
        self.viewport.coords(self.page_window, max(0, (event.width-width)//2), 0)
        self.viewport.itemconfigure(self.page_window, width=width)
        wide = width >= 960
        if wide != self.layout_wide:
            self.hero.grid_forget()
            self.side.grid_forget()
            if wide:
                self.hero.grid(row=0, column=0, sticky="new", padx=(0, 11))
                self.side.grid(row=0, column=1, sticky="new", padx=(11, 0))
            else:
                self.hero.grid(row=0, column=0, columnspan=2, sticky="new")
                self.side.grid(row=1, column=0, columnspan=2, sticky="new", pady=(18, 0))
            self.layout_wide = wide
        card_width = (width-74)//2 if wide else width-52
        for label in (self.detail_label, self.hint_label, self.notice_label, self.captcha_label):
            label.configure(wraplength=max(200, card_width-52))
        self.footer_label.configure(wraplength=max(200, width-60))
        self.headline.configure(font=("DejaVu Sans", 29 if width >= 700 else 24, "bold"))

    def draw_ring(self, active):
        color = VK if self.route.get() == "vk" else ACCENT
        self.ring.state(active=active, busy=self.proc is not None and not active, color=color)

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
        self.filtered = [p for p in self.profiles if (p["kind"] == "vk") == (self.route.get() == "vk") and query in (p["name"] + " " + p["kind"]).casefold()]
        self.combo["values"] = [p["name"] + "  ·  " + p["kind"] for p in self.filtered]
        index = next((i for i, p in enumerate(self.filtered) if p["id"] == previous), 0)
        if self.filtered:
            self.combo.current(index)
        else:
            self.selection.set("")
        self.mode_hint.set("Через VK · TURN до вашего сервера" if self.route.get() == "vk" else "Обычный VPN · напрямую к вашему серверу")
        self.connect_button.configure(style="Turn.TButton" if self.route.get() == "vk" else "Connect.TButton")
        self.draw_ring(self.routed)

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
        ttk.Button(win, text="Импортировать", style="Connect.TButton", command=submit).pack(pady=12)
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
        self.connection_generation += 1
        self.status.set("Создаём защищённый маршрут")
        self.badge.set("Подключение")
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
        self.cancel_captcha()
        self.status.set("Отключение…")
        self.send({"command": "stop"})
        if self.proc:
            try:
                self.proc.stdin.close()
            except OSError:
                pass

    def cancel_captcha(self):
        self.captcha_generation += 1
        self.captcha_challenge = None
        if self.captcha_proc is not None:
            try:
                self.captcha_proc.stdin.close()
            except (OSError, ValueError):
                pass
        self.captcha_button.configure(state="disabled")

    def reopen_captcha(self):
        if self.captcha_challenge and self.captcha_proc is None:
            self.captcha(self.captcha_challenge)

    def captcha(self, challenge):
        try:
            checked = validate_challenge(challenge)
        except ValueError:
            self.captcha_note.set("Проверка VK устарела. Подключитесь заново.")
            self.stop()
            return
        self.cancel_captcha()
        self.captcha_challenge = checked
        self.captcha_generation += 1
        generation = self.captcha_generation
        session = self.connection_generation
        self.captcha_note.set("Пройдите задание в окне VK. Blink продолжит это подключение автоматически.")
        self.captcha_button.configure(state="disabled")
        def job():
            proc = None
            try:
                proc = subprocess.Popen(["/usr/bin/python3", str(Path(__file__).with_name("captcha_window.py"))], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                if self.closing or generation != self.captcha_generation:
                    proc.stdin.close()
                    return
                self.captcha_proc = proc
                proc.stdin.write(json.dumps(checked) + "\n")
                proc.stdin.flush()
                if self.closing or generation != self.captcha_generation:
                    proc.stdin.close()
                line = proc.stdout.readline(65537)
                if len(line) > 65536:
                    raise ValueError("CAPTCHA response too large")
                result = json.loads(line)
                self.events.put(("captcha_result", (session, generation, checked, result)))
            except Exception:
                self.events.put(("captcha_error", (session, generation)))
            finally:
                if proc is not None:
                    try:
                        proc.stdin.close()
                    except (OSError, ValueError):
                        pass
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.terminate()
                        try:
                            proc.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()
                    proc.stdout.close()
                if self.captcha_proc is proc:
                    self.captcha_proc = None
        threading.Thread(target=job, daemon=True).start()

    def update_buttons(self):
        connected = self.proc is not None
        self.connect_button.configure(text="Отключить" if connected else "Подключить", state="normal" if connected or not self.busy else "disabled")
        for b in self.action_buttons:
            b.configure(state="disabled" if connected or self.busy else "normal")
        self.combo.configure(state="disabled" if connected or self.busy else "readonly")
        for button in self.mode_buttons:
            button.configure(state="disabled" if connected or self.busy else "normal")
        pending = self.captcha_challenge and self.captcha_challenge["expires_at"] > time.time()
        self.captcha_button.configure(state="normal" if connected and pending and self.captcha_proc is None else "disabled")

    def on_destroy(self, event):
        if event.widget is not self.root:
            return
        self.closing = True
        self.captcha_generation += 1
        if self.poll_timer is not None:
            try:
                self.root.after_cancel(self.poll_timer)
            except tk.TclError:
                pass
            self.poll_timer = None
        for process in (self.proc, self.captcha_proc):
            if process is not None:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass

    def poll(self, from_timer=False):
        if self.poll_timer is not None and not from_timer:
            self.root.after_cancel(self.poll_timer)
        self.poll_timer = None
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "profiles":
                    self.profiles = value
                    if not any(p["kind"] != "vk" for p in value) and any(p["kind"] == "vk" for p in value):
                        self.route.set("vk")
                    self.filter_profiles()
                elif kind == "notice":
                    self.notice.set(value)
                elif kind == "idle":
                    self.busy = False
                elif kind == "error" and not self.closing:
                    messagebox.showerror("Blink", value)
                    if self.proc is None:
                        self.status.set("Отключено")
                elif kind == "captcha_result":
                    session, generation, challenge, result = value
                    if session == self.connection_generation and generation == self.captcha_generation and not self.closing:
                        if result.get("status") == "success":
                            try:
                                self.send(validate_answer(result, challenge))
                                self.captcha_challenge = None
                                self.captcha_note.set("Проверка передана VK. Продолжаем подключение…")
                            except ValueError:
                                self.captcha_note.set("Проверка устарела. Подключитесь заново.")
                                self.stop()
                        elif result.get("status") in ("cancelled", "expired"):
                            self.stop()
                        else:
                            self.captcha_note.set("Не удалось открыть проверку. Нажмите «Открыть проверку VK» или отмените подключение.")
                elif kind == "captcha_error":
                    session, generation = value
                    if session == self.connection_generation and generation == self.captcha_generation:
                        self.captcha_note.set("Не удалось открыть проверку. Установите зависимости WebKit из пакета Blink и повторите.")
                elif kind == "disconnected":
                    self.cancel_captcha()
                    self.proc = None
                    self.routed = False
                    self.badge.set("VPN выключен")
                    self.status.set("Отключено")
                    self.detail.set("Маршруты VPN удалены; выберите профиль")
                    self.draw_ring(False)
                elif kind == "state":
                    state = value.get("state", "")
                    ready = value.get("routed", False)
                    self.routed = ready
                    self.badge.set("Вы на связи" if ready else "Проверка VK" if state == "captcha_required" else "Подключение")
                    self.status.set("Подключено" if ready else {"captcha_required": "Проверка VK", "stopping": "Отключение…"}.get(state, "Подключение…"))
                    if "captcha_accepted" in value:
                        self.captcha_note.set("Проверка принята. Продолжаем подключение…" if value["captcha_accepted"] else "VK отклонил результат или проверка устарела.")
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
            self.ring.pause()
            self.root.destroy()
            return
        self.poll_timer = self.root.after(100, self.poll, True)

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
