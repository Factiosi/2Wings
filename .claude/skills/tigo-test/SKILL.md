---
name: tigo-test
description: >-
  Прогон тестов Tigo и смысл проверок подбора стратегий (HTTP, TLS1.2,
  TLS1.3, UNSUP, пинг, вердикт «Полностью работает»). Применять перед
  коммитом, после правки кода и при вопросах о результатах теста стратегий.
---

# Тесты Tigo

## Прогон

- Все: `.venv\Scripts\python -m unittest discover -s tests` — так же их гоняет `deploy_release.ps1`. Системный Python без пакета `mcp` падает на `tests/test_mcp_server.py`; это не регрессия, бери `.venv`.
- Одна тема: `.venv\Scripts\python -m unittest tests.test_winws2 -v`.
- Новое поведение — новый тест в `tests/test_<тема>.py` рядом с соседями; сеть и процессы — через `unittest.mock.patch`, не вживую.
- Smoke daemon — `scripts/smoke_ipc_ping.py`; MCP-автоматизация — `docs/AUTOMATION.md`.

## Подбор стратегий

- Проба — `src/modules/strategy_testing/probe.py`: на каждый адрес `curl.exe` с `--http1.1`, `--tlsv1.2`, `--tlsv1.3`, плюс пинг DNS-серверов. DPI-тест — `dpi_probe.py`.
- Вердикт — `score_results` в `probe.py` и `_score_to_status` в `runner.py`: все засчитанные ячейки OK — «Полностью работает», от половины — «Частично».
- **TLS 1.3 показывается, но не засчитывается** (`UNSCORED_LABELS`). Системный `curl.exe` работает через Schannel, а curl включает TLS 1.3 на Schannel только с Windows 11 / Server 2022 (сборка 20348+). На Windows 10 там всегда UNSUP, ключ реестра этого не меняет; браузеры используют свои TLS-библиотеки.
- Код curl 35 сейчас тоже даёт UNSUP — так маскируется обрыв рукопожатия DPI. Чинить вместе с переходом проверки TLS 1.3 на Python, если пользователь попросит.
