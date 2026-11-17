import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("blink_gui", Path(os.environ.get("BLINK_GUI_DIR", str(Path(__file__).resolve().parents[1] / "gui"))) / "blink_gui.py")
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)

class GuiTest(unittest.TestCase):
    def test_captcha_origin_validation(self):
        for url in ("https://vk.com/captcha?x=1", "https://id.vk.ru/check"):
            self.assertTrue(gui.safe_vk_url(url))
        for url in ("http://vk.com/check", "https://vk.com.evil.org/", "https://evilvk.com/", "https://u@vk.com/", "https://vk.com:444/", "https://vk.com/#secret"):
            self.assertFalse(gui.safe_vk_url(url))

    @unittest.skipUnless(os.environ.get("DISPLAY"), "needs Xvfb/display")
    def test_window_filter_and_shutdown(self):
        root = gui.tk.Tk()
        try:
            with mock.patch.object(gui.Blink, "load_profiles"):
                app = gui.Blink(root)
            app.profiles = [{"id": "a", "name": "Germany", "kind": "xray"}, {"id": "b", "name": "Finland", "kind": "wireguard"}]
            app.filter_profiles()
            self.assertEqual(app.selected_id(), "a")
            app.search.set("fin")
            self.assertEqual(app.selected_id(), "b")
            app.search.set("no match")
            self.assertIsNone(app.selected_id())
            root.geometry("600x680")
            root.update()
            self.assertFalse(app.layout_wide)
            self.assertGreater(app.viewport.bbox("all")[3], 680)
            root.geometry("1120x820")
            root.update()
            self.assertTrue(app.layout_wide)
            app.route.set("vk")
            app.search.set("")
            app.profiles.append({"id": "vk", "name": "TURN server", "kind": "vk"})
            app.filter_profiles()
            self.assertEqual(app.selected_id(), "vk")
            self.assertEqual(app.connect_button.cget("style"), "Turn.TButton")
            app.ring.reduce_motion = True
            app.ring.state(busy=True)
            self.assertIsNone(app.ring.timer)
            root.update()
        finally:
            root.update_idletasks()
            root.destroy()


class CaptchaForwardingTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("DISPLAY"), "needs Xvfb/display")
    def test_only_current_connection_receives_answer(self):
        import io
        import time
        root = gui.tk.Tk()
        try:
            with mock.patch.object(gui.Blink, "load_profiles"):
                app = gui.Blink(root)
            class Process:
                stdin = io.StringIO()
                def poll(self):
                    return None
            app.proc = Process()
            app.busy = True
            app.connection_generation = 3
            app.captcha_generation = 7
            challenge = {"id": "current-id", "url": "https://vk.com/check", "expires_at": int(time.time())+200}
            answer = {"status": "success", "id": "current-id", "kind": "token", "value": "synthetic-only"}
            app.captcha_challenge = challenge
            app.events.put(("captcha_result", (2, 6, challenge, answer)))
            app.poll()
            self.assertEqual(app.proc.stdin.getvalue(), "")
            app.events.put(("captcha_result", (3, 7, challenge, answer)))
            app.poll()
            self.assertEqual(json.loads(app.proc.stdin.getvalue())["value"], "synthetic-only")
            self.assertIsNone(app.captcha_challenge)
        finally:
            root.update_idletasks()
            root.destroy()

if __name__ == "__main__":
    unittest.main()
