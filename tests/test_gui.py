import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("blink_gui", Path(__file__).resolve().parents[1] / "gui/blink_gui.py")
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
            root.update()
        finally:
            root.destroy()

if __name__ == "__main__":
    unittest.main()
