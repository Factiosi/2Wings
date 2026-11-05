# Сборка 2Wings (Windows, Nuitka standalone)

## Требования

- Windows 10/11 x64
- Python 3.12 + venv
- Компилятор ставить не нужно: Nuitka сам скачает MinGW при первой сборке
- Node.js 20+ (для `tools/generate_icons.mjs`, если нет готовых `app.ico` / `tray-*.png`)

## Установка зависимостей

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-build.txt
.venv\Scripts\python -m pip install --no-deps -r requirements-ui.txt
```

## Ассеты (знаки, ico, трей)

Растры и `app.ico` собираются из SVG в `assets/icons/`:

```powershell
cd tools
npm install
node generate_icons.mjs
cd ..
```

## Сборка

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_nuitka.ps1
```

Скрипт пересоздаёт `dist\2Wings\` и после успешной сборки удаляет промежуточный `dist\run.build\`.

Результат: **вся папка** `dist\2Wings\` — `2Wings.exe`, `TwoWingsUpdate.exe`, `assets\icons\`, DLL и прочие зависимости Nuitka. Локальные `bin\` и `utils\` намеренно не копируются.

> **Важно:** распространяйте или копируйте **целиком папку** `dist\2Wings\`, а не один `2Wings.exe`. Без `flet_client\` и соседних DLL приложение не запустится.

`2Wings.exe` собран с UAC-манifest (запуск от администратора). Двойной клик: UAC → фоновый daemon (трей) → GUI.

## Installer (Inno Setup)

После standalone-сборки скомпилируйте [`tools/twowings_installer.iss`](../tools/twowings_installer.iss):

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" tools\twowings_installer.iss
```

Результат: `dist\installer\2Wings-Setup-X.Y.Z.exe`. Версия в `.iss` должна совпадать с `src\core\version.py`.

Installer устанавливает всю папку standalone в `{autopf}\2Wings`. При удалении он очищает установленный runtime и задачу `2Wings Autostart`, но сохраняет настройки и пользовательские данные в `%APPDATA%\2Wings`.

## Выпуск релиза

Проверка без изменений GitHub:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy_release.ps1 -Version 1.1.0 -DryRun
```

Публикация выполняется только из чистой ветки `master` после commit:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\deploy_release.ps1 -Version 1.2.2 -ReleaseNotes "Краткое описание релиза." -Publish
```

Скрипт запускает unit-тесты, пересобирает standalone, проверяет отсутствие MCP и стороннего runtime, создаёт installer и SHA-256, отправляет `master`, tag и GitHub Release.

`TwoWingsUpdate.exe` (окно прогресса самообновления) собирается **один раз** локально и не коммитится в git:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_update_splash.ps1
```

Артефакт сохраняется в `scripts/release_assets/TwoWingsUpdate.exe` (gitignored). `scripts/build_nuitka.ps1` копирует его в `dist\2Wings\` рядом с `2Wings.exe`; installer кладёт бинарник в `{Program Files}\2Wings\`. Исходники: `src/update_splash/`.

Релиз **1.3.1** однократно удаляет устаревшую копию `%APPDATA%\2Wings\TwoWingsUpdate.exe` при любом запуске (миграция только в этом релизе, не в последующих).

## Проверка

```powershell
dist\2Wings\2Wings.exe --daemon
dist\2Wings\2Wings.exe
dist\2Wings\2Wings.exe --debug-console
.venv\Scripts\python scripts\smoke_ipc_ping.py
```

Дополнительно проверьте: второй `--daemon` не создаёт новый экземпляр; start/stop и тестирование стратегий выполняются без консольных окон; debug console открывается из GUI.

## winws2 runtime

`bin\`, `lua\`, `utils\` и `engine-version.txt` **не входят** в git, standalone и installer. При первом запуске daemon независимо от настроек стратегий скачивает движок winws2 из официального релиза [zapret2](https://github.com/bol-van/zapret2/releases/latest) (`winws2.exe`, `WinDivert.dll`, `WinDivert64.sys`, `cygwin1.dll`, `zapret-lib.lua`, `zapret-antidpi.lua`) и сверяет архив с `sha256sum.txt`. Стратегии, листы и фейки по-прежнему приходят из релиза Flowseal. Перед распространением проверьте, что installer не содержит сторонний runtime.

## Архитектура

- **Daemon** (`2Wings.exe --daemon`) — tray, IPC, winws, обновления
- **GUI** (`2Wings.exe`) — только окно на Qt, управление через IPC; без daemon не стартует
