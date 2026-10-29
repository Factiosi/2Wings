---
name: tigo-winws2
description: >-
  Движок winws2 (zapret2), конвертер стратегий Flowseal winws1 → winws2, Lua,
  автоисключение по ошибке TLS, установка движка. Применять при правке
  src/modules/strategies, src/kernel, assets/lua, modules/tls_exclude,
  modules/updates/engine.py, своей стратегии и при ошибках запуска winws2.
---

# winws2 в Tigo

Сначала прочитай в `AGENTS.md` разделы «Поток запуска winws», «winws2 и конвертер стратегий», «Автоисключение по ошибке TLS» и пункт 7 «Ключевых решений».

## Опоры

- Перевод — `src/modules/strategies/winws2.py` (`to_winws2_argv`, `ConversionError`, `inject_tls_watch`), сборка запуска — `launcher.py` (`build_winws_launch`, `resolve_custom_args`). Конвертер сохраняет семантику nfqws1 — сверяться с исходниками nfqws1, не со стилем PR Flowseal#18202. Опция без точного аналога — `ConversionError`, а не молчаливая потеря.
- Справка по ключам — исходники и документация релиза `bol-van/zapret2`; Lua-функции — `{program_root}/lua/zapret-*.lua`.
- winws2 срезает `\` в тексте `--lua-init`: пути туда — с прямыми слешами. Хостлисты и ipset winws2 перечитывает сам при изменении файла.
- Движок ставится из релиза zapret2 со сверкой `digest` ассета GitHub и `sha256sum.txt` по файлам архива. Из Flowseal берутся только стратегии, листы, фейки и `utils`.
- В подборе стратегий `tls_watch=False`: тест не должен править листы.
- Исключение программ по `.exe` не возвращать (раздел «Осознанные странности»).

## Проверка

- `tests/test_winws2.py`, `test_engine.py`, `test_tls_exclude.py`, `test_custom_args.py`.
- Разбор аргументов вживую — `bin\winws2.exe --dry-run <аргументы>` (ждём «command line parameters verified»). Запуск winws2 из оболочки агента среда блокирует: дать пользователю готовую команду или скрипт и попросить вывод.
- Перед запуском движка — `_engine_preflight()`; каких файлов нет — `paths.missing_engine_files()`.
