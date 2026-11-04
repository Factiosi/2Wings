<div align="center">

<img src="assets/icons/app.svg" width="120" alt="Tigo">

# Tigo

Окно управления zapret2 для Windows: стратегии Flowseal на winws2, их подбор, DNS и hosts.

[![Скачать последнюю версию](https://img.shields.io/badge/Скачать-последнюю%20версию-8b5cf6?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Factiosi/Tigo/releases/latest)

[![Релиз](https://img.shields.io/github/v/release/Factiosi/Tigo?label=релиз&color=8b5cf6)](https://github.com/Factiosi/Tigo/releases/latest)
[![Скачиваний](https://img.shields.io/github/downloads/Factiosi/Tigo/total?label=скачиваний&color=8b5cf6)](https://github.com/Factiosi/Tigo/releases)
[![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4?logo=windows&logoColor=white)](#требования)

</div>

## Что умеет

- **Обход на winws2.** Движок — `winws2.exe` из официального релиза [zapret2](https://github.com/bol-van/zapret2). Стратегии [Flowseal](https://github.com/Flowseal/zapret-discord-youtube) выходят под winws1, Tigo переводит их в winws2 сам при каждом запуске.
- **Подбор стратегий.** Прогоняет выбранные стратегии по очереди и показывает, какие открывают нужные сайты. Итог считается по HTTP и TLS 1.2, TLS 1.3 показан для справки. Результаты хранятся по версии Flowseal.
- **Автоисключения.** Сайт, который стратегия ломает (ошибка `ERR_SSL_PROTOCOL_ERROR`), Tigo сам вносит в исключения. Отключается в настройках.
- **Своя стратегия.** Аргументы winws1 или winws2 с подстановками `%LISTS%` и `%BIN%`.
- **Фоновая работа.** Обход держит фоновый процесс со значком в трее; окно можно закрыть.
- **Изменение DNS.** Comss DNS, Cloudflare, Google и Quad9 в один клик для всех адаптеров.
- **Редактор hosts.** Готовые наборы (Telegram в браузере, блокировка MAX и гос. СМИ) и сервисы через DNS-профили: нейросети, Spotify, Twitch, Notion, Discord, YouTube и другие. Адреса берутся у выбранного DNS в момент применения, неотвечающие не записываются.
- **TG WS Proxy.** Локальный прокси для Telegram.

Изменение DNS, редактор hosts и выбор источника стратегий появляются после галочки «Настройки для продвинутых пользователей» в **Настройках**.

## Требования

- Windows 10 или 11, x64
- Права администратора (запрос UAC при старте)

## Установка

1. Скачайте `Tigo-Setup-<версия>.exe` со страницы [последнего релиза](https://github.com/Factiosi/Tigo/releases/latest).
2. Установите программу и откройте Tigo из меню «Пуск».
3. Подтвердите запрос UAC.

При первом запуске Tigo скачает движок winws2 и стратегии Flowseal. На главном экране выберите стратегию и нажмите **Запуск**. Для подбора откройте **Подбор стратегий**, отметьте варианты и запустите тест.

## Обновления

Проверка обновлений Tigo включена по умолчанию; установка — вручную в **Настройках**. Стратегии Flowseal, движок winws2 и каталог сервисов hosts обновляются отдельно.

## Данные

Настройки, стратегии, списки, кэш и результаты тестов: `%APPDATA%\Tigo`.

## Разработка

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py --daemon   # отдельный терминал с правами администратора
.venv\Scripts\python run.py            # окно
```

Сборка и релиз: [`docs/BUILD.md`](docs/BUILD.md).

## Ограничения

Установщик не подписан кодом; при первом запуске Windows может показать предупреждение SmartScreen.
