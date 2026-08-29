import ctypes
from ctypes import wintypes
import re
import time
import os
import sys
import winreg

import win32api
import win32con
import win32gui
import win32process

import subprocess

user32 = ctypes.windll.user32

# Этих двух функций в win32gui нет: IsIconic обёрнут, а IsZoomed и IsWindow —
# нет. Берём их прямо у user32, благо они простые.
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL


def is_maximized(hwnd):
    """Развёрнуто ли окно на весь экран."""
    return bool(user32.IsZoomed(hwnd))


def window_exists(hwnd):
    """Живо ли ещё окно. Спрятанное — живо, уничтоженное — нет."""
    return bool(user32.IsWindow(hwnd))


# --- права и перетаскивание ---

ERROR_CANCELLED = 1223

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def is_elevated():
    """Запущены ли мы от администратора."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def integrity_level(pid):
    """Уровень доверия процесса или None, если прочитать не дали.

    Обычная программа — 0x2000, поднятая до администратора — 0x3000,
    системная — 0x4000. Сравнение этих чисел и объясняет, почему одному
    процессу не дают трогать окна другого.
    """
    try:
        import win32api
        import win32security

        handle = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        try:
            token = win32security.OpenProcessToken(handle, win32security.TOKEN_QUERY)
            sid, _ = win32security.GetTokenInformation(
                token, win32security.TokenIntegrityLevel
            )
            return sid.GetSubAuthority(sid.GetSubAuthorityCount() - 1)
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return None


def higher_integrity(pid):
    """Стоит ли чужой процесс выше нас по правам."""
    mine = integrity_level(os.getpid())
    theirs = integrity_level(pid)
    if mine is None or theirs is None:
        return False
    return theirs > mine


def pid_of_window(hwnd):
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return None


def set_app_id(app_id="Automaticsic"):
    """Своё имя в панели задач.

    Без этого запуск из исходников группируется под значком python.exe
    и показывает его иконку вместо нашей.
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return True
    except Exception:
        return False


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]



SERVICE_TITLES = {"MSCTFIME UI", "Default IME", "QTrayIconMessageWindow"}


def windows_of_pid(pid, include_hidden=False):
    result = []

    def collect(hwnd, _):
        if not include_hidden and not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.GetParent(hwnd):
            return True
        try:
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if window_pid != pid:
            return True
        title = win32gui.GetWindowText(hwnd) or ""
        if not title or title in SERVICE_TITLES:
            return True
        result.append(hwnd)
        return True

    win32gui.EnumWindows(collect, None)
    return result


def window_title(hwnd):
    try:
        return win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return ""


def filter_by_title(hwnds, substring):
    if not substring:
        return hwnds
    needle = substring.lower()
    return [h for h in hwnds if needle in window_title(h).lower()]


def wait_for_window(pid, timeout_ms=10000, poll_ms=200, exe_name=None):
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        found = windows_of_pid(pid)
        if found:
            return found[0], pid

        if exe_name:
            for other in sorted(pids_by_name(exe_name)):
                found = windows_of_pid(other)
                if found:
                    return found[0], other

        time.sleep(poll_ms / 1000.0)
    return None, pid


SHOW_COMMANDS = {
    "minimize": win32con.SW_MINIMIZE,
    "maximize": win32con.SW_MAXIMIZE,
    "hide": win32con.SW_HIDE,
    "show": win32con.SW_SHOW,
    "restore": win32con.SW_RESTORE,
}

# Чем проверять, что команда действительно подействовала. Windows на
# ShowWindow ничего внятного не возвращает: она сообщает, каким окно было
# раньше, а не удалось ли его переключить. Поэтому смотрим на состояние сами.
SHOW_CHECKS = {
    "minimize": lambda hwnd: win32gui.IsIconic(hwnd),
    "maximize": lambda hwnd: is_maximized(hwnd),
    "hide": lambda hwnd: not win32gui.IsWindowVisible(hwnd),
    "show": lambda hwnd: win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd),
    "restore": lambda hwnd: not win32gui.IsIconic(hwnd) and not is_maximized(hwnd),
    "foreground": lambda hwnd: user32.GetForegroundWindow() == hwnd,
    # Крестик считается нажатым, если окна не стало: программа его либо
    # уничтожила, либо спрятала по-своему. И то и другое — успех.
    "close": lambda hwnd: not window_exists(hwnd) or not win32gui.IsWindowVisible(hwnd),
}

# Сколько ждать результата. Крестик — не команда, а просьба: программа
# успевает спросить «сохранить?», прибраться и только потом убрать окно.
CHECK_TIMEOUTS = {"close": 3000}


def took_effect(hwnd, action, timeout_ms=None, poll_ms=50):
    """Дождаться, пока окно окажется в нужном состоянии.

    С запасом по времени: сворачивание и разворачивание анимированы,
    сразу после команды состояние ещё прежнее.
    """
    check = SHOW_CHECKS.get(action)
    if check is None:
        return True

    if timeout_ms is None:
        timeout_ms = CHECK_TIMEOUTS.get(action, 500)

    deadline = time.time() + timeout_ms / 1000.0
    while True:
        try:
            if check(hwnd):
                return True
        except Exception:
            return False
        if time.time() >= deadline:
            return False
        time.sleep(poll_ms / 1000.0)


def apply_show(hwnd, action):
    if action == "close":
        # Не ShowWindow, а то же сообщение, что шлёт сама Windows по клику
        # на крестик. Программа его перехватывает и решает сама: закрыться
        # или спрятаться в свой трей — так, чтобы потом суметь вернуться.
        return close_window(hwnd)

    cmd = SHOW_COMMANDS.get(action)
    if cmd is None:
        return False

    if action == "show":
        # Спрятанное в трей и свёрнутое в панель задач — разные состояния,
        # и они складываются. SW_SHOW достаёт из трея, SW_RESTORE разворачивает
        # из панели; чтобы пункт работал в обоих случаях, нужны обе команды.
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        return True

    if action == "maximize" and win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    win32gui.ShowWindow(hwnd, cmd)
    return True


# --- мониторы ---

MONITORINFOF_PRIMARY = 1


def monitors():
    """Подключённые мониторы: номер, границы, рабочая область, основной ли.

    Номер попадает в сценарий, поэтому нумеруем сами и предсказуемо —
    слева направо, сверху вниз, как экраны стоят на столе. Порядок, в котором
    их отдаёт Windows, зависит от того, в каком они подключены, и меняется
    от перетыкания кабеля.
    """
    found = []
    for handle, _, _ in win32api.EnumDisplayMonitors(None, None):
        try:
            info = win32api.GetMonitorInfo(handle)
        except Exception:
            continue
        found.append({
            "rect": tuple(info["Monitor"]),
            "work": tuple(info["Work"]),
            "primary": bool(info.get("Flags", 0) & MONITORINFOF_PRIMARY),
            "device": info.get("Device", ""),
        })

    found.sort(key=lambda m: (m["rect"][0], m["rect"][1]))
    for index, monitor in enumerate(found, 1):
        monitor["index"] = index
    return found


def find_monitor(target):
    """Монитор по номеру или по слову «primary». None, если такого нет."""
    found = monitors()
    if not found:
        return None

    if target == "primary":
        return next((m for m in found if m["primary"]), found[0])

    try:
        number = int(target)
    except (TypeError, ValueError):
        return None
    return next((m for m in found if m["index"] == number), None)


def _overlap(a, b):
    """Площадь пересечения двух прямоугольников (left, top, right, bottom)."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return max(width, 0) * max(height, 0)


def monitor_of_rect(rect):
    """Монитор, на котором лежит бо́льшая часть прямоугольника.

    Считаем сами, а не через MonitorFromWindow: меньше зависимостей от того,
    что именно завернули в pywin32, а логика та же — наибольшее пересечение,
    а если окно вообще за пределами экранов, то ближайший по центру.
    """
    found = monitors()
    if not found:
        return None

    best = max(found, key=lambda m: _overlap(rect, m["rect"]))
    if _overlap(rect, best["rect"]):
        return best

    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2

    def distance(m):
        left, top, right, bottom = m["rect"]
        return ((left + right) / 2 - cx) ** 2 + ((top + bottom) / 2 - cy) ** 2

    return min(found, key=distance)


def monitor_of_window(hwnd):
    """На каком мониторе сейчас окно."""
    return monitor_of_rect(win32gui.GetWindowRect(hwnd))


# --- смена основного монитора ---

CCHDEVICENAME = 32
CCHFORMNAME = 32

ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
DM_POSITION = 0x00000020
CDS_UPDATEREGISTRY = 0x00000001
CDS_SET_PRIMARY = 0x00000010
CDS_NORESET = 0x10000000
DISP_CHANGE_SUCCESSFUL = 0


class POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class DEVMODEW(ctypes.Structure):
    """Настройки экрана. Нас интересует только dmPosition, но структуру
    приходится описывать целиком: Windows проверяет dmSize."""

    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * CCHDEVICENAME),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPosition", POINTL),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * CCHFORMNAME),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


user32.EnumDisplaySettingsExW.argtypes = [
    ctypes.c_wchar_p, wintypes.DWORD, ctypes.POINTER(DEVMODEW), wintypes.DWORD,
]
user32.EnumDisplaySettingsExW.restype = wintypes.BOOL

user32.ChangeDisplaySettingsExW.argtypes = [
    ctypes.c_wchar_p, ctypes.POINTER(DEVMODEW), wintypes.HWND,
    wintypes.DWORD, wintypes.LPVOID,
]
user32.ChangeDisplaySettingsExW.restype = wintypes.LONG


DISP_ERRORS = {
    1: "нужна перезагрузка",
    -1: "драйвер не принял раскладку",
    -2: "недопустимый режим экрана",
    -3: "настройки не записались в реестр",
    -4: "неверные флаги",
    -5: "неверные параметры",
    -6: "режим недоступен для этой видеосистемы",
}


def _disp_error(code):
    return DISP_ERRORS.get(code, f"код {code}")


def _display_modes():
    """Текущие настройки всех экранов: {имя устройства: DEVMODEW}.

    Читать надо у всех: если хоть один экран не отдал настройки, двигать
    раскладку нельзя — оставшийся на месте перекроет соседей, и Windows
    отвергнет всю перестановку.
    """
    modes = {}
    for monitor in monitors():
        name = monitor.get("device")
        if not name:
            raise OSError("Windows не сообщила имя устройства для одного из экранов")

        mode = DEVMODEW()
        mode.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsExW(
            name, ENUM_CURRENT_SETTINGS, ctypes.byref(mode), 0
        ):
            raise OSError(f"не удалось прочитать настройки экрана {name}")

        # Драйвер мог сообщить, сколько своих данных он готов отдать сверху.
        # Их у нас нет, а Windows по этому полю полезет читать за буфер —
        # обнуляем перед тем, как отправлять структуру обратно.
        mode.dmDriverExtra = 0
        modes[name] = mode

    return modes


def _stage_position(device, mode, primary):
    """Записывает новое положение экрана, но пока не применяет."""
    mode.dmFields = DM_POSITION
    mode.dmDriverExtra = 0

    flags = CDS_UPDATEREGISTRY | CDS_NORESET
    if primary:
        flags |= CDS_SET_PRIMARY

    result = user32.ChangeDisplaySettingsExW(
        device, ctypes.byref(mode), None, flags, None
    )
    if result != DISP_CHANGE_SUCCESSFUL:
        raise OSError(
            f"{device} → ({mode.dmPosition.x}, {mode.dmPosition.y})"
            f"{' основной' if primary else ''}: {_disp_error(result)}"
        )


def _apply_layout():
    result = user32.ChangeDisplaySettingsExW(None, None, None, 0, None)
    if result != DISP_CHANGE_SUCCESSFUL:
        raise OSError(f"новая раскладка не применилась: {_disp_error(result)}")


def set_primary_monitor(monitor):
    """Делает монитор основным.

    Основной — это просто тот, что стоит в начале координат, поэтому одной
    командой не обойтись: новый основной надо сдвинуть в (0, 0), а все
    остальные — на ту же величину, иначе рабочий стол расползётся. Windows
    принимает правки по одному экрану (CDS_NORESET) и применяет их разом
    последним вызовом с пустым именем.

    Новый основной идёт первым: в раскладке всегда должен быть экран
    в начале координат, и если сперва увезти оттуда старый, Windows
    отвергнет всю перестановку.

    Сдвиг одинаковый для всех, поэтому взаимное расположение экранов
    не меняется — и наша нумерация слева направо остаётся прежней.
    """
    name = monitor.get("device")
    modes = _display_modes()
    if not name or name not in modes:
        raise OSError("не удалось прочитать настройки экранов")

    was_primary = next((m.get("device") for m in monitors() if m["primary"]), None)
    origin = {
        device: (mode.dmPosition.x, mode.dmPosition.y)
        for device, mode in modes.items()
    }

    shift_x, shift_y = -origin[name][0], -origin[name][1]
    order = [name] + [device for device in modes if device != name]

    def place(device, x, y, primary):
        mode = modes[device]
        mode.dmPosition.x, mode.dmPosition.y = x, y
        _stage_position(device, mode, primary)

    try:
        for device in order:
            x, y = origin[device]
            place(device, x + shift_x, y + shift_y, device == name)
        _apply_layout()
    except OSError:
        # Записанная наполовину раскладка так и лежит в реестре и всплыла бы
        # при следующем входе в систему. Возвращаем как было.
        for device, (x, y) in origin.items():
            try:
                place(device, x, y, device == was_primary)
            except OSError:
                pass
        try:
            _apply_layout()
        except OSError:
            pass
        raise

    return True


def display_report():
    """Что известно про экраны — строкой, для разбора неудачной перестановки."""
    lines = []
    try:
        modes = _display_modes()
    except OSError as e:
        modes = {}
        lines.append(f"настройки прочитать не удалось: {e}")

    for monitor in monitors():
        device = monitor.get("device") or "<без имени>"
        left, top, right, bottom = monitor["rect"]
        mark = " основной" if monitor["primary"] else ""
        lines.append(
            f"{monitor['index']}. {device}{mark} "
            f"{right - left}×{bottom - top} в ({left}, {top})"
        )

        mode = modes.get(device)
        if mode is not None:
            lines.append(
                f"    режим: {mode.dmPelsWidth}×{mode.dmPelsHeight}, "
                f"{mode.dmDisplayFrequency} Гц, {mode.dmBitsPerPel} бит, "
                f"позиция ({mode.dmPosition.x}, {mode.dmPosition.y})"
            )

    return "\n".join(lines)


def _work_area_of_window(hwnd):
    rect = win32gui.GetWindowRect(hwnd)
    monitor = monitor_of_rect(rect)
    return monitor["work"] if monitor else rect


def move_to_monitor(hwnd, monitor):
    """Переносит окно на монитор, сохраняя размер и место внутри экрана.

    Ведёт себя как системное Win+Shift+стрелка: окно оказывается на новом
    экране примерно там же, где стояло на старом, а не в углу. Развёрнутое
    приходится сперва восстановить — развёрнутое окно Windows не двигает,
    — а после переноса развернуть снова, уже на новом месте.
    """
    zoomed = is_maximized(hwnd)
    if zoomed or win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top

    from_left, from_top, from_right, from_bottom = _work_area_of_window(hwnd)
    to_left, to_top, to_right, to_bottom = monitor["work"]

    from_width = max(from_right - from_left, 1)
    from_height = max(from_bottom - from_top, 1)

    # Переносим не координаты, а доли: экраны бывают разного размера,
    # и середина одного не совпадает с серединой другого.
    x = to_left + round((left - from_left) / from_width * (to_right - to_left))
    y = to_top + round((top - from_top) / from_height * (to_bottom - to_top))

    # За край не пускаем: узкий монитор иначе оставил бы окно наполовину
    # за пределами видимого.
    x = max(to_left, min(x, to_right - width))
    y = max(to_top, min(y, to_bottom - height))

    win32gui.SetWindowPos(
        hwnd, 0, x, y, width, height,
        win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
    )

    if zoomed:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    return True


# --- обои рабочего стола ---

SPI_SETDESKWALLPAPER = 0x0014
SPI_GETDESKWALLPAPER = 0x0073
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02
COLOR_DESKTOP = 1

user32.SystemParametersInfoW.argtypes = [
    wintypes.UINT, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT,
]
user32.SystemParametersInfoW.restype = wintypes.BOOL

# Как растянуть картинку. Пара чисел — то, что Windows хранит в реестре:
# WallpaperStyle и TileWallpaper. Замощение задаётся вторым, а не первым.
WALLPAPER_STYLES = {
    "fill": ("10", "0"),
    "fit": ("6", "0"),
    "stretch": ("2", "0"),
    "tile": ("0", "1"),
    "center": ("0", "0"),
    "span": ("22", "0"),
}


def _apply_wallpaper(path):
    """Ставит обои. Пустой путь — снять обои совсем."""
    ok = user32.SystemParametersInfoW(
        SPI_SETDESKWALLPAPER, 0, path, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
    )
    if not ok:
        code = ctypes.GetLastError()
        raise OSError(f"Windows не приняла обои (код {code})")
    return True


def set_wallpaper_image(path, fit="fill"):
    """Картинка на рабочий стол.

    Способ размещения живёт не в вызове, а в реестре: SystemParametersInfo
    умеет только «поставить файл» и читает стиль оттуда. Поэтому сначала
    пишем стиль, потом ставим картинку.
    """
    style, tile = WALLPAPER_STYLES.get(fit, WALLPAPER_STYLES["fill"])
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, style)
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, tile)

    return _apply_wallpaper(os.path.abspath(path))


def set_wallpaper_color(rgb):
    """Сплошной цвет вместо картинки.

    Цвет фона виден только там, где нет обоев, поэтому обои сначала снимаем.
    SetSysColors красит рабочий стол прямо сейчас, но не помнит цвет после
    перезагрузки — за память отвечает запись в реестре.
    """
    red, green, blue = rgb

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Colors") as key:
        winreg.SetValueEx(key, "Background", 0, winreg.REG_SZ, f"{red} {green} {blue}")

    elements = (ctypes.c_int * 1)(COLOR_DESKTOP)
    # COLORREF — это 0x00BBGGRR, порядок байтов обратный привычному RGB.
    values = (wintypes.DWORD * 1)(red | (green << 8) | (blue << 16))
    user32.SetSysColors(1, elements, values)

    return _apply_wallpaper("")


def current_wallpaper():
    """Что стоит на столе прямо сейчас: путь, способ размещения, цвет фона.

    Три разных источника, потому что Windows хранит это в трёх местах:
    путь отдаёт SystemParametersInfo, способ размещения лежит в реестре
    отдельными числами, цвет фона — вообще в другой ветке. Пустой путь
    значит, что обоев нет и виден сплошной цвет.
    """
    buffer = ctypes.create_unicode_buffer(1024)
    user32.SystemParametersInfoW(
        SPI_GETDESKWALLPAPER, len(buffer), buffer, 0
    )
    path = buffer.value or ""

    style, tile = "10", "0"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            style = str(winreg.QueryValueEx(key, "WallpaperStyle")[0])
            tile = str(winreg.QueryValueEx(key, "TileWallpaper")[0])
    except OSError:
        pass

    fit = "fill"
    for name, pair in WALLPAPER_STYLES.items():
        if pair == (style, tile):
            fit = name
            break

    color = "#000000"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Colors") as key:
            parts = str(winreg.QueryValueEx(key, "Background")[0]).split()
            if len(parts) == 3:
                color = "#%02X%02X%02X" % tuple(int(part) for part in parts)
    except (OSError, ValueError):
        pass

    return {"path": path, "fit": fit, "color": color}


# --- значки из библиотек Windows ---

DI_NORMAL = 0x0003
BI_RGB = 0
DIB_RGB_COLORS = 0

gdi32 = ctypes.windll.gdi32


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def library_icon_count(path):
    """Сколько значков лежит в библиотеке."""
    try:
        return win32gui.ExtractIconEx(path, -1, 0)
    except Exception:
        return 0


def library_icon(path, index, size=32):
    """Точки значка из библиотеки Windows — по его номеру внутри файла.

    Отдаём сырые точки в порядке BGRA и размер: рисовать их — дело
    интерфейса, ядро про Qt не знает.

    Рисуем в 32-битный DIB, а не в обычную совместимую картинку. Разница
    решающая: у совместимой нет прозрачности, и вместо неё получается
    чёрный фон вокруг значка.
    """
    try:
        large, small = win32gui.ExtractIconEx(path, index, 1)
    except Exception:
        return None

    handles = list(large) + list(small)
    if not handles:
        return None

    # В библиотеке лежат два размера: крупный, обычно 32, и мелкий, 16.
    # Мелкий нарисован отдельно, а не уменьшён, поэтому для списка берём
    # именно его — уменьшенный крупный выглядит мыльным.
    hicon = (small[0] if small else large[0]) if size <= 16 else (
        large[0] if large else small[0])

    screen = user32.GetDC(0)
    memory = gdi32.CreateCompatibleDC(screen)

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = size
    # Минус — строки идут сверху вниз, как их ждёт кто угодно, кроме Windows.
    info.bmiHeader.biHeight = -size
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = BI_RGB

    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(
        memory, ctypes.byref(info), DIB_RGB_COLORS, ctypes.byref(bits), None, 0
    )

    data = None
    if bitmap:
        previous = gdi32.SelectObject(memory, bitmap)
        user32.DrawIconEx(memory, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
        data = ctypes.string_at(bits, size * size * 4)
        gdi32.SelectObject(memory, previous)
        gdi32.DeleteObject(bitmap)

    gdi32.DeleteDC(memory)
    user32.ReleaseDC(0, screen)
    for handle in handles:
        try:
            win32gui.DestroyIcon(handle)
        except Exception:
            pass

    return (data, size) if data else None


def shell32_path():
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                        "System32", "SHELL32.dll")


def bring_to_front(hwnd):
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        user32.SwitchToThisWindow(hwnd, True)
        return True


VK_MODIFIERS = {
    "ctrl": win32con.VK_CONTROL,
    "alt": win32con.VK_MENU,
    "shift": win32con.VK_SHIFT,
    "win": win32con.VK_LWIN,
}

VK_NAMED = {
    "enter": win32con.VK_RETURN,
    "esc": win32con.VK_ESCAPE,
    "tab": win32con.VK_TAB,
    "space": win32con.VK_SPACE,
    "backspace": win32con.VK_BACK,
    "delete": win32con.VK_DELETE,
    "insert": win32con.VK_INSERT,
    "home": win32con.VK_HOME,
    "end": win32con.VK_END,
    "pageup": win32con.VK_PRIOR,
    "pagedown": win32con.VK_NEXT,
    "up": win32con.VK_UP,
    "down": win32con.VK_DOWN,
    "left": win32con.VK_LEFT,
    "right": win32con.VK_RIGHT,
}

for _i in range(1, 25):
    VK_NAMED[f"f{_i}"] = win32con.VK_F1 + _i - 1

KEY_CHOICES = (
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(d) for d in range(10)]
    + [f"F{i}" for i in range(1, 13)]
    + ["Enter", "Esc", "Tab", "Space", "Backspace", "Delete", "Insert",
       "Home", "End", "PageUp", "PageDown", "Up", "Down", "Left", "Right"]
)


def key_to_vk(key):
    """Возвращает (код клавиши, список обязательных модификаторов) или None.

    VkKeyScanW отдаёт в старшем байте модификаторы, без которых символ
    на текущей раскладке не набрать: например «?» — это Shift+7.
    Раньше старший байт отбрасывался и хоткей уходил без Shift.
    """
    if not key:
        return None

    name = key.strip().lower()
    if name in VK_NAMED:
        return VK_NAMED[name], []

    if len(name) == 1:
        code = user32.VkKeyScanW(ord(name))
        if code == -1:
            return None
        state = (code >> 8) & 0xFF
        mods = []
        if state & 1:
            mods.append(win32con.VK_SHIFT)
        if state & 2:
            mods.append(win32con.VK_CONTROL)
        if state & 4:
            mods.append(win32con.VK_MENU)
        return code & 0xFF, mods

    return None


# --- отправка ввода через SendInput ---

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

# Клавиши с префиксом E0: делят коды с цифровым блоком и без флага
# распознаются как нумпад — стрелка «вправо» приезжает как «6».
EXTENDED_VKS = frozenset({
    win32con.VK_UP, win32con.VK_DOWN, win32con.VK_LEFT, win32con.VK_RIGHT,
    win32con.VK_HOME, win32con.VK_END, win32con.VK_PRIOR, win32con.VK_NEXT,
    win32con.VK_INSERT, win32con.VK_DELETE, win32con.VK_DIVIDE,
    win32con.VK_LWIN, win32con.VK_RWIN, win32con.VK_RCONTROL, win32con.VK_RMENU,
})

ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


def _key_event(vk, up):
    flags = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0
    if up:
        flags |= KEYEVENTF_KEYUP

    event = INPUT()
    event.type = INPUT_KEYBOARD
    event.ki.wVk = vk
    event.ki.dwFlags = flags
    return event


def send_input(events):
    if not events:
        return
    batch = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), batch, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(
            "Windows отклонила ввод — вероятно, целевое окно запущено "
            "от администратора, а Automaticsic нет"
        )


def send_hotkey(vk_list):
    """Нажимает сочетание одним пакетом событий.

    Модификаторы отпускаются в обратном порядке, иначе сочетание
    не распознаётся. Весь пакет уходит атомарно, поэтому живой ввод
    с клавиатуры уже не может вклиниться в середину.
    """
    events = [_key_event(vk, up=False) for vk in vk_list]
    events += [_key_event(vk, up=True) for vk in reversed(vk_list)]
    send_input(events)


# --- перехват клавиш раньше системы ---

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_INJECTED = 0x00000010

CTRL_KEYS = {win32con.VK_CONTROL, win32con.VK_LCONTROL, win32con.VK_RCONTROL}
ALT_KEYS = {win32con.VK_MENU, win32con.VK_LMENU, win32con.VK_RMENU}
SHIFT_KEYS = {win32con.VK_SHIFT, win32con.VK_LSHIFT, win32con.VK_RSHIFT}
WIN_KEYS = {win32con.VK_LWIN, win32con.VK_RWIN}
MODIFIER_KEYS = CTRL_KEYS | ALT_KEYS | SHIFT_KEYS | WIN_KEYS

_VK_TO_LOWER = {vk: name for name, vk in VK_NAMED.items()}
_DISPLAY_BY_LOWER = {name.lower(): name for name in KEY_CHOICES}


def vk_to_key_name(vk):
    """Имя клавиши по коду — обратное к key_to_vk."""
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    lower = _VK_TO_LOWER.get(vk)
    if not lower:
        return None
    return _DISPLAY_BY_LOWER.get(lower, lower.capitalize())


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOK_PROC = ctypes.CFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class KeyGrabber:
    """Ловит нажатия раньше Windows и не пропускает их дальше.

    Нужен для записи системных сочетаний. Alt+F4, Win+D и им подобные
    разбирает сама система, до окна они не доходят — обычным способом их
    не подсмотреть. Низкоуровневый хук стоит в очереди раньше системного
    разбора, поэтому видит нажатие первым и может его проглотить.

    Пока хук стоит, клавиатура целиком уходит нам: ни одно нажатие никуда
    не долетит. Поэтому включать его надо только на время записи и снимать
    сразу, как сочетание поймано.

    Ctrl+Alt+Del и Win+L перехватить нельзя ничем — их обрабатывает
    защищённая часть Windows.
    """

    def __init__(self, on_combo):
        self.on_combo = on_combo
        self._handle = None
        self._down = set()
        # Ссылку на обёртку держим сами: иначе сборщик мусора её уберёт,
        # а система продолжит звать освободившуюся память.
        self._proc = HOOK_PROC(self._callback)

    def start(self):
        if self._handle:
            return True

        user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int, HOOK_PROC, wintypes.HINSTANCE, wintypes.DWORD,
        )
        user32.SetWindowsHookExW.restype = ctypes.c_void_p

        self._down.clear()
        self._handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        return bool(self._handle)

    def stop(self):
        if self._handle:
            user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
            user32.UnhookWindowsHookEx(self._handle)
            self._handle = None
        self._down.clear()

    def _flags(self):
        # Состояние модификаторов ведём сами: проглоченное нажатие может
        # не дойти до системного состояния клавиатуры, и GetAsyncKeyState
        # покажет неправду.
        return {
            "ctrl": bool(self._down & CTRL_KEYS),
            "alt": bool(self._down & ALT_KEYS),
            "shift": bool(self._down & SHIFT_KEYS),
            "win": bool(self._down & WIN_KEYS),
        }

    def _callback(self, code, wparam, lparam):
        if code != 0:
            return user32.CallNextHookEx(None, code, wparam, lparam)

        info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents

        # Свои же нажатия из send_hotkey ловить незачем.
        if info.flags & LLKHF_INJECTED:
            return user32.CallNextHookEx(None, code, wparam, lparam)

        vk = info.vkCode

        if wparam in (WM_KEYUP, WM_SYSKEYUP):
            self._down.discard(vk)
            return 1

        if wparam not in (WM_KEYDOWN, WM_SYSKEYDOWN):
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._down.add(vk)

        if vk in MODIFIER_KEYS:
            return 1

        name = vk_to_key_name(vk)
        if name:
            combo = self._flags()
            combo["key"] = name
            self.on_combo(combo)

        return 1


SW_FOR_SHOW = {
    "normal": win32con.SW_SHOWNORMAL,
    "maximized": win32con.SW_SHOWMAXIMIZED,
    "minimized": win32con.SW_SHOWMINNOACTIVE,
    "hidden": win32con.SW_HIDE,
}


def read_shortcut(path):
    """Разбирает .lnk на (цель, аргументы, рабочая папка)."""
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        link = shell.CreateShortCut(path)
        return (
            link.Targetpath or path,
            (link.Arguments or "").strip(),
            link.WorkingDirectory or "",
        )
    except Exception:
        return path, "", ""


def resolve_target(path):
    """Путь к exe: для ярлыка — его цель, для остального — сам путь."""
    if not (path or "").lower().endswith(".lnk"):
        return path
    return read_shortcut(path)[0]


# Схема с двойным слешем: steam://, mailto: сюда намеренно не попадает —
# у него своего слеша нет, а нам нужны именно адреса запуска.
URI = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def is_uri(value):
    return bool(URI.match((value or "").strip()))


def is_url_shortcut(path):
    """Интернет-ярлык .url — не программа, а адрес внутри файла."""
    return (path or "").lower().endswith(".url")


def read_url_shortcut(path):
    """Адрес из интернет-ярлыка.

    Внутри обычный ini: раздел [InternetShortcut] и строка URL=. Читаем
    сами: файл простой, а COM ради одной строки — лишнее.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.lower().startswith("url="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


shell32 = ctypes.windll.shell32
shell32.ShellExecuteW.argtypes = [
    wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int,
]
shell32.ShellExecuteW.restype = ctypes.c_ssize_t


def shell_open(target, show="normal"):
    """Отдаёт цель проводнику — пусть сам решает, чем её открыть.

    PID отсюда не вернуть: адрес вроде steam:// обрабатывает не наш процесс,
    а зарегистрированная на схему программа, и что она потом породит,
    Windows нам не сообщает.
    """
    result = shell32.ShellExecuteW(
        None, "open", target, None, None,
        SW_FOR_SHOW.get(show, win32con.SW_SHOWNORMAL),
    )
    # Всё, что до 32 включительно, — код ошибки, так задумано в самой функции.
    if result <= 32:
        raise OSError(f"Windows не смогла открыть «{target}» (код {result})")


def elevated_launch(path, args="", show="normal", work_dir=None):
    """Запускает программу с повышением прав — глагол runas, запрос UAC."""
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = path
    info.lpParameters = args or None
    info.lpDirectory = work_dir or None
    info.nShow = SW_FOR_SHOW.get(show, win32con.SW_SHOWNORMAL)

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        code = ctypes.GetLastError()
        if code == ERROR_CANCELLED:
            raise OSError("запуск от администратора отменён в запросе UAC")
        raise OSError(f"не удалось запустить от администратора (код {code})")

    pid = ctypes.windll.kernel32.GetProcessId(info.hProcess)
    ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return pid



def relaunch_elevated(arguments=""):
    """Перезапускает саму программу с повышением прав.

    Собранный exe запускает сам себя, из исходников — python с main.py.
    Аргументы передаются как есть, вместе с кавычками вокруг путей.
    """
    if getattr(sys, "frozen", False):
        return elevated_launch(sys.executable, arguments)

    entry = os.path.abspath(sys.argv[0])
    return elevated_launch(sys.executable, f'"{entry}" {arguments}'.strip())


def shell_launch(path, show="normal", args=""):
    is_lnk = path.lower().endswith(".lnk")
    target = path
    arguments = (args or "").strip()
    work_dir = ""

    if is_lnk:
        target, lnk_args, work_dir = read_shortcut(path)
        # Аргументы шага важнее: ярлык мог быть развёрнут давно и с тех пор
        # правился руками.
        if not arguments:
            arguments = lnk_args

    exe_name = os.path.basename(target).lower()
    before = pids_by_name(exe_name)

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = SW_FOR_SHOW.get(show, win32con.SW_SHOWNORMAL)

    if not work_dir:
        work_dir = os.path.dirname(target)


    if is_lnk and not os.path.isfile(target):
        # Ярлык ведёт не на файл — приложение из Store, элемент панели
        # управления. Пусть разбирается сам проводник.
        subprocess.Popen(
            ["cmd", "/c", "start", "", path],
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return wait_for_new_pid(exe_name, before)

    # Командная строка одной строкой, а не списком: аргументы уходят ровно
    # в том виде, в каком записаны, вместе с кавычками, и Windows разбирает
    # их сама — как при запуске ярлыка.
    cmdline = f'"{target}"'
    if arguments:
        cmdline += f" {arguments}"

    proc = subprocess.Popen(cmdline, cwd=work_dir or None, startupinfo=startupinfo)
    return proc.pid


def pids_by_name(exe_name):
    import psutil

    found = set()
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if (proc.info["name"] or "").lower() == exe_name:
                found.add(proc.info["pid"])
        except psutil.Error:
            continue
    return found


def registered_exe(exe_name):
    """Путь к программе из реестра «App Paths».

    Туда установщики записывают, где лежит программа, — именно оттуда
    Windows узнаёт путь, когда в «Выполнить» пишут одно имя. Работает
    и когда программа закрыта, в отличие от поиска среди процессов.
    """
    branch = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe_name
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, branch) as key:
                path = str(winreg.QueryValueEx(key, "")[0]).strip().strip('"')
        except OSError:
            continue
        if path and os.path.isfile(path):
            return path
    return ""


def exe_path_by_name(exe_name):
    """Путь к программе по имени exe — если она сейчас запущена.

    Нужен для значка: в шаге закрытия записано «notepad.exe», а значок
    лежит в файле, и найти файл можно только у живого процесса.
    """
    import psutil

    name = (exe_name or "").lower()
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() == name:
                path = proc.exe()
                if path and os.path.isfile(path):
                    return path
        except psutil.Error:
            continue
    return ""


def wait_for_new_pid(exe_name, before, timeout_ms=10000, poll_ms=150):
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        new = pids_by_name(exe_name) - before
        if new:
            return sorted(new)[0]
        time.sleep(poll_ms / 1000.0)
    return None


# --- выход, как при выключении Windows ---

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
ENDSESSION_CLOSEAPP = 0x00000001
SMTO_ABORTIFHUNG = 0x0002

user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(wintypes.DWORD),
]


def all_windows_of_pid(pid):
    """Все окна процесса верхнего уровня, включая скрытые и подчинённые.

    Отличается от windows_of_pid тем, что ничего не отсеивает. Для выхода
    это важно: программа может слушать сообщение не в главном окне,
    а в служебном и невидимом — у INCY их шесть штук на одно видимое.
    """
    found = []

    def collect(hwnd, _):
        try:
            if win32process.GetWindowThreadProcessId(hwnd)[1] == pid:
                found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(collect, None)
    except Exception:
        pass
    return found


def end_session(hwnd, timeout_ms=5000):
    """Просит окно выйти так, как оно вышло бы при выключении Windows.

    Крестик программа вправе перехватить и спрятаться в трей — так делают
    INCY и Telegram. На выключение системы спрятаться нельзя: программа
    обязана ответить и закрыться, свернув за собой всё, что подняла, —
    туннель, соединения, временные файлы.

    Разговор из двух сообщений: сначала «можно выключаться?», потом
    «выключаемся». Отправляем с ожиданием ответа, а не вдогонку: программе
    надо дать успеть прибраться, а нам — узнать, что сообщение дошло.
    Windows не пропускает сообщения программе с правами выше своих,
    поэтому от администратора это работает, а без него — нет.
    """
    answer = wintypes.DWORD(0)
    delivered = user32.SendMessageTimeoutW(
        hwnd, WM_QUERYENDSESSION, 0, ENDSESSION_CLOSEAPP,
        SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(answer),
    )
    if not delivered:
        return False

    user32.SendMessageTimeoutW(
        hwnd, WM_ENDSESSION, 1, ENDSESSION_CLOSEAPP,
        SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(answer),
    )
    return True


def close_window(hwnd):
    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return True
    except Exception:
        return False


# --- запуск команд оболочки ---

# Флаги CreateProcess. Своя консоль нужна режиму «в окне», отсутствие консоли —
# тихому: иначе на каждой команде моргало бы чёрное окно.
CREATE_NEW_CONSOLE = 0x00000010
CREATE_NO_WINDOW = 0x08000000
# Своя группа процессов: без неё Ctrl+C, пришедший нашему процессу, свалил бы
# и запущенную команду заодно.
CREATE_NEW_PROCESS_GROUP = 0x00000200


def console_encoding():
    """Кодировка, в которой консоль отвечает.

    Это не ANSI-кодировка системы: cmd на русской Windows пишет в cp866,
    а cp1251 отдаёт только графический интерфейс. Спутать их — получить
    в логе кракозябры ровно там, где лог и нужен.
    """
    try:
        return "cp%d" % ctypes.windll.kernel32.GetOEMCP()
    except Exception:
        return "cp866"


def shell_command(shell, script_path, keep_open):
    """Командная строка запуска сгенерированного скрипта.

    Скрипт, а не команда строкой: так многострочное работает само собой,
    и не надо воевать с экранированием & | ^ и кавычек.
    """
    if shell == "powershell":
        exe = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
        )
        args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path]
        # -NoExit оставляет приглашение после конца скрипта: без него окно
        # с ipconfig закрылось бы раньше, чем на него успели посмотреть.
        return [exe] + (["-NoExit"] if keep_open else []) + args

    exe = os.environ.get("COMSPEC") or "cmd.exe"
    # Через call, а не путём напрямую: у cmd своё правило про кавычки
    # в первом аргументе, и путь с пробелом (а профиль пользователя
    # запросто «Иван Петров») по нему разбирается неверно. call —
    # обычная команда, кавычки в ней работают как везде, и код
    # возврата он пропускает через себя.
    return [exe, "/k" if keep_open else "/c", "call", script_path]


def script_body(shell, command):
    """Тело временного скрипта вокруг команды пользователя."""
    if shell == "powershell":
        # Иначе код возврата у PowerShell почти всегда 0: ноль там означает
        # только, что сам PowerShell не упал, а не что команда сработала.
        head = "$ErrorActionPreference = 'Stop'"
        return f"{head}\r\n{command}\r\nexit $LASTEXITCODE\r\n"
    return f"@echo off\r\n{command}\r\n"


def script_suffix(shell):
    return ".ps1" if shell == "powershell" else ".bat"


def script_encoding(shell):
    """В какой кодировке писать временный скрипт.

    Две разные, и обе не UTF-8 «просто так». Файл .bat читает cmd —
    в кодировке консоли. Файл .ps1 читает PowerShell 5.1, и без метки
    в начале файла он считает его однобайтовым: русские буквы в путях
    превратятся в мусор. Метку ставит utf-8-sig.
    """
    return "utf-8-sig" if shell == "powershell" else console_encoding()


def start_detached(argv, work_dir, flags):
    """Запуск, который переживёт сценарий.

    Сценарий с двойного клика отрабатывает и закрывается, а ssh-мост
    должен остаться. Своя группа процессов и закрытые наследуемые
    дескрипторы — то, что отвязывает запущенное от нас.
    """
    return subprocess.Popen(
        argv,
        cwd=work_dir or None,
        close_fds=True,
        creationflags=flags | CREATE_NEW_PROCESS_GROUP,
    )

