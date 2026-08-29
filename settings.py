import json
import os

import model

DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), model.APP_NAME)
FILE = os.path.join(DIR, "settings.json")

DEFAULTS = {
    "write_log": True,
    # Обои, запомненные шагом перед сменой: путь, способ размещения, цвет.
    # Живут здесь, а не в сценарии, — вернуть их может другой сценарий,
    # запущенный хоть через неделю.
    "saved_wallpaper": None,
    # Где лежит программа с таким именем exe. Заполняется само, когда
    # программу удаётся увидеть запущенной: потом её значок находится
    # и после того, как она закрыта.
    "exe_paths": {},
}

_cache = None


def load():
    global _cache
    if _cache is not None:
        return _cache
    data = dict(DEFAULTS)
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data.update(json.load(f))
    except (OSError, ValueError):
        pass
    _cache = data
    return _cache


def save(data=None):
    global _cache
    if data is not None:
        _cache = dict(DEFAULTS)
        _cache.update(data)
    os.makedirs(DIR, exist_ok=True)
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def get(key):
    return load().get(key, DEFAULTS.get(key))


def known_exe(exe_name):
    """Где лежит программа с таким именем — если мы это уже выяснили."""
    path = (get("exe_paths") or {}).get((exe_name or "").lower(), "")
    return path if path and os.path.isfile(path) else ""


def remember_exe(exe_name, path):
    """Запоминает путь к программе.

    Имя exe в шаге закрытия — это всё, что у нас есть, а значок лежит
    в файле. Пока программа запущена, путь можно спросить у неё; когда
    закрыта — уже не у кого. Поэтому записываем в тот момент, когда путь
    точно известен: при выборе из списка запущенных и при выполнении шага.
    """
    name = (exe_name or "").lower()
    if not name or not path or not os.path.isfile(path):
        return
    paths = dict(get("exe_paths") or {})
    if paths.get(name) == path:
        return
    paths[name] = path
    set_value("exe_paths", paths)


def set_value(key, value):
    load()[key] = value
    save()