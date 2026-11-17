# SPDX-License-Identifier: GPL-3.0-only
"""Credential-free validation for the private CAPTCHA process protocol."""
import json
import time
from urllib.parse import urlsplit

LIMIT = 16384


def vk_origin(raw):
    if not isinstance(raw, str) or not raw or len(raw.encode("utf-8")) > LIMIT:
        raise ValueError("Некорректный адрес проверки VK")
    if any(ord(c) < 33 or ord(c) == 127 for c in raw) or "\\" in raw:
        raise ValueError("Некорректный адрес проверки VK")
    try:
        u = urlsplit(raw)
        host = (u.hostname or "").lower()
        if (u.scheme != "https" or u.username is not None or u.password is not None
                or u.port not in (None, 443) or u.fragment
                or not any(host == d or host.endswith("." + d) for d in ("vk.com", "vk.ru"))):
            raise ValueError()
    except ValueError:
        raise ValueError("Проверка должна использовать HTTPS-домен VK") from None
    return "https://" + host


def validate_challenge(value, now=None):
    now = int(time.time() if now is None else now)
    if not isinstance(value, dict):
        raise ValueError("Некорректная проверка VK")
    identifier = value.get("id")
    expiry = value.get("expires_at")
    if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 128
            or not all(c.isascii() and (c.isalnum() or c in "-_") for c in identifier)
            or not isinstance(expiry, int) or isinstance(expiry, bool)
            or expiry <= now or expiry > now + 305):
        raise ValueError("Проверка VK устарела; подключитесь заново")
    # Like Android, prefer the modern redirect when both fields are present.
    key = "url" if value.get("url") else "image"
    vk_origin(value.get(key))
    return {"id": identifier, "expires_at": expiry, key: value[key]}


def validate_answer(answer, challenge, now=None):
    checked = validate_challenge(challenge, now)
    if not isinstance(answer, dict) or answer.get("status") != "success" or answer.get("id") != checked["id"]:
        raise ValueError("Проверка VK не завершена")
    expected = "token" if "url" in checked else "key"
    value = answer.get("value")
    if (answer.get("kind") != expected or not isinstance(value, str) or not 1 <= len(value.encode("utf-8")) <= LIMIT
            or any(c in value for c in "\r\n\x00")):
        raise ValueError("Некорректный результат проверки VK")
    return {"command": "captcha", "id": checked["id"], "kind": expected, "value": value}


def js_config(challenge, nonce):
    # Used inside an isolated JS world, never interpolated into an HTML attribute.
    value = json.dumps({"id": challenge["id"], "link": challenge["url"], "nonce": nonce}, ensure_ascii=True)
    return value.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
