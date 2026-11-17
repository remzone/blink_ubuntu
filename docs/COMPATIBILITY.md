# Совместимость

Целевая нижняя версия: **Ubuntu 20.04 LTS** (Python 3.8, Tk 8.6, systemd 245, iproute2 5.5, Linux 5.4). Нет зависимости от GTK4, Electron, Snap, Wayland-only API или новой glibc. Встроенная CAPTCHA использует GTK3/WebKit2 4.0 либо 4.1. CLI собирается с CGO_ENABLED=0 и GOAMD64=v1, GUI использует системные Python/Tk. X11 и XWayland поддерживаются Tk системного дистрибутива; нативный Wayland не требуется.

Go 1.27.3 нужен сборщику, а не пользователю. Минимальная версия ядра для современных Go — [Linux 3.2](https://go.dev/wiki/MinimumRequirements), ниже ядра Ubuntu 20.04. Описание [TUN/TAP](https://docs.kernel.org/networking/tuntap.html) определяет используемый публичный Linux API. Фактические контейнерные и сетевые проверки приведены отдельно в VALIDATION.md; контейнеры используют ядро хоста и не заменяют тест на физическом Ubuntu 20.04 с ядром 5.4.

| Формат / протокол | Поддержка | Граница |
| --- | --- | --- |
| VLESS / VMess AEAD / Trojan | общее Xray-ядро | VMess alterId > 0 и удалённый Trojan flow отвергаются |
| Shadowsocks / SS2022 | SIP002, legacy, JSON | внешние plugins не добавлены |
| TCP/raw, WS, gRPC, HTTPUpgrade, XHTTP, KCP | URI и Xray JSON | допустимые сочетания определяет закреплённое ядро |
| REALITY / TLS / Vision | URI и JSON | нужны корректные серверные параметры |
| XDRIVE / MASQUE | Xray JSON | универсальный URI не придумывается |
| Hysteria2 | URI и JSON | произвольные параметры сторонних клиентов не гарантированы |
| Hysteria v1 / TUIC v5 | URI, узлы YAML | selective routing для этих standalone backend не добавлено |
| WireGuard / AmneziaWG | URI, .conf, AWG vpn://, YAML | адреса, DNS и маршруты следуют конфигурации |
| Clash/Mihomo | импорт поддерживаемых узлов | группы, правила и DNS документа не эмулируются |
| Vokop v1/v2/v3 | VK-профили и vpn_profiles | scoped HTTPS URL, сроки и ревизии; v3 требует selected routing |
| VK manual CAPTCHA | встроенный официальный Web SDK + изображение с кодом | ручная проверка в окне GTK/WebKit, без копирования token |
| MTProto | не системный VPN | используйте Telegram |
| OpenVPN / Cisco / Forti | нет | импорт не означает поддержку |

Работа зависит от поддержки TUN и policy routing ядром, включённого resolved и Polkit-агента в графической сессии. Минимальные контейнеры/WSL без resolved или Polkit не являются полноценной desktop VPN-средой. На Ubuntu Server доступны CLI и подключение через sudo; установка GUI необязательна при использовании отдельного бинарника.

Одинаковый parser и общие тесты уменьшают расхождения с мобильными клиентами, но не доказывают работу каждого стороннего сервера. Подписки, реальные VPN-ключи и пользовательский трафик для этой реализации не использовались.
