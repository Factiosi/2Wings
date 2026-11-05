# AGENTS.md — 2Wings

Документ для AI-агентов: быстрый вход в проект, архитектура и осознанные решения.

Закон имён папок — в соседнем репозитории Factiosi, `docs/STRUCTURE.md`. Здесь второй схемы нет.

Коммиты, ветки и релизы — по `docs/LOG.md` Factiosi, с одним отличием: **все тексты 2Wings только на русском** — строки коммитов («Добавить…», «Релиз 1.5.5»), заметки релизов, описание репозитория. Английский из `LOG.md` к 2Wings не относится.

Скилы агента — `.claude/skills/`: `twowings-log` (коммиты и версии), `twowings-release` (выпуск, `/twowings-release X.Y.Z`), `twowings-structure`, `twowings-ui` (Fluent на Qt), `twowings-winws2`, `twowings-hosts`, `twowings-test`. Скилы ссылаются на этот файл и на Factiosi, а не повторяют их.

## Что это

**2Wings** (в коде `twowings`, до версии 2.0.0 называлась Tigo) — десктоп GUI на PySide6 и QFluentWidgets для управления zapret/winws на Windows. Пользователь выбирает стратегию flowseal, запускает/останавливает winws без видимых консолей, тестирует стратегии, обновляет runtime с GitHub.

> Имя приложения — **2Wings**. 

## Корень

| Имя | Что это |
|-----|---------|
| `run.py` | Вход: окно, `--daemon`, `--debug-console` |
| `requirements.txt` | Зависимости запуска |
| `requirements-build.txt` | Nuitka |
| `src/` | Весь код |
| `assets/icons/` | Иконки окна, трея и окна обновления (собираются из `assets/brand/sources/`) |
| `assets/brand/sources/` | Белый мастер знака `twowings-simple.svg` |
| `tools/` | Генератор иконок и инсталлятор |
| `scripts/` | Сборка, сплэш обновления, релиз, smoke |
| `docs/` | Сборка и локальные заметки |
| `tests/` | Тесты |

## Точки входа

```
run.py --daemon
  → ensure_layout(), bootstrap_user_lists()
  → kernel.public.initialize_runtime()
  → kernel.process_monitor.start_monitor()
  → run_startup_updates()
  → tray + IPC (winws живёт здесь)

run.py (GUI)
  → ensure_admin() (UAC)
  → require_daemon_for_gui()  # без daemon GUI не стартует
  → ft.run(ui/app.py:main)    # только IPC к daemon
```

**Сборка release:** [`docs/BUILD.md`](docs/BUILD.md) (Nuitka standalone, Windows).
**Локальная автоматизация:** [`docs/AUTOMATION.md`](docs/AUTOMATION.md) (MCP stdio, dev/test only).

## Архитектура

```
src/
├── core/           # инфраструктура: paths, settings, admin, debug_log, events
├── kernel/         # ядро: запуск/остановка winws, мониторинг, runtime state
├── modules/        # функциональные модули
│   ├── strategies/       # парсинг .bat, репозиторий, launcher
│   ├── strategy_testing/ # daemon-раннер тестов, probe, cache результатов
│   ├── updates/          # GitHub releases, transformer
│   ├── filters/          # game filter, ipset, tcp timestamps
│   └── hosts/            # hosts Windows: сервисы по каталогу, готовые наборы, резервная копия
├── update_splash/  # отдельный процесс окна обновления
└── ui/
    ├── components/ # контролы без знания экрана
    ├── pages/      # экраны основного окна
    └── features/   # debug console
```

### Слои и границы

| Слой | Ответственность | Не знает о |
|------|-----------------|------------|
| **kernel** | `WinwsLaunchSpec` → start/stop winws, PID monitor | стратегиях, UI, тестах |
| **modules/strategies** | `.bat` → args, репозиторий, `build_winws_launch()` | UI |
| **modules/strategy_testing** | daemon: start→probe→stop; cache результатов по версии | UI |
| **core/debug_log** | always-on журнал, TTL 1 час | UI (только pub/sub) |
| **ui** | страницы, snackbar, debug console window | бизнес-логике |

### Поток запуска winws

```
GUI → daemon IPC → strategies.launcher.build_winws_launch(strategy)
                → .txt (аргументы winws1) → плейсхолдеры → strategies.winws2.to_winws2_argv → WinwsLaunchSpec
                → kernel.public.start(spec) → winws_runner → bin/winws2.exe (CREATE_NO_WINDOW)
```

Kernel **не** парсит стратегии — только принимает готовый `WinwsLaunchSpec`.

### winws2 и конвертер стратегий

Движок — `winws2.exe` из официального релиза zapret2 (`bol-van/zapret2`). Flowseal по-прежнему выпускает стратегии под winws1, поэтому в `%APPDATA%` хранятся аргументы winws1, а перевод в winws2 делается **при каждом запуске** в `modules/strategies/winws2.py` (обновление конвертера не требует перекачивать Flowseal).

- Перевод сохраняет семантику nfqws1, а не стиль PR Flowseal#18202: каждый фейк — отдельный `fake`-инстанс в группе своего `--payload` (tls/http/quic/discord/stun…), неявные умолчания nfqws1 прописаны явно (`fake_default_tls` с `rnd,rndsni,dupsid`, нулевые фейки 64/256 байт), `--dpi-desync-any-protocol` → группа «всё, что nfqws1 считал unknown» (`--payload=all` + Lua-фильтр `~…,empty`), `--dpi-desync-cutoff=nN` → `--out-range=<nN`, `multidisorder` → `multidisorder_legacy`.
- Fooling (`tcp_ts`, `tcp_seq`/`tcp_ack`/`tcp_ts_up` для badseq, `tcp_md5`) и `repeats` идут только в инстансы, шлющие фейки: в winws2 fooling у `multisplit`/`multidisorder` портил бы настоящие сегменты.
- Фейки подключаются через `--blob=fs_<имя файла>:@<путь>`, `blobs.lua` не нужен.
- Опции без точного аналога в winws2 → `ConversionError`, стратегия не запускается. Единственное, что теряется молча с предупреждением в лог, — `altorder` у `hostfakesplit`/`fakedsplit` (в winws2 его нет).
- «Своя стратегия»: аргументы winws1 конвертируются, аргументы winws2 (`--lua-desync`, `--payload`…) передаются как есть, библиотека Lua подключается автоматически.

**Daemon vs GUI:** winws, tray, IPC и bootstrap (обновления, монитор) живут только в `run.py --daemon`. GUI без daemon не запускается; управление zapret — только через IPC.

## Пути данных

| Что | Где |
|-----|-----|
| winws2, WinDivert, cygwin | `{program_root}/bin` (версия zapret2 — `{program_root}/engine-version.txt`) |
| Lua-библиотека zapret2 | `{program_root}/lua` (`zapret-lib.lua`, `zapret-antidpi.lua`) |
| utils Flowseal | `{program_root}/utils` |
| иконки | `{program_root}/assets/icons` |
| flowseal strategies | `%APPDATA%\2Wings\strategies\flowseal\{version}\*.txt` |
| versioned lists | `%APPDATA%\2Wings\strategies\flowseal\{version}\lists\` |
| user lists | `%APPDATA%\2Wings\strategies\flowseal\user_lists\` |
| fake bins | `%APPDATA%\2Wings\strategies\flowseal\bin\` |
| settings | `%APPDATA%\2Wings\settings.json` |
| результаты тестов | `%APPDATA%\2Wings\cache\test_results.json` |

## Ключевые решения

1. **Модульность** — core + kernel + modules + ui. Новый функционал = новый модуль в `modules/`, логирование через `core.debug_log`.
2. **Результаты тестов сохраняются по версии Flowseal** — daemon пишет `%APPDATA%\2Wings\cache\test_results.json`, GUI перечитывает cache через IPC polling. Журнал текущего запуска остаётся in-memory.
3. **Debug console** — отдельный процесс (`run.py --debug-console`), вход в `src/ui/features/debug_console/app.py`, лог через `%APPDATA%\2Wings\debug.log`, TTL 1 час.
4. **Home page без inline-консоли** — статус через бейдж + тост; детали в debug console.
5. **winws принадлежит только daemon** — GUI не запускает и не завершает процесс напрямую, включая тестирование стратегий.
6. **Automation ограничена** — source daemon разрешает MCP-команды; compiled daemon требует `TWOWINGS_AUTOMATION=1`.
7. **Движок обязателен и независим от стратегий** — при отсутствии файлов winws2 daemon скачивает официальный релиз zapret2 (проверка по `sha256sum.txt`) независимо от `strategy_source` и настроек автообновления; при `auto_promote_updates` и остановленном winws2 обновляет его на старте. Из архива Flowseal берутся только стратегии, листы, фейки `.bin` и `utils` — его `winws.exe` и `WinDivert.dll` не ставятся (у zapret2 свой пропатченный DLL). Оставшийся от старых версий `bin/winws.exe` считается своим: его гасит stop и удаляет установка движка.
8. **Самообновление 2Wings** — проверка GitHub Releases (`2Wings-Setup-X.Y.Z.exe` + `.sha256`); автопроверка включена, автоустановка выключена.
9. **Массовые тесты** — daemon владеет probe snapshot; GUI раскрывает только текущую стратегию, пауза 2 с, затем все завершённые.

## Осознанные «странности»

- **`kernel/service_api.py`** — legacy Win32 SCM API, используется только в `migrate.py` для удаления старого сервиса `zapret`. Deprecated для обычного запуска.
- **DPI-тест** — backend пока не реализован; radio в UI отключён.
- **winws2 stdout → DEVNULL** — пользователь не видит консоль winws2; stderr читается только при immediate exit.
- **Исключения программ по `.exe` нет — и это осознанно.** Пробовали: монитор WinDivert SOCKET (PID → локальный порт) + Lua-фильтр первым в профиле winws2. На сетевом уровне WinDivert PID недоступен, события SOCKET/FLOW приходят асинхронно, а `connect()` драйвер не придерживает (без sniff сразу `FWP_ACTION_BLOCK`). Итог — гонка: первые пакеты (QUIC Initial, часть ClientHello) успевают в обработку. Без гонки и без задержки это делает только свой подписанный WFP-драйвер. Не возвращаться без нового механизма.

## Как добавить модуль

1. Создать `src/modules/<name>/` с `__init__.py`.
2. Логировать действия через `from src.core.debug_log import debug, info, warn, error`.
3. Опционально: pub/sub через `src.core.events`.
4. UI-страницу — в `src/ui/pages/`, регистрация в `ui/app.py`.
5. **Не** импортировать ui из modules. Журнал тестов — исключение: цвета строк берутся из `src.ui.theme`.

## Запуск

```bash
python run.py
```

## Автоисключение по ошибке TLS

Настройка `tls_auto_exclude` (по умолчанию включена). Если сервер отвечает на изменённый обходом ClientHello открытым фатальным TLS alert (`15 03 xx 00 02 02`) или простым `HTTP/1.x 400` (так делает Tengine у aliexpress.ru: фейк доходит до сервера, тот читает мусор как HTTP) — в браузере это ERR_SSL_PROTOCOL_ERROR, — домен уходит в `list-exclude-user.txt`, а для профилей без `--hostlist-exclude` (игровой фильтр, ipset) — адрес в `ipset-exclude-user.txt`.

- `inject_tls_watch` (`strategies/winws2.py`): `--wf-raw-part` перехватывает только такие входящие пакеты; `twowings_tls_watch` (`assets/lua/twowings-tls-watch.lua`) первым в каждом профиле с `--in-range=a`/`--out-range=x`, затем диапазоны сбрасываются. Отчёт — строка в `tls-alerts.txt` в каталоге `--writable` (`%APPDATA%\2Wings\cache\winws2`).
- `modules/tls_exclude/watcher.py` в daemon раз в 2 с забирает файл (rename) и дописывает листы под пометкой `# 2Wings: …`; winws2 перечитывает листы сам.
- По RST, ретрансмиссиям и молчанию не исключаем: так выглядит и блокировка DPI. Зашифрованный alert (обычное закрытие TLS 1.2) фильтр не пропускает.
- В тестировании стратегий детектор выключен (`tls_watch=False`): тестируемая стратегия не должна править листы.

## Редактор hosts

- 2Wings пишет в hosts только свои блоки `# >>> twowings:<id> >>>` … `# <<< twowings:<id> <<<`; чужие строки не трогает. Перед первой записью снимает копию `hosts.twowings.bak` рядом с файлом.
- Сервисы — из каталога zapretgui (`hosts_catalog.sqlite3`, схема 1): у DNS-сервисов адреса по профилям (XBOX DNS, Comss DNS…), у «прямых» — готовые записи. Снимок лежит в `assets/hosts/`, свежий — в `%APPDATA%\2Wings\cache\`; `catalog_update.py` берёт его из `update-manifest.json` последнего выпуска zapretgui и хранилища `<sha256>.zst` со сверкой суммы. Daemon проверяет раз в 6 часов на старте и переписывает выбранные сервисы.
- Выбор хранится в `settings.hosts_services` (сервис → профиль). Один профиль на все сервисы, **без подмены другим профилем**: так однажды для Gemini записался мёртвый прокси чужого профиля из снимка.
- Zapret DNS в 2Wings нет и не возвращать: с ноября 2026 он отвечает только по DoH через Cloudflare, без постоянного адреса, а обычный DNS закрыт. В каталоге zapretgui профиль остаётся, `catalog.HIDDEN_PROFILES` его скрывает. `settings.load` переводит выбор на Comss, `modules/dns/cleanup.py` при старте daemon снимает прежние адреса с адаптеров и переписывает hosts.
- Профили с DoH (Comss, XBOX — `hosts/live.py`) спрашиваются вживую при «Применить» и при плановой проверке daemon. Прокси — ответ из сети (/16, /48), которой нет в ответе Google DNS, и при этом адрес общий для ≥2 имён или известный прокси профиля по каталогу; иначе домен остаётся обычному DNS. Остальные профили — из снимка.
- Любой адрес перед записью проверяется подключением к 443; неотвечающий не пишется. Локальные адреса отбрасываются, IPv6 — только при маршруте в IPv6.
- SQLite открывать только через `closing(...)`: `with sqlite3.connect()` соединение не закрывает, и каталог потом не заменить.

## Что не трогать без запроса

- DNS — `modules/dns/`, UI-страница `ui/pages/dns.py`.
- Режим «Своя стратегия» — `settings.strategy_source == "custom"`, скрывает тестирование стратегий и редактирование листов. Аргументы проходят те же подстановки, что стратегии Flowseal (`%LISTS%list-general-user.txt`, `%BIN%`, `%GameFilterTCP%`), абсолютные пути остаются как есть.
- «Настройки для продвинутых пользователей» — `settings.advanced_mode`. Без неё нет пунктов «Изменение DNS» и «Редактирование hosts» и выбора источника стратегий (всегда Flowseal). У новой установки выключена; `settings.json` без этого ключа — от прежней версии — читается как включённая.
- Переименование 2Wings / папки репозитория.

## Интерфейс: Fluent Design

Продукт живёт в стиле своей платформы, общего стиля с Factiosi нет: Umbrae и особые шрифты убраны и не возвращаются.

- Основа — [QFluentWidgets](https://qfluentwidgets.com) поверх PySide6. Это GPLv3, поэтому и 2Wings распространяется под GPLv3 (`LICENSE`). Это копия WinUI на Qt, а не настоящий WinUI: тот есть только в C# и C++.
- Ставится `PySide6-Essentials` и пакет библиотеки с `--no-deps` (`requirements-ui.txt`): обычная установка тянет весь PySide6 с WebEngine, а это около 100 МБ в установщике. `build_nuitka.ps1` такую сборку не пропускает.
- Сборка идёт через MinGW (`--mingw64`), компилятор Nuitka скачивает сам. Visual Studio не нужна.
- Окно рисуется через Direct3D с вертикальной синхронизацией (`components.use_vsync_rendering`): программная отрисовка даёт разрывы при прокрутке. Чтобы при этом работала Mica, окну нужна поверхность с альфа-каналом, иначе прозрачная часть становится чёрной; библиотека создаёт окно без неё, поэтому `MainWindow._recreate_with_alpha` пересоздаёт его. Анимации запускаются через `components.play_at_display_rate`: у Qt таймер фиксирован на 60 кадрах, на мониторе 144 Гц это заметно. Переход между страницами библиотеки остаётся на 60. У прокрутки своё короткое скольжение (`Page._on_wheel`): анимация полосы библиотеки отключена, она давала «желе» и прыжки при изменении высоты.
- Иконки — только Lucide: `components.Lucide("имя")`, файлы в `assets/icons/lucide/` из `lucide-static` (ISC, лицензия рядом). Меню трея — те же значки, PNG делает `tools/generate_icons.mjs`.
- Шрифт, тема и акцент — системные: `components.apply_theme`. Цвета статусов — только `COLOR_*` из `ui/components`. Свои цвета, шрифты и радиусы не заводить.
- Страница — наследник `components.Page`. Настройка — `OptionCard`/`switch_card`/`select_card` внутри `Group`, как в параметрах Windows; свободное содержимое — `Panel`.
- Страница строится при входе и уничтожается при уходе (`app._Host`), поэтому таймеры и подписки снимает её `stop()`.
- Из фонового потока к виджетам не обращаться: только `dispatch.ui_call` и `dispatch.run_bg`. Запросы к daemon — вне потока окна: сокет может подвиснуть на секунды.
- Окно обновления (`update_splash`) — чистый Win32 и GDI+ без Qt: оно живёт отдельной маленькой программой.

## Переход с Tigo

Версии до 1.5.8 назывались Tigo. Установка заменяет их на месте: `AppId` прежний.

- Папка `%APPDATA%\Tigo` копируется в `%APPDATA%\2Wings` самым первым действием (`paths.migrate_legacy_app_data`), старая остаётся.
- Блоки `# >>> tigo:…` в hosts читаются как свои и переписываются при следующей записи, копия `hosts.tigo.bak` остаётся исходной.
- Задача автозапуска `Tigo Autostart` заменяется новой (`lifecycle.sync_autostart_task`, она же при каждом старте держит задачу на текущем exe).
- Установщик принимает прежние ключи `/TIGOPROGRESS` и `/TIGORELAUNCH`, гасит `Tigo.exe` и удаляет `flet_client`.
- Обновлятор 1.5.8 ищет в последнем релизе файл `Tigo-Setup-X.Y.Z.exe`, поэтому установщик и его `.sha256` прикладываются ещё и под старым именем (`deploy_release.ps1`), в каждом релизе. Иначе старые версии навсегда останутся «актуальными».
- Новый обновлятор приходит внутри установщика. Старый отрабатывает последний раз: качает установщик, тот кладёт `updater\TwoWingsUpdate.exe`, а 2Wings при следующем обновлении копирует его в `%LOCALAPPDATA%\2Wings\updater\<ревизия>`. Изменил `src/update_splash` — подними `UPDATER_REVISION` и пересобери `build_update_splash.ps1`, иначе останется прежняя копия.
- Установщик гасит `Tigo.exe` без `/T`: старый обновлятор и сам установщик — его дочерние процессы. Перед новым релизом сначала переименовывается репозиторий: старые версии идут за перенаправлением GitHub, а новые сразу обращаются к новому адресу.
