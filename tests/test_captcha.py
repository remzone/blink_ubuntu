import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

GUI = Path(os.environ.get("BLINK_GUI_DIR", str(Path(__file__).resolve().parents[1] / "gui")))
sys.path.insert(0, str(GUI))
from captcha_protocol import validate_challenge, validate_answer, vk_origin, js_config
import captcha_window


def challenge(modern=True):
    return {"id": "test-challenge", "expires_at": int(time.time())+200,
            "url" if modern else "image": "https://vk.com/blink-synthetic-fixture"}


class ProtocolTest(unittest.TestCase):
    def test_origin_confusion_rejected(self):
        self.assertEqual(vk_origin("https://ID.VK.COM:443/check"), "https://id.vk.com")
        for value in ("https://vk.com.evil.org/", "https://evilvk.com/", "http://vk.com/", "https://u@vk.com/", "https://vk.com/#secret", "https://vk.com:444/", "https://vk.com/\n", "https://vk.com\\@evil.org/"):
            with self.assertRaises(ValueError):
                vk_origin(value)

    def test_binding_expiry_type_and_controls(self):
        c = challenge()
        good = {"status": "success", "id": c["id"], "kind": "token", "value": "private-value"}
        self.assertEqual(validate_answer(good, c)["command"], "captcha")
        for changes in ({"id": "other"}, {"kind": "key"}, {"status": "cancelled"}, {"value": "bad\nvalue"}, {"value": "x"*16385}):
            with self.assertRaises(ValueError):
                validate_answer(dict(good, **changes), c)
        with self.assertRaises(ValueError):
            validate_answer(good, c, c["expires_at"])
        with self.assertRaises(ValueError):
            validate_challenge(dict(c, expires_at=True))

    def test_modern_preferred_and_config_escaped(self):
        c = challenge()
        c["image"] = "https://vk.com/image"
        self.assertNotIn("image", validate_challenge(c))
        c["url"] += "?x=</script>"
        self.assertNotIn("</script>", js_config(c, "nonce"))


@unittest.skipUnless(os.environ.get("BLINK_WEBKIT_TEST") == "1" and os.environ.get("DISPLAY"), "needs isolated WebKit/Xvfb test environment")
class WebKitTest(unittest.TestCase):
    def wait(self, predicate, seconds=15):
        _, GLib, _, _ = captcha_window.load_gtk()
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            if predicate():
                return
            time.sleep(.01)
        self.fail("WebKit callback timed out")

    def run_js(self, window, script, world=None):
        results = []
        def done(web, result, *_):
            try:
                value = web.run_javascript_in_world_finish(result) if world else web.run_javascript_finish(result)
                results.append(value.get_js_value().to_string())
            except Exception as exc:
                results.append("ERROR:"+str(exc))
        if world:
            window.web.run_javascript_in_world(script, world, None, done, None)
        else:
            window.web.run_javascript(script, None, done, None)
        self.wait(lambda: bool(results))
        return results[0]

    def modern(self):
        # Cancel the synthetic remote iframe before any request is sent.
        original = captcha_window.CaptchaWindow.decide_policy
        def block_fixture(instance, web, decision, kind):
            if kind == instance.WebKit.PolicyDecisionType.NAVIGATION_ACTION and "blink-synthetic-fixture" in decision.get_request().get_uri():
                decision.ignore()
                return True
            return original(instance, web, decision, kind)
        output = io.StringIO()
        with mock.patch.object(captcha_window.CaptchaWindow, "decide_policy", block_fixture):
            window = captcha_window.CaptchaWindow(challenge(), output, monitor_stdin=False)
            self.wait(lambda: not window.web.is_loading())
        return window, output

    def test_private_world_sdk_and_callback(self):
        window, output = self.modern()
        try:
            self.assertEqual(self.run_js(window, "typeof VKIDCaptchaSDK"), "undefined")
            self.assertEqual(self.run_js(window, "typeof VKIDCaptchaSDK.CaptchaWidget", "blink-captcha-private"), "function")
            self.assertEqual(self.run_js(window, "typeof window.webkit === 'undefined' || !window.webkit.messageHandlers || typeof window.webkit.messageHandlers.blinkCaptcha === 'undefined'"), "true")
            self.assertTrue(window.web.get_context().is_ephemeral())
            answer = {"nonce": window.nonce, "id": window.challenge["id"], "status": "success", "kind": "token", "value": "synthetic-token"}
            script = "window.webkit.messageHandlers.blinkCaptcha.postMessage("+json.dumps(json.dumps(answer))+")"
            self.run_js(window, script, "blink-captcha-private")
            self.wait(lambda: window.finished)
            result = json.loads(output.getvalue())
            self.assertEqual(result["value"], "synthetic-token")
            self.assertEqual(result["id"], window.challenge["id"])
        finally:
            if not window.finished:
                window.finish("cancelled")

    def test_cancel_and_bad_nonce(self):
        window, output = self.modern()
        class Value:
            def to_string(self):
                return json.dumps({"nonce": "wrong", "id": window.challenge["id"], "status": "success", "kind": "token", "value": "not-accepted"})
        class Result:
            def get_js_value(self):
                return Value()
        window.on_message(None, Result())
        self.assertFalse(window.finished)
        window.cancel()
        self.assertEqual(json.loads(output.getvalue())["status"], "cancelled")

    def test_legacy_picture_code_and_expiry(self):
        from PIL import Image
        data = io.BytesIO()
        Image.new("RGB", (100, 40), "white").save(data, "PNG")
        output = io.StringIO()
        with mock.patch.object(captcha_window.CaptchaWindow, "fetch_image"):
            window = captcha_window.CaptchaWindow(challenge(False), output, monitor_stdin=False)
        window.show_image(data.getvalue())
        window.entry.set_text("12345")
        window.submit_image()
        result = json.loads(output.getvalue())
        self.assertEqual((result["kind"], result["value"]), ("key", "12345"))
        output = io.StringIO()
        with mock.patch.object(captcha_window.CaptchaWindow, "fetch_image"):
            window = captcha_window.CaptchaWindow(challenge(False), output, monitor_stdin=False)
        window.challenge["expires_at"] = int(time.time())-1
        window.tick()
        self.assertEqual(json.loads(output.getvalue())["status"], "expired")


if __name__ == "__main__":
    unittest.main()
