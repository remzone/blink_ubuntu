# Происхождение и лицензии

Клиент Ubuntu создан на основе локальных исходников:

- Android: `https://github.com/remzone/blink-android`, HEAD `b205d622c1247ba221d8c6b4f5d2883aef61d7d0`.
- iOS: `https://github.com/remzone/blink_ios`, HEAD `e198d6111e22cd36590ad026e2b1758d82e32495`.

`native/` скопирован из рабочего дерева Android без изменения Go-исходников. Сгенерированные AAR/JAR и каталоги сборки исключены. На момент переноса в рабочем дереве имелись незакоммиченные изменения, включая XDRIVE и обновления зависимостей; поэтому один HEAD не определяет этот снимок. Точный состав и SHA-256 всех vendored файлов закреплены в native-manifest.json. Проверка `python3 tools/verify-native.py` не требует доступа к соседним проектам или сети. В Ubuntu-репозитории сохранены native/go.mod, go.sum, тесты, синтетические fixtures, геоданные и исходные LICENSE/UPSTREAM.md.

Из iOS изучены VokopSubscription.swift, модели профилей, документация протоколов и поток подключения. Linux-адаптер, Go CLI, файловое хранилище, Tk GUI и упаковка реализованы для Ubuntu. Swift/Android UI и мобильные VPN API в Linux не запускаются. Соседние репозитории не изменялись.

Основная лицензия — GPL-3.0-only (LICENSE). Сохранены отдельные лицензии `native/share`, `native/vkturn`, `native/resources`. Go-зависимости используют собственные лицензии; их версии и контрольные суммы закреплены в go.mod/go.sum. Геоданные и исходный транспорт дополнительно описаны в `native/resources/UPSTREAM.md` и `native/vkturn/UPSTREAM.md`. Распространяя бинарники, сохраняйте уведомления и предоставляйте соответствующий исходный код этого репозитория в соответствии с GPL.

Графический знак Blink в packaging/blink.svg — простой векторный ресурс этой реализации; внешние изображения и шрифты не включены. GUI использует системный DejaVu Sans или системную замену.

## Web CAPTCHA SDK

`gui/vendor/vkid-captcha-2.0.0.js` — неизменённый UMD bundle официального npm-пакета `@vkid/captcha@2.0.0`, правообладатель V Kontakte LLC, лицензия MIT. Лицензия сохранена рядом в VKID-CAPTCHA-LICENSE.

Источник: https://registry.npmjs.org/@vkid/captcha/-/captcha-2.0.0.tgz

SHA-512 npm-архива проверен перед переносом: `4SRSVQOGYc5CXmduS5uCJhDuLgNgbYKqIflzE5BorDy8sOTkiSlGMKr7qTqjrm+x8km1RWzJEpLD6WKlnbTLEg==` (base64).

SHA-256 UMD bundle: `ca80b70bf136ef5b88dfd7be571f6c80dd8612753a8ae9b7bc8a8b035f0adc4c`. Дополнительная JS-зависимость mitt включена в опубликованный UMD SDK. Собственные captcha_shell.js и desktop bridge находятся под GPL-3.0-only.
