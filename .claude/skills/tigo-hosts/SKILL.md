---
name: tigo-hosts
description: >-
  Редактор hosts Tigo, каталог сервисов zapretgui, живые ответы DNS-профилей
  (Zapret DNS, Comss, XBOX), страница DNS. Применять при правке
  src/modules/hosts, src/modules/dns, страниц hosts и DNS, и когда у
  пользователя сервис (Gemini, ChatGPT…) не открывается через hosts или DNS.
---

# hosts и DNS в Tigo

Сначала прочитай раздел «Редактор hosts» в `AGENTS.md` и `docs/ZAPRET-DNS.md`.

## Правила кода

- В hosts — только свои блоки `# >>> tigo:<id> >>>`; чужие строки не трогать. Копия `hosts.tigo.bak` перед первой записью.
- Один профиль на все сервисы, без подмены другим профилем. Профили с DoH (`PROFILE_DOH` в `hosts/live.py`) спрашиваются вживую; прокси — адрес вне сетей ответа Google DNS, общий для двух и более имён или известный по каталогу. Каждый адрес перед записью проверяется подключением к 443.
- SQLite — только `closing(sqlite3.connect(...))`.
- DNS на странице: Zapret DNS, Comss, Cloudflare, Google — без согласия не расширять.

## Разбор жалобы «сервис не открывается»

Идти от сети к браузеру, проверяя, а не угадывая:

1. Что в hosts — строки `C:\Windows\System32\drivers\etc\hosts` без комментариев.
2. Системный DNS — `Get-DnsClientServerAddress`; ответ профиля и Google — `_resolve` из `hosts/live.py`.
3. Жив ли прокси — `curl --resolve host:443:<ip> https://host/` (файлы — в scratchpad, не в `/tmp`).
4. Встроенный браузер панели (`mcp__Claude_Browser__*`) берёт системный DNS — быстрый ответ, работает ли путь на этом ПК.
5. Путь работает, а браузер пользователя нет: сравнить с InPrivate (кэш, сокеты, куки профиля — `edge://restart`, данные сайта), расширения с правом `proxy`, «Безопасный DNS» (`dns_over_https` в `Local State`), Throne и системный прокси (`ProxyEnable`).
6. Анонимно работает, в аккаунте нет — страна аккаунта Google (`policies.google.com/terms`); hosts и Tigo тут не помогут.

Данные браузера пользователя сам не чистить — дать шаги.
