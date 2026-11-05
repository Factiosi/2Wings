---
name: twowings-structure
description: >-
  Куда класть файлы в 2Wings. Применять при создании папки, модуля, страницы,
  теста, скрипта, документа, ассета или знака. Второй схемы имён не заводить.
---

# Структура 2Wings

Общие правила — [reference.md](reference.md).

## 2Wings

- Код — только `src/`: `core/` (настройки, пути, процесс), `kernel/` (граница с ОС, winws), `modules/<способность>/`, `ui/` (`components/`, `pages/`, `features/`, `theme/`), `update_splash/`. Новый слой — только если код не входит ни в один.
- `modules` не импортирует `ui` (исключение — цвета журнала тестов из `src.ui.theme`). Kernel не знает о стратегиях: принимает готовый `WinwsLaunchSpec`.
- Новый модуль: `src/modules/<name>/__init__.py`, лог через `src.core.debug_log`; страница — `src/ui/pages/`, регистрация в `ui/app.py` (`build_nav_items`).
- Тесты — только корневой `tests/test_<тема>.py` (unittest).
- Ассеты — `assets/` (`brand/`, `icons/`, `hosts/`, `lua/`). Новая папка ассетов — в `scripts/build_nuitka.ps1` и в проверку `scripts/deploy_release.ps1`; если имя совпадает с каталогом в корне программы — проверить маски `tools/twowings_installer.iss` (`\lua\*` с якорем).
- Генераторы — `tools/`, команды разработчика — `scripts/`, объяснения — `docs/`. В корне свободных файлов нет.
- Пути рантайма — только через `src/core/paths.py`, не собирать строкой.
