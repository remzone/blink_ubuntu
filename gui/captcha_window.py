#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-only
"""Unprivileged, ephemeral GTK/WebKit CAPTCHA window. Input/output are pipes."""
import io
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import urllib.request

from captcha_protocol import validate_challenge, validate_answer, js_config, vk_origin


def load_gtk():
    import gi
    gi.require_version("Gtk", "3.0")
    for version in ("4.1", "4.0"):
        try:
            gi.require_version("WebKit2", version)
            break
        except ValueError:
            continue
    else:
        raise RuntimeError("Установите gir1.2-webkit2-4.1 или gir1.2-webkit2-4.0")
    from gi.repository import Gtk, GLib, WebKit2, GdkPixbuf
    return Gtk, GLib, WebKit2, GdkPixbuf


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def load_image(url):
    vk_origin(url)
    opener = urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "Blink-Ubuntu/0.2.0"})
    with opener.open(request, timeout=10) as response:
        if response.status != 200:
            raise ValueError("Не удалось загрузить изображение")
        data = response.read(524289)
    if len(data) > 524288:
        raise ValueError("Изображение слишком большое")
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.width > 4096 or image.height > 4096 or image.width < 1 or image.height < 1:
            raise ValueError("Неподдерживаемый размер изображения")
        image.thumbnail((520, 220))
        output = io.BytesIO()
        image.convert("RGB").save(output, format="PNG")
        return output.getvalue()


class CaptchaWindow:
    def __init__(self, challenge, output=None, monitor_stdin=True):
        self.Gtk, self.GLib, self.WebKit, self.Pixbuf = load_gtk()
        Gtk, GLib, WebKit = self.Gtk, self.GLib, self.WebKit
        self.challenge = validate_challenge(challenge)
        self.output = output or sys.stdout
        self.finished = False
        self.web = None
        self.image_ready = False
        self.nonce = secrets.token_urlsafe(32)
        self.window = Gtk.Window(title="Blink · Проверка VK")
        self.window.set_default_size(640, 680 if "url" in self.challenge else 510)
        self.window.set_position(Gtk.WindowPosition.CENTER)
        self.window.set_border_width(24)
        self.window.connect("delete-event", self.cancel)
        self.window.connect("destroy", lambda *_: Gtk.main_quit() if Gtk.main_level() else None)
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background: #080d18; color: #f2f6ff; } label { color: #f2f6ff; } button { background: #1c293b; color: #f2f6ff; border: 1px solid #304057; border-radius: 15px; padding: 12px 18px; } button:focus { border-color: #93e8d1; } entry { background: #131d2c; color: #f2f6ff; border-radius: 12px; padding: 12px; }")
        self.window.get_style_context().add_provider_for_screen(self.window.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.window.add(box)
        heading = Gtk.Label(label="Один небольшой шаг.")
        heading.set_markup('<span size="xx-large" weight="bold">Один небольшой шаг.</span>')
        heading.set_xalign(0)
        box.pack_start(heading, False, False, 0)
        subtitle = Gtk.Label(label="Пройдите проверку VK — Blink продолжит подключение.")
        subtitle.set_xalign(0)
        subtitle.set_line_wrap(True)
        box.pack_start(subtitle, False, False, 0)
        self.message = Gtk.Label(label="Загружаем проверку…")
        self.message.set_line_wrap(True)
        self.message.set_xalign(0)
        box.pack_start(self.message, False, False, 0)
        if "url" in self.challenge:
            context = WebKit.WebContext.new_ephemeral()
            context.set_tls_errors_policy(WebKit.TLSErrorsPolicy.FAIL)
            self.manager = WebKit.UserContentManager()
            if not self.manager.register_script_message_handler_in_world("blinkCaptcha", "blink-captcha-private"):
                raise RuntimeError("Не удалось открыть приватный канал проверки")
            self.manager.connect("script-message-received::blinkCaptcha", self.on_message)
            source = Path(__file__).with_name("vendor").joinpath("vkid-captcha-2.0.0.js").read_text()
            shell = Path(__file__).with_name("captcha_shell.js").read_text()
            script = source + "\n" + shell.replace("__BLINK_CONFIG__", js_config(self.challenge, self.nonce))
            self.manager.add_script(WebKit.UserScript.new_for_world(script, WebKit.UserContentInjectedFrames.TOP_FRAME, WebKit.UserScriptInjectionTime.END, "blink-captcha-private", None, None))
            self.web = WebKit.WebView(web_context=context, user_content_manager=self.manager)
            settings = self.web.get_settings()
            settings.set_enable_developer_extras(False)
            settings.set_allow_file_access_from_file_urls(False)
            settings.set_allow_universal_access_from_file_urls(False)
            settings.set_enable_html5_database(False)
            settings.set_enable_html5_local_storage(False)
            settings.set_javascript_can_open_windows_automatically(False)
            self.web.connect("decide-policy", self.decide_policy)
            self.web.connect("permission-request", lambda _, request: request.deny() or True)
            self.web.connect("load-failed-with-tls-errors", lambda *_: self.failed("Не удалось проверить HTTPS-сертификат VK") or True)
            self.web.connect("web-process-terminated", lambda *_: self.failed("Окно проверки закрыто; подключитесь заново"))
            self.web.connect("context-menu", lambda *_: True)
            box.pack_start(self.web, True, True, 0)
            self.web.load_html('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; frame-src https://vk.com https://*.vk.com https://vk.ru https://*.vk.ru"><style>html,body,#captcha{margin:0;width:100%;height:100%;background:#080d18;color:#f2f6ff}iframe{border:0}</style><div id="captcha"></div></html>', "https://blink.invalid/")
            self.message.set_text("Решите задание в окне ниже. Результат передастся автоматически.")
        else:
            self.picture = Gtk.Image()
            box.pack_start(self.picture, True, True, 0)
            self.entry = Gtk.Entry()
            self.entry.set_placeholder_text("Код с изображения")
            self.entry.set_max_length(256)
            self.entry.connect("activate", self.submit_image)
            box.pack_start(self.entry, False, False, 0)
            self.submit = Gtk.Button(label="Продолжить подключение")
            self.submit.set_sensitive(False)
            self.submit.connect("clicked", self.submit_image)
            box.pack_start(self.submit, False, False, 0)
            threading.Thread(target=self.fetch_image, daemon=True).start()
        retry = Gtk.Button(label="Повторить загрузку проверки")
        retry.connect("clicked", lambda *_: self.web.reload() if self.web else threading.Thread(target=self.fetch_image, daemon=True).start())
        box.pack_start(retry, False, False, 0)
        self.countdown = Gtk.Label()
        self.countdown.set_xalign(0)
        box.pack_start(self.countdown, False, False, 0)
        cancel = Gtk.Button(label="Отменить подключение")
        cancel.connect("clicked", self.cancel)
        box.pack_start(cancel, False, False, 0)
        self.timer_id = GLib.timeout_add(1000, self.tick)
        self.stdin_watch = GLib.io_add_watch(sys.stdin.fileno(), GLib.IO_HUP | GLib.IO_IN | GLib.IO_ERR, self.parent_closed) if monitor_stdin else None
        self.tick()
        self.window.show_all()

    def parent_closed(self, *_):
        self.finish("cancelled")
        return False

    def tick(self):
        if self.finished:
            return False
        seconds = self.challenge["expires_at"] - int(time.time())
        if seconds <= 0:
            self.finish("expired")
            return False
        self.countdown.set_text("Проверка действует ещё {}:{:02d}".format(seconds // 60, seconds % 60))
        return True

    def decide_policy(self, web, decision, kind):
        WebKit = self.WebKit
        if kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        if kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_request().get_uri()
            if uri in ("https://blink.invalid/", "about:blank"):
                return False
            try:
                if vk_origin(uri) == vk_origin(self.challenge["url"]):
                    return False
            except ValueError:
                pass
            decision.ignore()
            return True
        return False

    def on_message(self, manager, result):
        if self.finished:
            return
        try:
            raw = result.get_js_value().to_string()
            if len(raw) > 65536:
                return
            answer = json.loads(raw)
            if answer.get("nonce") != self.nonce or answer.get("id") != self.challenge["id"]:
                return
            if answer.get("status") == "success":
                command = validate_answer(answer, self.challenge)
                self.finish("success", command["value"], "token")
            elif answer.get("status") == "cancelled":
                self.finish("cancelled")
            else:
                self.failed("VK не завершил проверку. Повторите подключение.")
        except (ValueError, TypeError, AttributeError):
            self.failed("Некорректный или устаревший результат проверки")

    def fetch_image(self):
        try:
            data = load_image(self.challenge["image"])
            self.GLib.idle_add(self.show_image, data)
        except Exception:
            self.GLib.idle_add(self.failed, "Не удалось загрузить изображение VK. Повторите подключение.")

    def show_image(self, data):
        if self.finished:
            return False
        loader = self.Pixbuf.PixbufLoader.new_with_type("png")
        loader.write(data)
        loader.close()
        self.picture.set_from_pixbuf(loader.get_pixbuf())
        self.image_ready = True
        self.submit.set_sensitive(True)
        self.message.set_text("Введите код с изображения. Проверку выполняете вы.")
        self.entry.grab_focus()
        return False

    def submit_image(self, *_):
        if self.image_ready and self.entry.get_text().strip():
            self.finish("success", self.entry.get_text().strip(), "key")

    def failed(self, message):
        if not self.finished:
            self.message.set_text(message)
        return False

    def cancel(self, *_):
        self.finish("cancelled")
        return True

    def finish(self, status, value="", kind=""):
        if self.finished:
            return
        if status == "success":
            answer = {"status": status, "id": self.challenge["id"], "kind": kind, "value": value}
            try:
                validate_answer(answer, self.challenge)
            except ValueError:
                status, value, kind = "expired", "", ""
        self.finished = True
        if getattr(self, "timer_id", None):
            self.GLib.source_remove(self.timer_id)
            self.timer_id = None
        if getattr(self, "stdin_watch", None):
            self.GLib.source_remove(self.stdin_watch)
            self.stdin_watch = None
        response = {"status": status, "id": self.challenge["id"], "kind": kind, "value": value}
        try:
            self.output.write(json.dumps(response) + "\n")
            self.output.flush()
        except (BrokenPipeError, OSError):
            pass
        if self.web:
            self.web.stop_loading()
        self.window.destroy()


def main():
    if os.geteuid() == 0:
        raise SystemExit("Окно проверки VK запускается обычным пользователем")
    try:
        raw = sys.stdin.buffer.readline(65537)
        if len(raw) > 65536 or not raw.endswith(b"\n"):
            raise ValueError("Некорректная проверка")
        challenge = validate_challenge(json.loads(raw))
        window = CaptchaWindow(challenge, monitor_stdin="--standalone" not in sys.argv[1:])
        if not window.finished:
            window.Gtk.main()
    except Exception:
        print(json.dumps({"status": "error"}))
        print("Не удалось открыть проверку VK. Проверьте установку WebKit/GTK и сеть.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
