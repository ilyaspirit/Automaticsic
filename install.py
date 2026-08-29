import ctypes
import os
import sys
import winreg

import model

PROG_ID = "Automaticsic.Script"

SHCNE_ASSOCCHANGED = 0x08000000
SHCNF_IDLIST = 0x0000

RT_GROUP_ICON = 14
LOAD_LIBRARY_AS_DATAFILE = 0x00000002

# Значки внутри exe нумеруются с нуля: нулевой — сама программа,
# первый — документ. Порядок задаётся списком icon=[...] в .spec.
FILE_ICON_INDEX = 1

USER_CHOICE_PATH = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer"
    rf"\FileExts\{model.EXT}\UserChoice"
)


def refresh_shell():
    """Просит проводник перечитать ассоциации.

    Без этого значок у .asic остаётся прежним: проводник держит свой кэш
    и сам его не сбрасывает — файлы так и лежат со старой картинкой.
    """
    try:
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )
        return True
    except Exception:
        return False


def user_choice():
    """Программа, выбранная через «Открыть с помощью».

    Windows держит такой выбор отдельно и ставит его выше нашей записи
    в Software\\Classes: и значок, и запуск берутся оттуда.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_CHOICE_PATH) as key:
            value, _ = winreg.QueryValueEx(key, "ProgId")
            return value
    except OSError:
        return None


def foreign_choice():
    """ProgId чужой программы, перебивающей нашу привязку, или None."""
    choice = user_choice()
    return choice if choice and choice != PROG_ID else None


def clear_user_choice():
    """Снимает чужой выбор «Открыть с помощью».

    Записать туда своё значение нельзя — Windows защищает ключ хешем,
    который умеет считать только она сама. А удалить обычно даёт,
    и тогда снова работает обычная привязка из Software\\Classes.
    """
    if not foreign_choice():
        return True
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, USER_CHOICE_PATH)
        return True
    except OSError:
        return False


def read_default(path):
    """Значение по умолчанию ключа реестра или None."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return value
    except OSError:
        return None


def report():
    """Что сейчас записано о файлах .asic — для окна диагностики."""
    base = r"Software\Classes"
    exe = exe_path()
    icon = model.icon_path()

    prog_id = read_default(rf"{base}\{model.EXT}") or "— ничего —"
    default_icon = read_default(rf"{base}\{PROG_ID}\DefaultIcon") or "— не задан —"

    return "\n".join([
        f"Программа:  {exe}",
        f"            {'найдена' if os.path.isfile(exe) else 'НЕ НАЙДЕНА'}",
        f"Файл значка: {'на месте' if os.path.isfile(icon) else 'НЕТ'}",
        f"Значков в exe: {icon_count(exe)} (нужно 2: программа и документ)",
        "",
        f"{model.EXT} привязан к: {prog_id}",
        f"Значок:     {default_icon}",
        f"Команда:    {current_target() or '— не задана —'}",
        "",
        f"«Открыть с помощью»: {user_choice() or '— не выбрано —'}",
    ])


def icon_count(exe):
    """Сколько групп значков лежит внутри exe."""
    try:
        import win32api

        handle = win32api.LoadLibraryEx(exe, 0, LOAD_LIBRARY_AS_DATAFILE)
        try:
            return len(win32api.EnumResourceNames(handle, RT_GROUP_ICON))
        finally:
            win32api.FreeLibrary(handle)
    except Exception:
        return 0


def file_icon(exe):
    """Строка DefaultIcon: значок документа, если он в exe есть.

    Собранный до появления второго значка exe его не содержит — тогда
    берём нулевой, значок программы, вместо пустого места.
    """
    index = FILE_ICON_INDEX if icon_count(exe) > FILE_ICON_INDEX else 0
    return f'"{exe}",{index}'


def exe_path():
    if getattr(sys, "frozen", False):
        return sys.executable
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "dist", "Automaticsic.exe"))


def set_value(path, name, value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def install():
    exe = exe_path()
    if not os.path.isfile(exe):
        print(f"Не найден exe: {exe}")
        print("Сначала собери проект: uv run pyinstaller --noconfirm Automaticsic.spec")
        return 1

    # Чужой выбор из «Открыть с помощью» перебивает всё, что мы напишем
    # ниже, — пробуем снять его первым делом.
    clear_user_choice()

    base = r"Software\Classes"

    set_value(rf"{base}\{model.EXT}", "", PROG_ID)
    set_value(rf"{base}\{PROG_ID}", "", "Automaticsic script")
    set_value(rf"{base}\{PROG_ID}\DefaultIcon", "", file_icon(exe))
    set_value(rf"{base}\{PROG_ID}\shell", "", "run")
    set_value(rf"{base}\{PROG_ID}\shell\run", "", "Выполнить")
    set_value(rf"{base}\{PROG_ID}\shell\run\command", "", f'"{exe}" "%1"')
    set_value(rf"{base}\{PROG_ID}\shell\edit", "", "Редактировать")
    set_value(rf"{base}\{PROG_ID}\shell\edit\command", "", f'"{exe}" --edit "%1"')

    refresh_shell()

    print(f"Готово. {model.EXT} привязан к {exe}")
    print("Двойной клик — выполнение, правый клик → Редактировать — редактор.")

    other = foreign_choice()
    if other:
        print(f"\nВнимание: для {model.EXT} выбрана другая программа ({other}).")
        print("Этот выбор перебивает привязку — значок и запуск берутся из него.")
        print("Сними его: правый клик по файлу → Открыть с помощью → "
              "Выбрать другое приложение → Automaticsic → всегда.")
    return 0


def uninstall():
    base = r"Software\Classes"
    for path in (
        rf"{base}\{PROG_ID}\shell\edit\command",
        rf"{base}\{PROG_ID}\shell\edit",
        rf"{base}\{PROG_ID}\shell\run\command",
        rf"{base}\{PROG_ID}\shell\run",
        rf"{base}\{PROG_ID}\shell",
        rf"{base}\{PROG_ID}\DefaultIcon",
        rf"{base}\{PROG_ID}",
        rf"{base}\{model.EXT}",
    ):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass
    refresh_shell()
    print("Ассоциация удалена")
    return 0


def is_installed():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{model.EXT}") as key:
            value, _ = winreg.QueryValueEx(key, "")
            return value == PROG_ID
    except FileNotFoundError:
        return False


def current_target():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROG_ID}\shell\run\command"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            return value
    except FileNotFoundError:
        return None


def needs_update():
    if not getattr(sys, "frozen", False):
        return False
    expected = f'"{sys.executable}" "%1"'
    return current_target() != expected


if __name__ == "__main__":
    sys.exit(uninstall() if "--uninstall" in sys.argv else install())