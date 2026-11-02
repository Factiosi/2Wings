---
name: tigo-release
description: >-
  Собрать и выпустить релиз Tigo: коммит «Релиз X.Y.Z», сборка Nuitka и
  инсталлятора, тег, GitHub Release, затем следующий -dev. Запускать по просьбе
  выпустить релиз или собрать сборку.
disable-model-invocation: true
argument-hint: "X.Y.Z"
---

# Выпуск Tigo $ARGUMENTS

Тексты — по скилу `tigo-log`. Сборка подробно — `docs/BUILD.md`. Шаги, которые меняют GitHub (пуш, тег, релиз), — только с явного согласия пользователя в чате; пуши пользователь часто делает сам.

## Шаги

1. **Проверка.** Ветка `experimental`, дерево чистое (`.claude/settings.local.json` и черновики пользователя не трогать). Тесты: `.venv\Scripts\python -m unittest discover -s tests`. Сверить `README.md` и `AGENTS.md` с коммитами пачки (`git log master..experimental`): новое поведение должно быть описано до коммита выпуска.
2. **Коммит выпуска** на `experimental`: номер `X.Y.Z` без `-dev` в `src/core/version.py` и в `#define MyAppVersion` в `tools/tigo_installer.iss`. Строка — «Релиз X.Y.Z».
3. **master:** `git checkout master`, `git merge --ff-only experimental`. Коммита слияния нет.
4. **Сборка:** `powershell -File scripts\deploy_release.ps1 -Version X.Y.Z -DryRun` (без `-ExecutionPolicy Bypass` — среда его блокирует). Скрипт требует ветку `master`, гоняет Nuitka, Inno Setup и тесты, кладёт `dist\installer\Tigo-Setup-X.Y.Z.exe` и `.sha256`. Запущенный `dist\Tigo\Tigo.exe` закрыть заранее.
5. **Публикация** (после согласия): пуш `master` и `experimental`; аннотированный тег `vX.Y.Z` с сообщением «Tigo X.Y.Z» и заметкой; пуш тега; затем
   `gh release create vX.Y.Z dist\installer\Tigo-Setup-X.Y.Z.exe dist\installer\Tigo-Setup-X.Y.Z.exe.sha256 --repo Factiosi/Tigo --title "Tigo X.Y.Z" --notes-file <файл UTF-8 без BOM> --verify-tag`.
   Режим `-Publish` скрипта вслепую не запускать: он ещё и меняет видимость репозитория.
6. **Следующий тест:** `git checkout experimental`, коммит «Отметить версию разработки X.Y.Z-dev» — когда пользователь назовёт номер.

## Заметка релиза

```
## X.Y.Z — YYYY-MM-DD

- Что стало, языком пользователя: что он увидит и где.
```

Сначала `Breaking: …`, если прежнее ломается. Один пункт — один смысл. Без авторов, благодарностей и пересказа коммитов. Образец — `git tag -n20 v1.5.7`.
