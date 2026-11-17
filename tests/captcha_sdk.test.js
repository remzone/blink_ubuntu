// Exercises the real pinned VK SDK's origin/source checks with a minimal DOM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const directory = path.join(__dirname, '..', 'gui');
async function test() {
  const listeners = [];
  const replies = [];
  const iframe = {contentWindow: {postMessage() {}}, set src(value) {this.uri = value;}, remove() {}};
  const root = {insertAdjacentHTML() {}, querySelector: () => iframe, style: {}, setAttribute() {}, hasAttribute: () => false, remove() {}};
  const document = {getElementById: () => root, body: {insertAdjacentHTML() {}}, addEventListener() {}, removeEventListener() {}};
  const window = {addEventListener(name, cb) {if (name === 'message') listeners.push(cb);}, removeEventListener() {}, crypto: require('node:crypto').webcrypto,
    webkit: {messageHandlers: {blinkCaptcha: {postMessage(value) {replies.push(JSON.parse(value));}}}}};
  const context = {window, document, location: {origin: 'https://blink.invalid'}, URL, URLSearchParams, setTimeout, clearTimeout, console, Uint8Array};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(directory, 'vendor/vkid-captcha-2.0.0.js'), 'utf8'), context);
  const config = {id: 'fixture', nonce: 'nonce', link: 'https://vk.com/captcha?sid=test'};
  vm.runInContext(fs.readFileSync(path.join(directory, 'captcha_shell.js'), 'utf8').replace('__BLINK_CONFIG__', JSON.stringify(config)), context);
  const data = {type: 'vk-sak-sdk', handler: 'VKCaptchaGetResult', params: {token: 'synthetic-success'}};
  for (const event of [{origin: 'https://evil.org', source: iframe.contentWindow, data}, {origin: 'https://vk.com', source: {}, data}, {origin: 'https://vk.com.evil.org', source: iframe.contentWindow, data}]) {
    for (const callback of listeners) callback(event);
  }
  await new Promise(setImmediate);
  assert.equal(replies.length, 0, 'forged origin or window must not complete the challenge');
  for (const callback of listeners) callback({origin: 'https://vk.com', source: iframe.contentWindow, data});
  await new Promise(setImmediate);
  assert.equal(replies.length, 1);
  assert.equal(replies[0].value, 'synthetic-success');
  assert.equal(replies[0].nonce, 'nonce');
  for (const callback of listeners) callback({origin: 'https://vk.com', source: iframe.contentWindow, data});
  await new Promise(setImmediate);
  assert.equal(replies.length, 1, 'callback must be single use');
  console.log('VK SDK: origin, iframe identity, success callback and single-use delivery OK');
}
test().catch(error => {console.error(error);process.exitCode = 1;});
