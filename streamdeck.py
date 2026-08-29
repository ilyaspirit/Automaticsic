"""Яркость подсветки Stream Deck напрямую через HID.

Программа Elgato для этого не нужна и наружу ничего не отдаёт. Само
устройство — обычный HID: яркость ставится одним feature-отчётом, и всё
общение помещается в полсотни строк.

Ходим через ctypes к системным hid.dll и cfgmgr32.dll, а не через hidapi:
лишняя нативная библиотека — это ещё один файл, который PyInstaller должен
не забыть положить рядом, и ещё одно место, где сборка может тихо развалиться.
"""

import ctypes
import re
from ctypes import wintypes

hid = ctypes.windll.hid
cfgmgr32 = ctypes.windll.cfgmgr32
kernel32 = ctypes.windll.kernel32

VENDOR_ELGATO = 0x0FD9

# Первое поколение просит длинную посылку с сигнатурой 55 AA D1, второе —
# короткую. Разница историческая: Elgato сменила прошивку, а старые модели
# так и остались на прежнем протоколе.
GEN1 = "gen1"
GEN2 = "gen2"

MODELS = {
    0x0060: ("Stream Deck", GEN1),
    0x0063: ("Stream Deck Mini", GEN1),
    0x0090: ("Stream Deck Mini MK.2", GEN1),
    0x006C: ("Stream Deck XL", GEN2),
    0x006D: ("Stream Deck V2", GEN2),
    0x0080: ("Stream Deck MK.2", GEN2),
    0x0084: ("Stream Deck Plus", GEN2),
    0x008F: ("Stream Deck XL V2", GEN2),
    0x009A: ("Stream Deck Neo", GEN2),
    0x00A5: ("Stream Deck MK.2 Scissor", GEN2),
}

REPORTS = {
    # (идентификатор отчёта, длина, позиция байта яркости, начало посылки)
    GEN1: (0x05, 17, 5, (0x55, 0xAA, 0xD1, 0x01)),
    GEN2: (0x03, 32, 2, (0x08,)),
}

GENERIC_WRITE = 0x40000000
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value

PATH_IDS = re.compile(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", re.IGNORECASE)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _hid_paths():
    """Пути ко всем HID-устройствам в системе.

    CM_Get_Device_Interface_List отдаёт их одним списком. Через SetupAPI
    то же самое заняло бы втрое больше кода и три структуры.
    """
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))

    size = ctypes.c_ulong(0)
    if cfgmgr32.CM_Get_Device_Interface_List_SizeW(
        ctypes.byref(size), ctypes.byref(guid), None, 0
    ) != 0:
        return []

    buffer = ctypes.create_unicode_buffer(size.value)
    if cfgmgr32.CM_Get_Device_Interface_ListW(
        ctypes.byref(guid), None, buffer, size.value, 0
    ) != 0:
        return []

    return [path for path in buffer[:size.value].split("\0") if path]


def devices():
    """Подключённые Stream Deck: [{'path', 'pid', 'name', 'gen'}, ...].

    Опознаём по самому пути — в нём есть и производитель, и модель, так что
    открывать устройство ради этого не нужно.
    """
    found = []
    for path in _hid_paths():
        ids = PATH_IDS.search(path)
        if not ids:
            continue

        vendor, product = int(ids.group(1), 16), int(ids.group(2), 16)
        if vendor != VENDOR_ELGATO or product not in MODELS:
            continue

        name, generation = MODELS[product]
        found.append({"path": path, "pid": product, "name": name, "gen": generation})

    return found


def _report(generation, percent):
    report_id, length, position, head = REPORTS[generation]
    data = bytearray(length)
    data[0] = report_id
    data[1:1 + len(head)] = bytes(head)
    data[position] = percent
    return (ctypes.c_ubyte * length).from_buffer(data)


def _open(path):
    for access in (GENERIC_WRITE, GENERIC_READ | GENERIC_WRITE):
        handle = kernel32.CreateFileW(
            path, access, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, 0, None,
        )
        if handle and handle != INVALID_HANDLE:
            return handle
    return None


def set_brightness(device, percent):
    """Ставит яркость в процентах. True, если устройство приняло команду."""
    percent = max(0, min(100, int(percent)))

    handle = _open(device["path"])
    if handle is None:
        return False

    try:
        # Сначала формат своего поколения, потом — на всякий случай второй.
        # Таблица моделей собрана вручную, и новая железка может оказаться
        # не в той половине; лишняя попытка дешевле неработающего шага.
        order = [device["gen"]] + [g for g in (GEN1, GEN2) if g != device["gen"]]
        for generation in order:
            report = _report(generation, percent)
            if hid.HidD_SetFeature(handle, ctypes.byref(report), len(report)):
                return True
        return False
    finally:
        kernel32.CloseHandle(handle)


def describe():
    """Что нашли — одной строкой для подписи в редакторе."""
    names = []
    for device in devices():
        if device["name"] not in names:
            names.append(device["name"])
    return ", ".join(names)
