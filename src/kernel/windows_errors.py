"""Human-readable diagnostics for common Windows/WinDivert launch failures."""

from __future__ import annotations

_HINTS = {
    2: "Не найден обязательный файл runtime.",
    5: "Windows отказала в доступе. Запустите 2Wings от администратора.",
    32: "Файл runtime занят другим процессом.",
    87: "winws2 получил некорректный параметр стратегии.",
    193: "Файл winws2.exe повреждён или собран для другой архитектуры.",
    577: "Windows заблокировала драйвер или неподписанный исполняемый файл.",
    1058: "Необходимая системная служба отключена.",
    1060: "Служба WinDivert отсутствует; переустановите движок winws2.",
}


def describe_windows_error(code: int | None) -> str:
    if code is None:
        return ""
    normalized = int(code) & 0xFFFFFFFF
    return _HINTS.get(normalized, _HINTS.get(normalized & 0xFF, ""))
