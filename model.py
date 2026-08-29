import json
import os
import sys
import uuid

EXT = ".asic"
APP_NAME = "Automaticsic"
ICON_FILE = "icon.ico"

# Единственное место, где живёт номер версии: отсюда его берут строка
# состояния и сборка, которая кладёт его в свойства exe.
VERSION = "1.0.0"

REPO_URL = "https://github.com/ilyaspirit/Automaticsic"
REPO_OWNER = "@ilyaspirit"

LAUNCH = "launch"
CLOSE = "close"
WINDOW = "window"
PAUSE = "pause"
COPY = "copy"
HOTKEY = "hotkey"
WALLPAPER = "wallpaper"
STREAMDECK = "streamdeck"
PRIMARY_MONITOR = "primary_monitor"
COMMAND = "command"

# Шаги разложены по группам: их уже девять, и меню «Добавить шаг»
# длинное. Список типов собирается отсюда, а не рядом, — иначе новый
# шаг рано или поздно попал бы в одно место и не попал в другое.
STEP_GROUPS = [
    ("Программы", [LAUNCH, CLOSE, COMMAND]),
    ("Окна и клавиши", [WINDOW, HOTKEY]),
    ("Экран", [PRIMARY_MONITOR, WALLPAPER]),
    ("Прочее", [PAUSE, COPY, STREAMDECK]),
]
STEP_TYPES = [t for _, types in STEP_GROUPS for t in types]
KNOWN_TYPES = frozenset(STEP_TYPES)

TYPE_NAMES = {
    LAUNCH: "Запуск программы",
    CLOSE: "Закрытие программы",
    WINDOW: "Действие с окном",
    PAUSE: "Пауза",
    COPY: "Копирование файла",
    HOTKEY: "Горячая клавиша",
    WALLPAPER: "Обои рабочего стола",
    STREAMDECK: "Яркость Stream Deck",
    PRIMARY_MONITOR: "Основной монитор",
    COMMAND: "Командная строка",
}

WINDOW_ACTIONS = {
    "maximize": "Развернуть на весь экран",
    "restore": "Восстановить обычный размер",
    "foreground": "Переместить на передний план",
    "monitor": "Сменить монитор",
    "minimize": "Свернуть в панель задач",
    "tray": "Свернуть в трей",
    "show": "Показать свёрнутое окно",
}

WINDOW_ACTION_HINTS = {
    "maximize": "Разворачивает окно на весь экран.",
    "restore": "Возвращает окну обычный размер — из развёрнутого\n"
               "или из свёрнутого в панель задач.",
    "foreground": "Поднимает окно поверх остальных и делает активным.\n"
                  "Свёрнутое сначала разворачивает.",
    "monitor": "Переносит окно на другой экран и больше ничего не трогает:\n"
               "развёрнутое останется развёрнутым, размер сохранится, место\n"
               "перенесётся пропорционально — как по Win+Shift+стрелка.",
    "minimize": "Обычное сворачивание — окно уходит в панель задач,\n"
                "оттуда же и достаётся.",
    "tray": "Убирает окно с экрана. Каким способом — задаётся ниже,\n"
            "в «Способе сворачивания».",
    "show": "Возвращает окно на экран — и спрятанное, и свёрнутое\n"
            "в панель задач.",
}

# Своего трея у Automaticsic за чужую программу быть не может, поэтому
# «свернуть в трей» — это либо просьба к самой программе, либо грубое
# сокрытие окна мимо неё. Разница видна только на практике, отсюда
# и подробные подсказки.
TRAY_MODES = {
    "close": "Нажать на крестик — программа спрячется сама",
    "hide": "Спрятать окно средствами Windows",
}

TRAY_MODE_HINTS = {
    "close": "Окну уходит ровно то, что Windows шлёт при клике по крестику.\n"
             "Что делать дальше, решает сама программа: Telegram, INCY\n"
             "и им подобные прячутся в свой трей — оттуда окно достаёт\n"
             "клик по значку. У кого трея нет, тот просто закроется.",
    "hide": "Windows убирает окно сама, мимо программы. Та об этом не знает:\n"
            "её значок в трее окно не вернёт, достать можно только шагом\n"
            "«Показать свёрнутое окно». Годится там, где своего трея нет\n"
            "и окно надо просто убрать с глаз.",
}

# Для названия шага в списке — коротко, чтобы два похожих шага различались.
TRAY_MODE_SHORT = {"close": "крестик", "hide": "мимо программы"}

# Монитор шага. Пусто — не трогать, «primary» — основной, иначе номер.
# Номер, а не системное имя устройства: имена вида \\.\DISPLAY2 переезжают
# с экрана на экран от перетыкания кабеля, а порядок слева направо — нет.
MONITOR_KEEP = ""
MONITOR_PRIMARY = "primary"

MONITOR_LABELS = {
    MONITOR_KEEP: "Не менять",
    MONITOR_PRIMARY: "Основной",
}

# Действия, при которых монитор что-то значит: свёрнутое и спрятанное окно
# переносить некуда.
MONITOR_ACTIONS = ("maximize", "restore", "foreground", "monitor")


def monitor_text(value):
    """Короткая подпись монитора — для лога и названия шага."""
    if not value:
        return ""
    if value == MONITOR_PRIMARY:
        return "основной монитор"
    return f"монитор {value}"

SHELLS = {
    "cmd": "cmd",
    "powershell": "PowerShell",
}

# Два режима, а не четыре: разница между «оставить окно» и «не ждать»
# видна только на мгновенных командах, а окно всё равно остаётся.
COMMAND_MODES = {
    "window": "В окне оболочки",
    "silent": "Без оболочки",
}

COMMAND_MODE_HINTS = {
    "window": "Открывается окно оболочки и остаётся на экране — видно, что\n"
              "происходит, и можно ответить на вопрос вроде пароля. Сценарий\n"
              "идёт дальше не дожидаясь, окно закрывается руками.",
    "silent": "Окна нет вовсе. Команда работает молча, а сценарий по галке\n"
              "ниже либо ждёт её конца и проверяет код возврата, либо идёт\n"
              "дальше сразу.",
}

CLOSE_MODES = {
    "soft": "Мягко",
    "session": "Как при выключении Windows",
    "soft_hard": "Мягко, затем жёстко",
    "hard": "Сразу жёстко",
}

CLOSE_MODE_HINTS = {
    "soft": "Просим закрыться, как крестиком. Программа вправе поступить\n"
            "по-своему: свернуться в трей и остаться работать.",
    "session": "Говорим то же, что Windows говорит перед выключением.\n"
               "Спрятаться в трей на это нельзя — программа обязана выйти\n"
               "и прибрать за собой: свернуть туннель, закрыть соединения.\n"
               "Для тех, кого крестик не берёт, а убивать нельзя.\n"
               "Никого не убивает: не вышла — считается ошибкой шага.",
    "soft_hard": "Сначала просим по-хорошему, потом, если не вышло за\n"
                 "отведённое время, завершаем принудительно.",
    "hard": "Завершаем процесс сразу. Программа не узнает об этом и ничего\n"
            "не успеет прибрать — то, что она держала, останется висеть.",
}

WALLPAPER_MODES = {
    "image": "Изображение",
    "color": "Сплошной цвет",
    "restore": "Вернуть запомненные",
}

WALLPAPER_MODE_HINTS = {
    "image": "Ставит картинку с выбранным способом размещения.",
    "color": "Убирает обои и заливает стол одним цветом.",
    "restore": "Возвращает то, что было запомнено галкой «запомнить прежние»\n"
               "в другом шаге. Запомненное лежит в настройках программы\n"
               "и переживает перезагрузку.",
}

# Названия те же, что в «Персонализация → Фон», чтобы не сочинять свои.
WALLPAPER_FITS = {
    "fill": "Заполнение",
    "fit": "По размеру",
    "stretch": "Растянуть",
    "tile": "Замостить",
    "center": "По центру",
    "span": "Расширить на все экраны",
}

DEFAULT_COLOR = "#1E1E1E"


def parse_color(value):
    """«#1E1E1E» → (30, 30, 30). None, если запись непонятна."""
    text = (value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def color_text(value):
    """Цвет в едином виде «#1E1E1E» — для подписей и лога."""
    rgb = parse_color(value)
    return "#%02X%02X%02X" % rgb if rgb else (value or "не задан")

DEFAULT_PARAMS = {
    LAUNCH: {
        "path": "",
        "args": "",
        "show": "normal",
        "if_running": "skip",
        "wait_window": True,
        "wait_timeout_ms": 3000,
        "monitor": "",
        "alias": "",
    },
    CLOSE: {
        "target_kind": "exe",
        "target": "",
        "mode": "soft_hard",
        "wait_close": True,
        "timeout_ms": 5000,
        "kill_children": True,
    },
    WINDOW: {
        "target_kind": "exe",
        "target": "",
        "title_contains": "",
        "action": "minimize",
        "tray_mode": "close",
        "monitor": "",
    },
    PAUSE: {"ms": 1000},
    COPY: {"src": "", "dst": ""},
    WALLPAPER: {
        "mode": "image",
        "path": "",
        "fit": "fit",
        "color": DEFAULT_COLOR,
        "remember": True,
    },
    STREAMDECK: {"percent": 100},
    PRIMARY_MONITOR: {"monitor": "1"},
    COMMAND: {
        "shell": "cmd",
        "command": "",
        "workdir": "",
        "mode": "window",
        "wait": True,
        "log_output": False,
        "timeout_ms": 10000,
    },
    HOTKEY: {
        "target_kind": "active",
        "target": "",
        "title_contains": "",
        "ctrl": False,
        "alt": False,
        "shift": False,
        "win": False,
        "key": "",
    },
}


def new_step(step_type):
    params = json.loads(json.dumps(DEFAULT_PARAMS[step_type]))
    return {
        "id": uuid.uuid4().hex[:8],
        "type": step_type,
        "enabled": True,
        "ignore_error": True,
        "comment": "",
        "params": params,
    }


def new_script():
    return {"name": "", "autopause_ms": 200, "steps": []}


def step_title(step):
    t = step.get("type")
    p = step.get("params") or {}

    if t == LAUNCH:
        name = os.path.basename(p["path"]) or "не задано"
        title = f"Запуск: {name}"
        monitor = monitor_text(p.get("monitor"))
        if monitor:
            title = f"{title} → {monitor}"
    elif t == CLOSE:
        title = f"Закрытие: {p['target'] or 'не задано'}"
    elif t == WINDOW:
        action = WINDOW_ACTIONS.get(p["action"], p["action"]).lower()
        if p["action"] == "tray":
            # Иначе два шага «свернуть в трей» разными способами выглядят
            # в списке одинаково.
            mode = TRAY_MODE_SHORT.get(p.get("tray_mode"))
            if mode:
                action = f"{action} ({mode})"
        monitor = monitor_text(p.get("monitor"))
        if p["action"] == "monitor":
            # Иначе вышло бы «сменить монитор → монитор 2».
            action = f"перенести на {monitor}" if monitor else action
        elif monitor and p["action"] in MONITOR_ACTIONS:
            action = f"{action} → {monitor}"
        title = f"Окно {p['target'] or '<окно не выбрано>'}: {action}"
    elif t == PAUSE:
        title = f"Пауза: {p['ms']} мс"
    elif t == COPY:
        title = f"Копирование: {os.path.basename(p['src']) or 'не задано'}"
    elif t == HOTKEY:
        title = f"Хоткей: {hotkey_text(p) or 'не задано'}"
    elif t == STREAMDECK:
        title = f"Stream Deck: яркость {p.get('percent', 0)}%"
    elif t == PRIMARY_MONITOR:
        title = f"Сделать основным: {monitor_text(p.get('monitor')) or 'не выбрано'}"
    elif t == COMMAND:
        title = f"Командная строка: {command_text(p) or 'не задана'}"
        if p.get("mode") == "silent":
            # Помечаем не тот режим, что по умолчанию: иначе пометка стояла бы
            # почти у каждого шага и ничего не различала.
            title = f"{title} (без оболочки)"
    elif t == WALLPAPER:
        if p.get("mode") == "restore":
            title = "Обои: вернуть запомненные"
        elif p.get("mode") == "color":
            title = f"Обои: сплошной цвет {color_text(p.get('color'))}"
        else:
            name = os.path.basename(p.get("path") or "") or "не задано"
            fit = WALLPAPER_FITS.get(p.get("fit"), "")
            title = f"Обои: {name}" + (f", {fit.lower()}" if fit else "")
    else:
        title = TYPE_NAMES.get(t) or f"Неизвестный шаг: {t or 'без типа'}"

    comment = (step.get("comment") or "").strip()
    return f"{title} — {comment}" if comment else title


def default_workdir(script_path):
    """Папка, в которой запустится команда, если своя не задана.

    У сохранённого сценария — его собственная: рядом с ним обычно и лежит
    то, что команда трогает. У несохранённого папки нет, и брать текущую
    нельзя: она досталась программе от того, кто её запустил, — у собранной
    это папка exe, у запуска из PyCharm папка проекта. Берём домашнюю, как
    свежеоткрытая командная строка.
    """
    if script_path:
        return os.path.dirname(os.path.abspath(script_path))
    return os.path.expanduser("~")


# Номер значка в SHELL32.dll — для шагов, у которых своей программы нет.
# Чего нет в списке, тот остаётся без значка. Номера у разных версий Windows
# разъезжаются, так что на чужой машине значки могут оказаться не те.
STEP_SHELL_ICONS = {
    LAUNCH: 0,      # программа не задана
    CLOSE: 0,       # и здесь тоже
    WINDOW: 87,
    PAUSE: 239,
    COPY: 132,
    WALLPAPER: 127,
    PRIMARY_MONITOR: 34,
    HOTKEY: 263,
    STREAMDECK: 130,
    # У командной строки номера нет намеренно: там показывается значок cmd
    # или PowerShell, и он говорит больше любого системного.
}


def step_icon_source(step):
    """Файл, чей значок представляет шаг: путь к программе или имя exe.

    Пусто там, где приложения нет вовсе — у паузы, обоев, монитора. Ядро
    только называет источник; искать файл и рисовать значок — дело интерфейса.
    """
    t = step.get("type")
    p = step.get("params") or {}

    if t == LAUNCH:
        return (p.get("path") or "").strip()

    if t in (CLOSE, WINDOW, HOTKEY):
        # У алиаса своего файла нет: он ссылается на шаг запуска, а какой
        # именно — знает сценарий, не отдельный шаг.
        if p.get("target_kind") == "exe":
            return (p.get("target") or "").strip()
        return ""

    if t == COMMAND:
        return "powershell.exe" if p.get("shell") == "powershell" else "cmd.exe"

    return ""


def command_text(params, limit=36):
    """Первая строка команды для названия шага.

    Команда бывает многострочной и длинной, а в списке шагов есть только
    одна строка — поэтому берём первую и подрезаем. Многоточие ставим
    и когда строк больше одной: иначе два похожих шага неразличимы.
    """
    lines = (params.get("command") or "").strip().splitlines()
    if not lines:
        return ""
    first = lines[0].strip()
    if len(first) > limit:
        return first[:limit].rstrip() + "…"
    return first + "…" if len(lines) > 1 else first


def resource_path(name):
    """Путь к файлу, лежащему рядом с программой.

    В сборке --onefile PyInstaller распаковывает вложенные файлы во временную
    папку и кладёт её путь в sys._MEIPASS. Из исходников это просто папка
    проекта.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def icon_path():
    return resource_path(ICON_FILE)


def plural(count, one, few, many):
    """Русское окончание по числу: 1 шаг, 2 шага, 5 шагов."""
    tail = abs(count) % 100
    if 11 <= tail <= 14:
        return many
    tail %= 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def steps_word(count):
    return f"{count} {plural(count, 'шаг', 'шага', 'шагов')}"


def processes_word(count):
    return f"{count} {plural(count, 'процесс', 'процесса', 'процессов')}"


def hotkey_text(params):
    parts = []
    for flag, label in (("ctrl", "Ctrl"), ("alt", "Alt"), ("shift", "Shift"), ("win", "Win")):
        if params.get(flag):
            parts.append(label)
    if params.get("key"):
        parts.append(params["key"])
    return "+".join(parts)


def load_script(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("файл не похож на сценарий: ожидался объект JSON")

    script = new_script()
    script.update(data)

    steps = script.get("steps")
    if not isinstance(steps, list):
        raise ValueError("в файле нет списка шагов")

    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise ValueError(f"шаг {index} записан неверно: ожидался объект JSON")

        step.setdefault("enabled", True)
        step.setdefault("ignore_error", False)
        step.setdefault("comment", "")
        step.setdefault("id", uuid.uuid4().hex[:8])

        step_type = step.get("type")

        if step_type not in KNOWN_TYPES:
            # Параметры не трогаем: сохранение должно вернуть шаг в файл
            # ровно таким, каким он пришёл. Выполняться он не будет.
            step["enabled"] = False
            if not isinstance(step.get("params"), dict):
                step["params"] = {}
            continue

        defaults = json.loads(json.dumps(DEFAULT_PARAMS[step_type]))
        if isinstance(step.get("params"), dict):
            defaults.update(step["params"])
        step["params"] = defaults

        if step_type == WINDOW:
            _migrate_window(step["params"])
        if step_type == COMMAND:
            _migrate_command(step["params"])

    return script


def _migrate_command(params):
    """Раньше режим назывался «тихо, дождаться»: ожидание было его частью.

    Теперь ожидание — отдельная галка, а режим отвечает только за окно.
    """
    if params.get("mode") == "wait":
        params["mode"] = "silent"
        params["wait"] = True


# Раньше «спрятать окно» и «нажать на крестик» были двумя отдельными
# действиями. Теперь это одно «Свернуть в трей» со способом на выбор —
# старые файлы переводим при чтении, чтобы не переделывать их руками.
LEGACY_TRAY_ACTIONS = ("hide", "close")


def _migrate_window(params):
    if params.get("action") in LEGACY_TRAY_ACTIONS:
        params["tray_mode"] = params["action"]
        params["action"] = "tray"


def unknown_steps(script):
    """Шаги с типом, которого программа не знает: [(номер, тип), ...]."""
    return [
        (index, step.get("type"))
        for index, step in enumerate(script.get("steps", []), 1)
        if step.get("type") not in KNOWN_TYPES
    ]


def save_script(path, script):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

def copy_step(step):
    clone = json.loads(json.dumps(step))
    clone["id"] = uuid.uuid4().hex[:8]
    # Комментарий описывает конкретный шаг — у копии он почти всегда врёт.
    clone["comment"] = ""
    return clone


# Метка своего содержимого в буфере обмена. Буфер один на всю систему,
# и туда попадает что угодно, — по ней отличаем свой шаг от чужого текста.
CLIP_FORMAT = "automaticsic-step"


def step_to_text(step):
    """Шаг в виде текста для буфера обмена.

    Через буфер шаг переезжает в другое окно программы: у каждого окна свой
    процесс, и общей памяти между ними нет. Заодно таким текстом можно
    просто поделиться — он читаемый.
    """
    return json.dumps(
        {"format": CLIP_FORMAT, "version": VERSION, "step": copy_step(step)},
        ensure_ascii=False,
        indent=2,
    )


def step_from_text(text):
    """Шаг из текста буфера обмена. None, если там не наш шаг."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None

    if isinstance(data, dict) and data.get("format") == CLIP_FORMAT:
        data = data.get("step")

    if not isinstance(data, dict) or data.get("type") not in KNOWN_TYPES:
        return None

    # Собираем от значений по умолчанию: в чужом тексте может не быть
    # половины полей, а лишние нам ни к чему.
    step = new_step(data["type"])
    step["enabled"] = bool(data.get("enabled", True))
    step["ignore_error"] = bool(data.get("ignore_error", step["ignore_error"]))

    params = data.get("params")
    if isinstance(params, dict):
        step["params"].update(params)
        if step["type"] == WINDOW:
            _migrate_window(step["params"])

    return step


PATH_LIKE = {LAUNCH: "path", CLOSE: "target", WINDOW: "target", HOTKEY: "target"}


def change_type(step, new_type):
    old_type = step["type"]
    if old_type == new_type:
        return step

    old = step["params"]
    fresh = new_step(new_type)
    new = fresh["params"]

    old_key = PATH_LIKE.get(old_type)
    new_key = PATH_LIKE.get(new_type)
    if old_key and new_key and old.get(old_key):
        value = old[old_key]
        if new_key == "target" and old_key == "path":
            value = os.path.basename(value)
        new[new_key] = value

    for key in ("title_contains", "target_kind", "alias"):
        if key in old and key in new:
            new[key] = old[key]

    if new_type in (CLOSE, WINDOW) and new.get("target_kind") == "active":
        new["target_kind"] = "exe"

    step["type"] = new_type
    step["params"] = new
    return step