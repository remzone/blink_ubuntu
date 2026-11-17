// SPDX-License-Identifier: GPL-3.0-only
// Executed with the pinned SDK only in WebKit's named, top-frame script world.
(function () {
  "use strict";
  const config = __BLINK_CONFIG__;
  let settled = false;
  const reply = (status, value) => {
    if (settled) return;
    if (status === "success" && (typeof value !== "string" || !value.length || value.length > 16384 || /[\r\n\0]/.test(value))) {
      status = "error";
      value = "";
    }
    settled = true;
    window.webkit.messageHandlers.blinkCaptcha.postMessage(JSON.stringify({
      nonce: config.nonce, id: config.id, status: status,
      kind: "token", value: status === "success" ? value : ""
    }));
  };
  try {
    const widget = new VKIDCaptchaSDK.CaptchaWidget();
    widget.show({
      container: document.getElementById("captcha"), link: config.link,
      captchaType: 1, view: "block", scheme: "dark", lang: "ru",
      onClose: () => reply("cancelled", "")
    }).then(token => reply("success", token)).catch(() => reply("error", ""));
    // The SDK checks both event.origin and iframe.contentWindow. Only its
    // successful promise reaches this private native bridge.
  } catch (_) {
    reply("error", "");
  }
}());
