import os
import shutil
import subprocess
import tempfile
import time

import psutil

import model
import settings
import streamdeck
import winapi



class StepError(Exception):
    pass


class Context:
    def __init__(self, script, script_path=None, should_stop=None):
        self.script = script
        self.script_path = script_path
        # Функция «пора остановиться?». Её передаёт редактор; ядро про Qt
        # ничего не знает. При двойном клике по файлу её просто нет.
        self.should_stop = should_stop
        self.aliases = {}
        self.alias_exe = dict(script.get("alias_exe") or {})

        # Шаги запуска в открытом сценарии свежее сохранённой карты — они её перекрывают.
        for step in script.get("steps", []):
            if step.get("type") != model.LAUNCH:
                continue
            params = step.get("params") or {}
            alias = (params.get("alias") or "").strip()
            path = (params.get("path") or "").strip()
            if alias and path:
                self.alias_exe[alias] = path

    def resolve_path(self, raw):
        value = os.path.expandvars(raw or "").strip().strip('"')
        if not value:
            raise StepError("путь не задан")
        return value

    def remember(self, alias, pid, exe_path):
        if alias:
            self.aliases[alias] = pid
            self.alias_exe[alias] = exe_path

    def stop_requested(self):
        return bool(self.should_stop and self.should_stop())


def do_pause(step, ctx):
    ms = step["params"].get("ms", 0)
    if ms < 0:
        raise StepError("отрицательное время паузы")

    # Спим короткими кусками: длинную паузу иначе не прервать, а именно
    # на ней чаще всего и хочется нажать «Прервать».
    left = ms / 1000.0
    while left > 0:
        if ctx.stop_requested():
            return "пауза прервана"
        chunk = min(0.05, left)
        time.sleep(chunk)
        left -= chunk

    return f"ждали {ms} мс"


def do_copy(step, ctx):
    src = ctx.resolve_path(step["params"].get("src"))
    dst = ctx.resolve_path(step["params"].get("dst"))

    if not os.path.isfile(src):
        raise StepError(f"файл-источник не найден: {src}")

    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))

    dst_dir = os.path.dirname(dst)
    if dst_dir and not os.path.isdir(dst_dir):
        os.makedirs(dst_dir, exist_ok=True)

    try:
        shutil.copy2(src, dst)
    except PermissionError:
        raise StepError(f"нет доступа к файлу: {dst}")
    except OSError as e:
        raise StepError(f"ошибка копирования: {e}")

    return f"скопировано в {dst}"


def find_pids(ctx, target_kind, target):
    if target_kind == "alias":
        pid = ctx.aliases.get(target)
        if not pid:
            exe = ctx.alias_exe.get(target)
            if exe:
                return find_pids(ctx, "exe", exe)
            raise StepError(f"алиас «{target}» не запускался в этой сессии")
        return [pid] if psutil.pid_exists(pid) else []

    name = os.path.basename(target or "").strip().lower()
    if not name:
        raise StepError("не задана целевая программа")

    found = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if (proc.info["name"] or "").lower() != name:
                continue
            found.append(proc.info["pid"])
            # Раз процесс в руках, путь у него есть. Запоминаем: потом
            # по этому имени найдётся значок и у закрытой программы.
            settings.remember_exe(name, proc.exe())
        except psutil.Error:
            continue
    return found


def find_windows(ctx, params, include_hidden=False):
    pids = find_pids(ctx, params.get("target_kind", "exe"), params.get("target"))
    if not pids:
        return []

    hwnds = []
    for pid in pids:
        hwnds.extend(winapi.windows_of_pid(pid, include_hidden=include_hidden))

    return winapi.filter_by_title(hwnds, params.get("title_contains"))


def _window_refused(hwnd, action):
    """Почему окно не послушалось — по возможности с настоящей причиной."""
    pid = winapi.pid_of_window(hwnd)
    if pid and winapi.higher_integrity(pid):
        return (
            "окно не поддалось: программа запущена от администратора, "
            "а Automaticsic нет"
        )
    if action == "close":
        return (
            "крестик нажат, но окно осталось: программа могла спросить "
            "подтверждение или не ответила вовремя"
        )
    return "окно не поддалось: команда отправлена, состояние не изменилось"


WINDOW_OUTCOMES = {
    "maximize": "развёрнуто на весь экран",
    "restore": "восстановлен обычный размер",
    "foreground": "на переднем плане",
    "minimize": "свёрнуто в панель задач",
    "hide": "спрятано мимо программы",
    "show": "показано",
}


def _move_to_monitor(hwnd, target):
    """Переносит окно на выбранный монитор. Текст для лога или пустая строка.

    Ошибку не глотаем: если человек указал второй монитор, а его нет,
    шаг должен об этом сказать, а не молча оставить окно на месте.
    """
    if not target:
        return ""

    monitor = winapi.find_monitor(target)
    if monitor is None:
        raise StepError(
            f"{model.monitor_text(target)} не найден: "
            f"подключено экранов — {len(winapi.monitors())}"
        )

    winapi.move_to_monitor(hwnd, monitor)

    # Переезд между экранами с разным масштабом программа доигрывает сама:
    # ловит смену DPI и подгоняет размер. Даём ей договорить и смотрим,
    # где окно в итоге оказалось.
    for attempt in range(3):
        landed = winapi.monitor_of_window(hwnd)
        if landed is None or landed["index"] == monitor["index"]:
            return f"монитор {monitor['index']}"
        time.sleep(0.15)

    raise StepError(
        f"окно не переехало на монитор {monitor['index']}: "
        f"осталось на мониторе {landed['index']}"
    )


def _window_outcome(hwnd, action):
    """Чем всё кончилось — короткой строкой для лога."""
    if action != "close":
        return WINDOW_OUTCOMES.get(action, "готово")

    # Крестик — единственное действие с разным исходом: одни программы
    # прячут окно в свой трей, другие закрываются насовсем. Разница важная,
    # поэтому смотрим, осталось ли окно живо.
    if winapi.window_exists(hwnd):
        return "крестик нажат, программа убрала окно в трей"
    return "крестик нажат, программа закрылась"


def do_window(step, ctx):
    p = step["params"]
    action = p.get("action")

    # «Свернуть в трей» — это одно действие для пользователя, но два разных
    # способа внутри: попросить программу убраться самой или спрятать окно
    # мимо неё. Ниже по коду ходят уже конкретные способы.
    if action == "tray":
        action = p.get("tray_mode") or "close"

    include_hidden = action in ("show", "foreground", "maximize", "restore")

    hwnds = find_windows(ctx, p, include_hidden=include_hidden)
    if not hwnds:
        raise StepError("окно не найдено")

    hwnd = hwnds[0]
    title = winapi.window_title(hwnd) or hwnd

    # Сначала переносим, потом действуем: «развернуть» должно развернуть
    # уже на целевом экране, а не на прежнем.
    moved = ""
    if action in model.MONITOR_ACTIONS:
        moved = _move_to_monitor(hwnd, p.get("monitor"))

    if action == "monitor":
        # Самостоятельное действие: только перенос, состояние окна не трогаем.
        if not moved:
            raise StepError("монитор не выбран")
        return f"{title}: перенесено на {moved}"

    if action == "foreground":
        winapi.apply_show(hwnd, "show")
        winapi.bring_to_front(hwnd)
    elif not winapi.apply_show(hwnd, action):
        raise StepError(f"неизвестное действие с окном: {action}")

    # Windows на такие команды не отвечает отказом: она молча их проглатывает,
    # если прав не хватает или окно решило иначе. Проверяем результат сами,
    # иначе шаг рапортует об успехе, а на экране ничего не поменялось.
    if not winapi.took_effect(hwnd, action):
        raise StepError(f"{title}: {_window_refused(hwnd, action)}")

    outcome = _window_outcome(hwnd, action)
    return f"{title}: {outcome}, {moved}" if moved else f"{title}: {outcome}"


def do_hotkey(step, ctx):
    p = step["params"]
    resolved = winapi.key_to_vk(p.get("key"))
    if resolved is None:
        raise StepError(f"неизвестная клавиша: {p.get('key') or 'не задана'}")
    vk_key, implied_mods = resolved

    where = "активное окно"

    if p.get("target_kind") != "active":
        hwnds = find_windows(ctx, p)
        if not hwnds:
            raise StepError("целевое окно не найдено")
        winapi.bring_to_front(hwnds[0])
        time.sleep(0.15)
        where = winapi.window_title(hwnds[0])

    vk_list = [winapi.VK_MODIFIERS[flag] for flag in ("ctrl", "alt", "shift", "win") if p.get(flag)]

    # Символы вроде «?» требуют Shift на текущей раскладке — добавляем,
    # если пользователь не поставил галочку сам.
    for vk in implied_mods:
        if vk not in vk_list:
            vk_list.append(vk)

    vk_list.append(vk_key)
    winapi.send_hotkey(vk_list)

    return f"{model.hotkey_text(p)} отправлено в {where}"


def _start(p, path):
    """Запуск с человеческим текстом ошибки вместо голого OSError."""
    try:
        return winapi.shell_launch(
            path,
            p.get("show", "normal"),
            p.get("args", ""),
        )
    except OSError as e:
        raise StepError(str(e))


# Как «Запустить как» переводится в действие с уже появившимся окном.
# «Обычное окно» отдельного действия не требует.
SHOW_TO_ACTION = {"minimized": "minimize", "maximized": "maximize"}

SHOW_FAILED = {
    "minimize": "свернуть не удалось",
    "maximize": "развернуть не удалось",
}


def _force_show_state(hwnd, action):
    """Доводит окно до нужного состояния своими руками.

    То, что просят у ShellExecute, — не команда, а пожелание: оно доезжает
    до программы в STARTUPINFO, и та вольна его проигнорировать. Почти всё
    современное (Qt, Chromium, Electron) так и делает — показывает окно
    как ему удобно. Поэтому дожимаем сами, уже по факту появления окна.
    """
    if winapi.took_effect(hwnd, action, 0):
        return True

    # Окно только что создано, и программа ещё доводит его до ума: ставит
    # размер, восстанавливает прошлую позицию, показывает поверх. Сразу
    # после появления команда часто теряется, поэтому пробуем несколько раз,
    # давая программе договорить.
    for delay in (0.2, 0.5, 1.0):
        time.sleep(delay)
        winapi.apply_show(hwnd, action)
        if winapi.took_effect(hwnd, action, 400):
            return True

    return False


def _launch_address(p, path):
    """Запуск того, у чего нет своего exe: интернет-ярлык или адрес схемы.

    Ярлык Steam — это файл .url со строкой steam://rungameid/…, и игру
    по нему запускаем не мы, а сам Steam. Своего процесса у шага при этом
    нет: ни окна дождаться, ни на монитор положить, ни алиас запомнить.
    Пишем об этом в лог — молча проглоченные настройки хуже неработающих.
    """
    shortcut = winapi.is_url_shortcut(path)
    if shortcut and not os.path.isfile(path):
        raise StepError(f"файл не найден: {path}")

    # Ярлык открываем файлом, как двойным кликом. Адрес внутри читаем только
    # затем, чтобы в логе было видно, что именно запустилось.
    address = (winapi.read_url_shortcut(path) if shortcut else path) or path

    try:
        winapi.shell_open(path, p.get("show", "normal"))
    except OSError as e:
        raise StepError(str(e))

    skipped = []
    if p.get("monitor"):
        skipped.append("монитор")
    if SHOW_TO_ACTION.get(p.get("show", "normal")):
        skipped.append("«запустить как»")
    if (p.get("alias") or "").strip():
        skipped.append("алиас")

    note = f"открыто: {address}"
    if skipped:
        note += f"; следить не за чем, {', '.join(skipped)} не применяется"
    return note


def do_launch(step, ctx):
    p = step["params"]
    path = ctx.resolve_path(p.get("path"))

    # Адрес схемы и интернет-ярлык — не программа: ни пути к exe, ни процесса.
    if winapi.is_uri(path) or winapi.is_url_shortcut(path):
        return _launch_address(p, path)

    if not os.path.exists(path):
        raise StepError(f"файл не найден: {path}")

    # Для ярлыка искать надо процесс цели, а не «что-то.lnk».
    target = winapi.resolve_target(path)
    exe_name = os.path.basename(target)
    # Запускаем по полному пути — значит знаем, где программа лежит.
    # Потом по этому имени найдётся её значок в шаге закрытия.
    settings.remember_exe(exe_name, target)
    alias = p.get("alias") or ""

    if p.get("if_running") in ("switch", "skip"):
        running = find_pids(ctx, "exe", exe_name)
        if running:
            ctx.remember(alias, running[0], path)
            if p.get("if_running") == "skip":
                return f"уже запущено (PID {running[0]}), пропуск"

            hwnds = winapi.windows_of_pid(running[0], include_hidden=True)
            if hwnds:
                winapi.apply_show(hwnds[0], "show")
                winapi.bring_to_front(hwnds[0])
                return f"уже запущено, переключились (PID {running[0]})"

            _start(p, path)
            hwnd, owner = winapi.wait_for_window(
                running[0], p.get("wait_timeout_ms", 3000), exe_name=exe_name.lower()
            )
            if hwnd:
                ctx.remember(alias, owner, path)
                return f"окна не было, повторный запуск поднял окно (PID {owner})"
            return f"уже запущено (PID {running[0]}), окно поднять не удалось"

    pid = _start(p, path)
    if not pid:
        raise StepError(f"не удалось запустить: {path}")

    ctx.remember(alias, pid, path)

    action = SHOW_TO_ACTION.get(p.get("show", "normal"))
    monitor = p.get("monitor") or ""

    # Разложить окно можно только когда оно есть, поэтому при таком запуске
    # ждём его и без галочки «Дождаться появления окна».
    if not p.get("wait_window", True) and not action and not monitor:
        return f"PID {pid}"

    timeout = p.get("wait_timeout_ms", 3000)
    hwnd, owner = winapi.wait_for_window(pid, timeout, exe_name=exe_name.lower())
    if hwnd is None:
        return f"PID {pid}, окно не появилось за {timeout} мс"

    where = f"PID {pid}, окно готово"
    if owner != pid:
        ctx.remember(alias, owner, path)
        where = f"PID {pid}, окно у PID {owner}"

    notes = []

    # Программа стартовала — это главное, поэтому дальше не ошибки, а пометки.
    if monitor:
        try:
            notes.append(_move_to_monitor(hwnd, monitor))
        except StepError as e:
            notes.append(str(e))

    if action and not _force_show_state(hwnd, action):
        notes.append(SHOW_FAILED[action])

    return ", ".join([where] + [note for note in notes if note])



def _script_path(step, shell):
    """Временный скрипт шага — с постоянным именем, по id шага.

    Постоянное имя, а не случайное: иначе в %TEMP% копился бы файл на каждый
    запуск. Удалить его сразу нельзя — cmd читает .bat по ходу выполнения,
    и у режима «в окне» скрипт нужен ещё долго после нашего ухода.
    """
    folder = os.path.join(tempfile.gettempdir(), model.APP_NAME)
    os.makedirs(folder, exist_ok=True)
    name = (step.get("id") or "step") + winapi.script_suffix(shell)
    return os.path.join(folder, name)


def _output_block(text, limit=None):
    """Вывод команды — блоком с отступом под строкой лога.

    Отступ не украшение: строка лога начинается с времени и номера шага,
    а продолжения — нет. Без сдвига вправо вывод команды не отличить
    от обычных записей сценария.
    """
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    if not lines:
        return ""

    note = ""
    if limit and len(lines) > limit:
        lines = lines[-limit:]
        note = "    …показан только конец вывода"

    block = "\n".join("    " + l for l in lines)
    return f"{block}\n{note}" if note else block


def _kill_tree(pid):
    try:
        parent = psutil.Process(pid)
    except psutil.Error:
        return
    # Убиваем детей первыми: cmd.exe уйдёт, а запущенное им останется висеть.
    try:
        children = parent.children(recursive=True)
    except psutil.Error:
        children = []
    for proc in children + [parent]:
        try:
            proc.kill()
        except psutil.Error:
            pass


def do_command(step, ctx):
    p = step["params"]
    shell = p.get("shell", "cmd")
    command = (p.get("command") or "").strip()
    if not command:
        raise StepError("команда не задана")

    work_dir = os.path.expandvars((p.get("workdir") or "").strip().strip('"'))
    if work_dir and not os.path.isdir(work_dir):
        raise StepError(f"рабочая папка не найдена: {work_dir}")
    if not work_dir:
        work_dir = model.default_workdir(ctx.script_path)

    script = _script_path(step, shell)
    try:
        with open(script, "w", encoding=winapi.script_encoding(shell),
                  errors="replace", newline="") as f:
            f.write(winapi.script_body(shell, command))
    except OSError as e:
        raise StepError(f"не удалось подготовить команду: {e}")

    window = p.get("mode") == "window"
    argv = winapi.shell_command(shell, script, keep_open=window)

    if window:
        try:
            winapi.start_detached(argv, work_dir, winapi.CREATE_NEW_CONSOLE)
        except OSError as e:
            raise StepError(f"не удалось открыть окно: {e}")
        return f"окно открыто: {model.SHELLS.get(shell, shell)}"

    if not p.get("wait", True):
        try:
            winapi.start_detached(argv, work_dir, winapi.CREATE_NO_WINDOW)
        except OSError as e:
            raise StepError(f"не удалось выполнить команду: {e}")
        return "команда запущена, ждать не стали"

    return _run_and_wait(step, ctx, argv, work_dir, script)


def _run_and_wait(step, ctx, argv, work_dir, script):
    timeout = step["params"].get("timeout_ms", 10000) / 1000.0
    out_path = os.path.splitext(script)[0] + ".out"

    try:
        out = open(out_path, "wb")
    except OSError as e:
        raise StepError(f"не удалось подготовить команду: {e}")

    # Вывод пишем в файл, а не в канал: канал на 64 КБ переполнится и команда
    # встанет намертво, дожидаясь, пока её кто-нибудь прочитает.
    try:
        with out:
            proc = subprocess.Popen(
                argv,
                cwd=work_dir or None,
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                creationflags=winapi.CREATE_NO_WINDOW,
            )
    except OSError as e:
        raise StepError(f"не удалось выполнить команду: {e}")

    deadline = time.time() + timeout
    while proc.poll() is None:
        if ctx.stop_requested():
            _kill_tree(proc.pid)
            return "команда прервана"
        if time.time() > deadline:
            _kill_tree(proc.pid)
            raise StepError(f"команда не уложилась в {int(timeout)} с")
        time.sleep(0.05)

    # Вывод читаем, только когда он кому-то нужен: при удачном молчаливом
    # выполнении он никого не интересует, а у иной команды его мегабайты.
    failed = proc.returncode != 0
    asked = bool(step["params"].get("log_output"))
    if not failed and not asked:
        # Про нулевой код в лог не пишем: строка «код 0» у каждой команды —
        # это шум. Молчание и значит, что всё прошло.
        return ""

    try:
        with open(out_path, "rb") as f:
            raw = f.read()
    except OSError:
        raw = b""
    text = raw.decode(winapi.console_encoding(), errors="replace")

    if failed:
        # Вывод здесь не просили, он приложен к ошибке — хватит конца.
        # А если просили, отдаём целиком: за этим и просили.
        block = _output_block(text, limit=None if asked else 15)
        message = f"команда вернула код {proc.returncode}"
        raise StepError(f"{message}\n{block}" if block else message)

    block = _output_block(text)
    return f"вывод команды:\n{block}" if block else "команда ничего не вывела"


def _end_session(ctx, pids, timeout):
    """Выход, как при выключении Windows.

    Ничего не убиваем: если программа не вышла — это ошибка шага, а не повод
    доламывать. Смысл способа ровно в том, чтобы она прибралась сама.

    Дочерние процессы, если их велено закрывать, получают ту же просьбу,
    а не нож: настоящее выключение системы тоже спрашивает каждого.
    """
    delivered = 0
    for pid in pids:
        for hwnd in winapi.all_windows_of_pid(pid):
            if winapi.end_session(hwnd):
                delivered += 1

    if not delivered:
        raise StepError(
            "окна не приняли сообщение о выходе: программа запущена "
            "с правами выше наших"
        )

    deadline = time.time() + timeout
    while time.time() < deadline:
        if ctx.stop_requested():
            return "ожидание выхода прервано"
        left = [pid for pid in pids if psutil.pid_exists(pid)]
        if not left:
            return f"вышло по-хорошему: {model.processes_word(len(pids))}"
        time.sleep(0.1)

    left = [pid for pid in pids if psutil.pid_exists(pid)]
    raise StepError(
        f"не вышло за {int(timeout)} с: {model.processes_word(len(left))}"
    )


def do_close(step, ctx):
    p = step["params"]
    pids = find_pids(ctx, p.get("target_kind", "exe"), p.get("target"))
    if not pids:
        return "процесс не найден, закрывать нечего"

    mode = p.get("mode", "soft_hard")
    timeout = p.get("timeout_ms", 5000) / 1000.0
    kill_children = p.get("kill_children", True)

    targets = []
    for pid in pids:
        try:
            proc = psutil.Process(pid)
        except psutil.NoSuchProcess:
            continue
        targets.append(proc)
        if kill_children:
            try:
                targets.extend(proc.children(recursive=True))
            except psutil.Error:
                pass

    if not targets:
        return "процесс уже завершён"


    if mode == "session":
        # Дочерние тоже просим, если галка стоит: в targets они уже собраны.
        return _end_session(ctx, [proc.pid for proc in targets], timeout)

    if mode in ("soft", "soft_hard"):
        for pid in pids:
            for hwnd in winapi.windows_of_pid(pid):
                winapi.close_window(hwnd)

        # Не ждать разрешено только в «Мягко»: в «Мягко, затем жёстко»
        # пропуск ожидания превратил бы шаг в «Сразу жёстко».
        if mode == "soft" and not p.get("wait_close", True):
            return f"отправлено закрытие: {model.processes_word(len(targets))}, ждать не стали"

        gone, alive = psutil.wait_procs(targets, timeout=timeout)
        if not alive:
            return f"закрыто мягко: {model.processes_word(len(gone))}"
        if mode == "soft":
            raise StepError(f"не закрылось за {int(timeout)} с: {model.processes_word(len(alive))}")
    else:
        alive = targets

    denied = False
    for proc in alive:
        try:
            proc.kill()
        except psutil.AccessDenied:
            denied = True
        except psutil.Error:
            pass

    gone, still = psutil.wait_procs(alive, timeout=3)
    if still:
        if denied:
            raise StepError(
                "нет прав завершить процесс: он запущен от администратора, "
                "а Automaticsic нет"
            )
        raise StepError(f"не удалось завершить: {model.processes_word(len(still))}")

    return f"завершено принудительно: {model.processes_word(len(gone))}"


def _same_wallpaper(state, path, fit, color):
    """Стоит ли на столе ровно то, что шаг собирается поставить."""
    if path:
        if not state["path"]:
            return False
        here = os.path.normcase(os.path.abspath(state["path"]))
        there = os.path.normcase(os.path.abspath(path))
        return here == there and state["fit"] == fit
    return (not state["path"]
            and model.parse_color(state["color"]) == model.parse_color(color))


def _remember_wallpaper(path="", fit="", color=""):
    """Записывает нынешние обои, чтобы потом было куда вернуться.

    Кладём в настройки программы, а не в сценарий: вернуть их может другой
    сценарий, запущенный хоть через неделю, — в файле шага такому месту
    взяться неоткуда.
    """
    try:
        state = winapi.current_wallpaper()
    except OSError as e:
        return f", запомнить прежние не вышло: {e}"

    # Если на столе уже ровно то, что шаг ставит, запоминать нечего. Иначе
    # второй запуск того же сценария запомнил бы сам себя, и возвращаться
    # стало бы некуда.
    if _same_wallpaper(state, path, fit, color):
        return ", запоминать нечего: эти обои уже стоят"

    settings.set_value("saved_wallpaper", state)
    if state["path"]:
        return f", прежние запомнены ({os.path.basename(state['path'])})"
    return f", прежним запомнен цвет {state['color']}"


def _restore_wallpaper():
    saved = settings.get("saved_wallpaper")
    if not isinstance(saved, dict):
        raise StepError("возвращать нечего: обои ещё ни разу не запоминались")

    path = saved.get("path") or ""
    if path:
        if not os.path.isfile(path):
            raise StepError(f"запомненный файл пропал: {path}")
        try:
            winapi.set_wallpaper_image(path, saved.get("fit", "fill"))
        except OSError as e:
            raise StepError(str(e))
        return f"вернули {os.path.basename(path)}"

    rgb = model.parse_color(saved.get("color"))
    if rgb is None:
        raise StepError("в запомненном состоянии нет ни картинки, ни цвета")
    try:
        winapi.set_wallpaper_color(rgb)
    except OSError as e:
        raise StepError(str(e))
    return f"вернули сплошной цвет {model.color_text(saved.get('color'))}"


def do_wallpaper(step, ctx):
    p = step["params"]
    mode = p.get("mode", "image")

    if mode == "restore":
        return _restore_wallpaper()

    remember = bool(p.get("remember"))

    if mode == "color":
        rgb = model.parse_color(p.get("color"))
        if rgb is None:
            raise StepError(f"непонятный цвет: {p.get('color') or 'не задан'}")
        # Запоминаем в момент выполнения и до смены — после уже нечего.
        note = _remember_wallpaper(color=p.get("color")) if remember else ""
        try:
            winapi.set_wallpaper_color(rgb)
        except OSError as e:
            raise StepError(str(e))
        return f"сплошной цвет {model.color_text(p.get('color'))}{note}"

    path = ctx.resolve_path(p.get("path"))
    if not os.path.isfile(path):
        raise StepError(f"файл не найден: {path}")

    fit = p.get("fit", "fit")
    note = _remember_wallpaper(path=path, fit=fit) if remember else ""
    try:
        winapi.set_wallpaper_image(path, fit)
    except OSError as e:
        raise StepError(str(e))

    # Не с имени файла: строка лога начинается с заглавной, и «sunset.jpg»
    # превратилось бы в «Sunset.jpg».
    return (f"картинка {os.path.basename(path)}, "
            f"{model.WALLPAPER_FITS.get(fit, fit).lower()}{note}")


def do_primary_monitor(step, ctx):
    target = step["params"].get("monitor") or ""
    if not target:
        raise StepError("монитор не выбран")

    monitor = winapi.find_monitor(target)
    if monitor is None:
        raise StepError(
            f"{model.monitor_text(target)} не найден: "
            f"подключено экранов — {len(winapi.monitors())}"
        )

    # Выбрать уже основной — не бессмыслица, а способ заставить Windows
    # заново применить раскладку: помогает, когда панель задач или обои
    # остались на прежнем экране.
    already = monitor["primary"]

    try:
        winapi.set_primary_monitor(monitor)
    except OSError as e:
        raise StepError(str(e))

    # Раскладка сдвигается целиком, поэтому нумерация слева направо
    # переживает смену — сравнивать номера можно.
    now = next((m for m in winapi.monitors() if m["primary"]), None)
    if now is None or now["index"] != monitor["index"]:
        raise StepError(f"основным монитор {monitor['index']} не стал")

    if already:
        return f"монитор {monitor['index']} и так основной, раскладка переприменена"
    return f"основной монитор — {monitor['index']}"


def do_streamdeck(step, ctx):
    percent = step["params"].get("percent", 50)
    if not isinstance(percent, int) or not 0 <= percent <= 100:
        raise StepError(f"яркость задаётся в процентах, от 0 до 100: {percent}")

    found = streamdeck.devices()
    if not found:
        raise StepError("Stream Deck не найден — проверь, что он подключён")

    done = []
    for device in found:
        if streamdeck.set_brightness(device, percent) and device["name"] not in done:
            done.append(device["name"])

    if not done:
        raise StepError(
            "Stream Deck найден, но команду не принял: скорее всего, "
            "устройство занято программой Elgato Stream Deck"
        )

    return f"{', '.join(done)}: яркость {percent}%"


HANDLERS = {
    model.PAUSE: do_pause,
    model.COPY: do_copy,
    model.WINDOW: do_window,
    model.HOTKEY: do_hotkey,
    model.LAUNCH: do_launch,
    model.CLOSE: do_close,
    model.WALLPAPER: do_wallpaper,
    model.STREAMDECK: do_streamdeck,
    model.PRIMARY_MONITOR: do_primary_monitor,
    model.COMMAND: do_command,
}
