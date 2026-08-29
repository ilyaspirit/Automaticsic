import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QLabel, QLineEdit, QPushButton,
    QFileDialog,
)

import model
import settings
import streamdeck
import winapi
from ui_style import BORDER, CONTROL_TOTAL
from ui_widgets import (
    CheckBox, ComboBox, HotkeyEdit, PathEdit, TextEdit, identify_monitors,
    make_spin, resolve_shortcut, row, set_row_enabled, spin_row, stretch,
)

# Все подписи, какие бывают в панели свойств, включая две общие из редактора.
# Колонка подписей меряется по самой длинной из них и потому одинакова
# на всех шагах — иначе поля разъезжаются при переключении с «Паузы»
# на «Закрытие». Добавляешь новый addRow — впиши подпись сюда.
FORM_LABELS = (
    "Тип шага", "Комментарий",
    "Задержка", "Откуда", "Куда",
    "Программа", "Аргументы", "Запустить как", "Монитор", "Алиас",
    "Если уже запущено", "Ждать не дольше",
    "Как искать", "Куда отправить", "Заголовок содержит",
    "Способ", "Способ сворачивания", "Действие", "Сочетание",
    "Чем заполнить", "Изображение", "Как разместить", "Цвет",
    "Яркость", "Найдено", "Сделать основным",
    "Оболочка", "Команда", "Рабочая папка", "Как выполнить", "Запомнено",
)

SHOW_MODES = [
    ("normal", "Обычное окно"),
    ("maximized", "На весь экран"),
    ("minimized", "Свёрнуто"),
]

IF_RUNNING = [
    ("switch", "Переключиться на окно"),
    ("skip", "Пропустить шаг"),
    ("launch", "Запустить ещё раз"),
]

TARGET_KINDS = [
    ("exe", "По имени программы",
     "Ищем среди запущенных процессов по имени exe — например, notepad.exe."),
    ("alias", "По алиасу шага запуска",
     "Ищем программу, запущенную шагом с таким алиасом. Точнее поиска по\n"
     "имени: если открыто пять окон Chrome, попадём именно в нужное."),
]

ACTIVE_KIND = (
    "active", "Глобально, как с клавиатуры",
    "Клавиши уходят в систему, будто ты нажал их сам. Попадут в то окно,\n"
    "которое активно в этот момент, — обычно его поднял предыдущий шаг.\n"
    "Так же срабатывают и системные сочетания вроде Win+D.",
)


class PropsBuilder:
    def __init__(self, window):
        self.win = window

    def build(self, step_type, params, form):
        builder = getattr(self, f"_{step_type}", None)
        if builder:
            builder(params, form)

    def _browse_button(self, line_edit, kind):
        button = QPushButton("…")
        button.setFixedWidth(36)
        button.clicked.connect(lambda: self._browse(line_edit, kind))
        return button

    def _pause(self, params, form):
        ms = make_spin(0, 3600000, 100)
        self.win.bind_spin(ms, params, "ms")
        form.addRow("Задержка", spin_row(ms))

    def _copy(self, params, form):
        src = PathEdit("path")
        self.win.bind_line(src, params, "src")
        form.addRow("Откуда", row(src, self._browse_button(src, "file")))

        dst = PathEdit("path")
        self.win.bind_line(dst, params, "dst")
        form.addRow("Куда", row(dst, self._browse_button(dst, "save")))

    def _command(self, params, form):
        shell = ComboBox()
        shell_keys = list(model.SHELLS.keys())
        shell.addItems([model.SHELLS[k] for k in shell_keys])
        self.win.bind_combo(shell, params, "shell", shell_keys)
        form.addRow("Оболочка", shell)

        command = TextEdit(rows=4)
        command.setPlaceholderText("ipconfig /all")
        self.win.bind_text(command, params, "command")
        form.addRow("Команда", command)

        workdir = PathEdit("path")
        # В подсказке та папка, где команда запустится на самом деле: от неё
        # зависит, что найдут относительные пути внутри команды.
        workdir.setPlaceholderText(model.default_workdir(self.win.path))
        self.win.bind_line(workdir, params, "workdir")
        form.addRow("Рабочая папка", row(workdir, self._browse_button(workdir, "dir")))

        mode = ComboBox()
        mode_keys = list(model.COMMAND_MODES.keys())
        mode.addItems([model.COMMAND_MODES[k] for k in mode_keys])
        self._hints(mode, mode_keys, model.COMMAND_MODE_HINTS)
        self.win.bind_combo(mode, params, "mode", mode_keys)
        form.addRow("Как выполнить", mode)

        wait = CheckBox("Дождаться завершения")
        self.win.bind_check(wait, params, "wait")
        form.addRow("", wait)

        timeout = make_spin(1, 3600, 10)
        self.win.bind_spin(timeout, params, "timeout_ms", scale=1000)
        timeout_row = spin_row(timeout, step=10, unit_text="с")
        form.addRow("Ждать не дольше", timeout_row)

        log_output = CheckBox("Вывести результат в лог")
        self.win.bind_check(log_output, params, "log_output")
        form.addRow("", log_output)

        hint = QLabel("Лог виден только в редакторе, не при запуске по файлу")
        hint.setStyleSheet("color: palette(mid);")
        hint.setWordWrap(True)
        form.addRow("", hint)

        def update_rows(*_):
            silent = mode_keys[mode.currentIndex()] == "silent"

            # В окне оболочки ждать нечего: оно живёт своей жизнью, а код
            # возврата туда и не доходит. Погашенная галка показывает это
            # честно — снятой, — но сохранённый выбор не трогает.
            set_row_enabled(form, wait, silent)
            self._show_effective(wait, params, "wait", None if silent else False)

            waiting = silent and wait.isChecked()
            set_row_enabled(form, timeout_row, waiting)

            # Вывод читается только у того, чего дождались.
            set_row_enabled(form, log_output, waiting)
            self._show_effective(
                log_output, params, "log_output", None if waiting else False
            )
            set_row_enabled(form, hint, waiting)

        mode.currentIndexChanged.connect(update_rows)
        wait.stateChanged.connect(update_rows)
        update_rows()

    def _primary_monitor(self, params, form):
        form.addRow("Сделать основным", self._monitor_combo(params, choices=False))

        hint = QLabel("Текущий основной тоже подходит: Windows заново применит раскладку")
        hint.setStyleSheet("color: palette(mid);")
        hint.setWordWrap(True)
        form.addRow("", hint)

    def _streamdeck(self, params, form):
        percent = make_spin(0, 100, 5)
        self.win.bind_spin(percent, params, "percent")
        form.addRow("Яркость", spin_row(percent, step=10, unit_text="%"))

        # Что нашлось прямо сейчас: без этой строки непонятно, увидит ли шаг
        # устройство вообще, — а узнать это иначе можно только запуском.
        found = streamdeck.describe()
        status = QLabel(found or "Устройство не найдено")
        status.setStyleSheet("color: palette(mid);")
        form.addRow("Найдено", status)

    def _wallpaper(self, params, form):
        mode = ComboBox()
        keys = list(model.WALLPAPER_MODES)
        mode.addItems([model.WALLPAPER_MODES[k] for k in keys])
        self._hints(mode, keys, model.WALLPAPER_MODE_HINTS)
        self.win.bind_combo(mode, params, "mode", keys)
        form.addRow("Чем заполнить", mode)

        path = PathEdit("path")
        path.setPlaceholderText("jpg, png, bmp или gif")
        self.win.bind_line(path, params, "path")
        path_row = row(path, self._browse_button(path, "image"))
        form.addRow("Изображение", path_row)

        fit = ComboBox()
        fit_keys = list(model.WALLPAPER_FITS)
        fit.addItems([model.WALLPAPER_FITS[k] for k in fit_keys])
        self.win.bind_combo(fit, params, "fit", fit_keys)
        form.addRow("Как разместить", fit)

        color_row = self._color_row(params, "color")
        form.addRow("Цвет", color_row)

        remember = CheckBox("Запомнить прежние обои")
        self.win.bind_check(remember, params, "remember")
        form.addRow("", remember)

        remember_hint = QLabel(
            "Запомненное хранится в настройках программы — вернуть его "
            "сможет любой другой сценарий"
        )
        remember_hint.setStyleSheet("color: palette(mid);")
        remember_hint.setWordWrap(True)
        form.addRow("", remember_hint)

        # Что лежит в памяти прямо сейчас: без этой строки непонятно, есть ли
        # чему возвращаться, — а узнать иначе можно только запуском.
        saved = QLabel(self._saved_wallpaper_text())
        saved.setStyleSheet("color: palette(mid);")
        saved.setWordWrap(True)
        form.addRow("Запомнено", saved)

        # Здесь не гасим, а прячем: изображение, цвет и возврат — не уточнения
        # друг друга, а взаимоисключающие варианты, и половина формы всё время
        # стояла бы серой без пользы.
        def update_rows(*_):
            current = keys[mode.currentIndex()]
            restore = current == "restore"
            form.setRowVisible(path_row, current == "image")
            form.setRowVisible(fit, current == "image")
            form.setRowVisible(color_row, current == "color")
            form.setRowVisible(remember, not restore)
            form.setRowVisible(remember_hint, not restore)
            form.setRowVisible(saved, restore)

        mode.currentIndexChanged.connect(update_rows)
        update_rows()

    @staticmethod
    def _saved_wallpaper_text():
        saved = settings.get("saved_wallpaper")
        if not isinstance(saved, dict):
            return "ничего — ни один шаг ещё не запоминал"
        if saved.get("path"):
            fit = model.WALLPAPER_FITS.get(saved.get("fit"), "")
            name = os.path.basename(saved["path"])
            return f"{name}" + (f", {fit.lower()}" if fit else "")
        return f"сплошной цвет {model.color_text(saved.get('color'))}"

    def _color_row(self, params, key):
        """Образец цвета и кнопка выбора из системной палитры."""
        swatch = QLabel()
        swatch.setFixedSize(72, CONTROL_TOTAL)

        button = QPushButton("Выбрать…")

        def repaint():
            value = params.get(key)
            shown = model.color_text(value) if model.parse_color(value) else "transparent"
            swatch.setStyleSheet(
                f"background: {shown}; border: 1px solid {BORDER}; border-radius: 3px;"
            )
            # Само значение никуда не делось — держим его в подсказке.
            swatch.setToolTip(model.color_text(value))

        def choose():
            value = params.get(key)
            start = QColor(model.color_text(value)) if model.parse_color(value) else QColor(model.DEFAULT_COLOR)
            picked = QColorDialog.getColor(start, self.win, "Цвет рабочего стола")
            if not picked.isValid():
                return
            params[key] = picked.name().upper()
            repaint()
            self.win.touch()

        button.clicked.connect(choose)
        repaint()

        # stretch() съедает свободное место, иначе кнопка растянулась бы
        # на всю оставшуюся ширину строки.
        return row(swatch, button, stretch())

    def _launch(self, params, form):
        path = PathEdit("path")
        self.win.bind_line(path, params, "path")
        pick = QPushButton("Из запущенных")
        pick.clicked.connect(lambda: self.win.pick_process(path, full_path=True))
        form.addRow("Программа", row(path, self._browse_button(path, "exe"), pick))

        args = QLineEdit()
        args.setPlaceholderText("ключи или адрес — как в ярлыке, необязательно")
        self.win.bind_line(args, params, "args")
        form.addRow("Аргументы", args)

        # Ярлык раскладывается надвое: путь сюда, аргументы туда.
        path.args_edit = args

        show = ComboBox()
        show.addItems([label for _, label in SHOW_MODES])
        self.win.bind_combo(show, params, "show", [key for key, _ in SHOW_MODES])
        form.addRow("Запустить как", show)

        monitor = self._monitor_combo(params)
        form.addRow("Монитор", monitor)


        if_running = ComboBox()
        if_running.addItems([label for _, label in IF_RUNNING])
        self.win.bind_combo(if_running, params, "if_running", [key for key, _ in IF_RUNNING])
        form.addRow("Если уже запущено", if_running)

        wait = CheckBox("Дождаться появления окна")
        self.win.bind_check(wait, params, "wait_window")
        form.addRow("", wait)

        timeout = make_spin(1000, 120000, 1000)
        self.win.bind_spin(timeout, params, "wait_timeout_ms")
        timeout_row = spin_row(timeout)
        form.addRow("Ждать не дольше", timeout_row)

        alias = QLineEdit()
        alias.setPlaceholderText("например: np — чтобы ссылаться в других шагах")
        self.win.bind_line(alias, params, "alias")
        form.addRow("Алиас", alias)

        # Ярлык .url (у Steam это адрес steam://rungameid/…) открывает сама
        # Windows: игру запускает Steam, своего процесса у шага нет. Гасим
        # всё, что без процесса не работает, — иначе форма обещает лишнее.
        address_hint = QLabel(
            "Ярлык открывает Windows, программу запускает не шаг — "
            "следить за окном он не может"
        )
        address_hint.setStyleSheet("color: palette(mid);")
        address_hint.setWordWrap(True)
        form.addRow("", address_hint)

        def update_rows(*_):
            text = path.text()
            plain = not (winapi.is_uri(text) or winapi.is_url_shortcut(text))
            for field in (args, show, monitor, if_running, wait, alias):
                set_row_enabled(form, field, plain)
            form.setRowVisible(address_hint, not plain)

            # Разложить окно можно только когда оно появилось. Поэтому, если
            # выбран монитор или запуск свёрнутым либо развёрнутым, шаг ждёт
            # окна независимо от галки — и галка в этом случае стоит и гаснет,
            # а не остаётся снятой, обещая обратное.
            placing = plain and (
                params.get("show", "normal") != "normal"
                or bool(params.get("monitor"))
            )
            wait.setEnabled(plain and not placing)
            self._show_effective(
                wait, params, "wait_window", True if placing else None
            )

            waiting = plain and (placing or wait.isChecked())
            set_row_enabled(form, timeout_row, waiting)

        path.textChanged.connect(update_rows)
        wait.stateChanged.connect(update_rows)
        show.currentIndexChanged.connect(update_rows)
        # У обёртки сигнала нет — подписываемся на сам список внутри неё.
        monitor.combo.currentIndexChanged.connect(update_rows)
        update_rows()

    def _close(self, params, form):
        self._target_rows(form, params, with_title=False)

        mode = ComboBox()
        keys = list(model.CLOSE_MODES.keys())
        mode.addItems([model.CLOSE_MODES[k] for k in keys])
        self._hints(mode, keys, model.CLOSE_MODE_HINTS)
        self.win.bind_combo(mode, params, "mode", keys)
        form.addRow("Способ", mode)

        wait = CheckBox("Дождаться закрытия")
        self.win.bind_check(wait, params, "wait_close")
        form.addRow("", wait)

        timeout = make_spin(500, 60000, 500)
        self.win.bind_spin(timeout, params, "timeout_ms")
        timeout_row = spin_row(timeout)
        form.addRow("Ждать не дольше", timeout_row)

        children = CheckBox("Закрывать дочерние процессы")
        self.win.bind_check(children, params, "kill_children")
        form.addRow("", children)


        def update_wait(*_):
            current = keys[mode.currentIndex()]

            # Ждать закрытия выбирают только в «Мягко». «Мягко, затем жёстко»
            # без ожидания — это и есть «Сразу жёстко», поэтому там ждём
            # обязательно; при выходе как при выключении тоже — весь смысл
            # в том, чтобы программа успела прибраться; а в «Сразу жёстко»
            # ждать нечего.
            wait.setEnabled(current == "soft")
            self._show_effective(
                wait, params, "wait_close",
                None if current == "soft" else current != "hard",
            )

            waiting = (current in ("soft_hard", "session")
                       or (current == "soft" and wait.isChecked()))
            set_row_enabled(form, timeout_row, waiting)

            # Галка работает во всех способах и отвечает на один вопрос:
            # распространять ли действие на дочерние процессы. Как именно
            # закрывать — сказано выше, в «Способе»: где-то завершением,
            # а при выходе как при выключении такой же просьбой выйти.
            # Поэтому подпись у неё одна на все режимы: меняющаяся подпись
            # заставляет перечитывать то, что уже прочёл.

        mode.currentIndexChanged.connect(update_wait)
        wait.stateChanged.connect(update_wait)
        update_wait()

    def _window(self, params, form):
        self._target_rows(form, params, with_title=True)

        action = ComboBox()
        keys = list(model.WINDOW_ACTIONS.keys())
        action.addItems([model.WINDOW_ACTIONS[k] for k in keys])
        self._hints(action, keys, model.WINDOW_ACTION_HINTS)
        self.win.bind_combo(action, params, "action", keys)
        form.addRow("Действие", action)

        tray = ComboBox()
        tray_keys = list(model.TRAY_MODES.keys())
        tray.addItems([model.TRAY_MODES[k] for k in tray_keys])
        self._hints(tray, tray_keys, model.TRAY_MODE_HINTS)
        self.win.bind_combo(tray, params, "tray_mode", tray_keys)
        form.addRow("Способ сворачивания", tray)

        monitor = self._monitor_combo(params)
        form.addRow("Монитор", monitor)

        def update_rows(*_):
            current = keys[action.currentIndex()]

            # Способ сворачивания к остальным действиям отношения не имеет.
            # Показать вместо него «ничего» нельзя — такого варианта нет,
            # поэтому просто гасим.
            set_row_enabled(form, tray, current == "tray")

            # Свёрнутое и спрятанное окно переносить некуда. Погашенный
            # список показывает «Не менять», а не сохранённый номер: иначе
            # он обещал бы перенос, которого не будет.
            places = current in model.MONITOR_ACTIONS
            set_row_enabled(form, monitor, places)
            self._show_effective_choice(
                monitor.combo, params, "monitor", monitor.values,
                None if places else model.MONITOR_KEEP,
            )

        action.currentIndexChanged.connect(update_rows)
        update_rows()

    @staticmethod
    def _show_effective(check, params, key, forced):
        """Показывает в погашенной галке то, что произойдёт на самом деле.

        Погашенная галка, застывшая в прежнем положении, врёт: выглядит
        включённой там, где ничего не включает, и не поймёшь, работает она
        или нет. Поэтому пока галка недоступна, она показывает поведение
        режима, а сохранённое значение при этом не трогает — вернёшь режим,
        вернётся и твой выбор.
        """
        check.blockSignals(True)
        check.setChecked(bool(params.get(key, False)) if forced is None else forced)
        check.blockSignals(False)

    @staticmethod
    def _show_effective_choice(combo, params, key, values, forced):
        """То же, что _show_effective, но для выпадающего списка."""
        value = params.get(key) if forced is None else forced
        if value not in values:
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(values.index(value))
        combo.blockSignals(False)

    @staticmethod
    def _hints(combo, keys, hints):
        """Пояснение к каждому пункту: коротким названием всё не расскажешь."""
        for position, key in enumerate(keys):
            hint = hints.get(key)
            if hint:
                combo.setItemData(position, hint, Qt.ToolTipRole)

    def _monitor_combo(self, params, choices=True):
        """Список мониторов — тот, что подключён прямо сейчас.

        Сценарий могли писать на трёх экранах, а открыть на одном. Тогда
        сохранённый номер остаётся в списке отдельным пунктом: молча заменить
        его на «не менять» значило бы испортить чужой сценарий при первом же
        сохранении.

        choices=False убирает «Не менять» и «Основной»: там, где выбирают,
        какому экрану быть основным, оба пункта — бессмыслица.
        """
        keys = [model.MONITOR_KEEP, model.MONITOR_PRIMARY] if choices else []
        labels = [model.MONITOR_LABELS[k] for k in keys]

        for monitor in winapi.monitors():
            left, top, right, bottom = monitor["rect"]
            mark = ", основной" if monitor["primary"] else ""
            keys.append(str(monitor["index"]))
            labels.append(
                f"Монитор {monitor['index']} — "
                f"{right - left}×{bottom - top}{mark}"
            )

        current = params.get("monitor") or model.MONITOR_KEEP
        if current not in keys:
            keys.append(current)
            labels.append(f"{model.monitor_text(current).capitalize()} — не подключён")

        combo = ComboBox()
        combo.addItems(labels)
        self.win.bind_combo(combo, params, "monitor", keys)

        # Номер экрана в списке ничего не говорит о том, какой он на столе.
        # Кнопка показывает номера прямо на мониторах — как «Определить»
        # в параметрах Windows.
        identify = QPushButton("Определить")
        identify.setToolTip("Показать номер на каждом мониторе")
        identify.clicked.connect(lambda: identify_monitors())

        wrapper = row(combo, identify)
        # Держим список на обёртке: снаружи бывает нужно показать в погашенном
        # виде не сохранённое значение, а то, что произойдёт на самом деле.
        wrapper.combo = combo
        wrapper.values = keys
        return wrapper

    def _hotkey(self, params, form):
        self._target_rows(form, params, with_title=True, allow_active=True,
                          kind_label="Куда отправить")

        combo = HotkeyEdit()
        combo.setText(model.hotkey_text(params))

        clear = QPushButton("Очистить")

        def remember(value):
            params.update(value)
            combo.setText(model.hotkey_text(params))
            self.win.touch()

        def reset():
            params.update({
                "ctrl": False, "alt": False, "shift": False, "win": False, "key": "",
            })
            combo.clear()
            self.win.touch()

        combo.captured.connect(remember)
        clear.clicked.connect(reset)

        form.addRow("Сочетание", row(combo, clear))

    def _target_rows(self, form, params, with_title, allow_active=False,
                     kind_label="Как искать"):
        kinds = list(TARGET_KINDS)
        if allow_active:
            kinds.insert(0, ACTIVE_KIND)
        keys = [key for key, _, _ in kinds]

        kind = ComboBox()
        kind.addItems([label for _, label, _ in kinds])
        # Пояснение к каждому пункту — коротким названием всё не расскажешь.
        for position, (_, _, hint) in enumerate(kinds):
            kind.setItemData(position, hint, Qt.ToolTipRole)
        self.win.bind_combo(kind, params, "target_kind", keys)
        form.addRow(kind_label, kind)

        # Та же связка, что и у шага запуска: поле, обзор по диску,
        # выбор из запущенных. Разница лишь в том, что здесь остаётся
        # имя exe, а не полный путь.
        target = PathEdit("name")
        target.setPlaceholderText("notepad.exe или алиас")
        self.win.bind_line(target, params, "target")
        browse = self._browse_button(target, "exe")
        pick = QPushButton("Из запущенных")
        pick.clicked.connect(lambda: self.win.pick_process(target, full_path=False))
        target_row = row(target, browse, pick)
        form.addRow("Программа", target_row)

        title = None
        if with_title:
            title = QLineEdit()
            title.setPlaceholderText("необязательно, часть заголовка окна")
            self.win.bind_line(title, params, "title_contains")
            form.addRow("Заголовок содержит", title)

        def update_visibility(index):
            active = keys[index] == "active"
            set_row_enabled(form, target_row, not active)
            if title is not None:
                set_row_enabled(form, title, not active)
            # По алиасу в поле имя шага запуска, а не программа — искать
            # его по диску и среди процессов бессмысленно.
            selectable = not active and keys[index] != "alias"
            browse.setEnabled(selectable)
            pick.setEnabled(selectable)

        kind.currentIndexChanged.connect(update_visibility)
        update_visibility(kind.currentIndex())

    def _browse(self, line_edit, kind):
        start = line_edit.text() or ""
        if kind == "save":
            path, _ = QFileDialog.getSaveFileName(self.win, "Выберите файл", start)
        elif kind == "exe":
            path, _ = QFileDialog.getOpenFileName(
                self.win, "Выберите программу", start,
                "Программы и ярлыки (*.exe *.lnk *.url);;Все файлы (*)",
            )
        elif kind == "dir":
            # Отдаёт строку, а не пару: это единственный диалог
            # без фильтра файлов.
            path = QFileDialog.getExistingDirectory(
                self.win, "Выберите папку", start
            )
        elif kind == "image":
            path, _ = QFileDialog.getOpenFileName(
                self.win, "Выберите изображение", start,
                "Изображения (*.jpg *.jpeg *.png *.bmp *.gif);;Все файлы (*)",
            )
        else:
            path, _ = QFileDialog.getOpenFileName(self.win, "Выберите файл", start)
        if not path:
            return
        if kind == "exe" and path.lower().endswith(".lnk"):
            path, arguments = resolve_shortcut(path)
            args_edit = getattr(line_edit, "args_edit", None)
            if arguments and args_edit is not None:
                args_edit.setText(arguments)

        # Поле «по имени программы» хранит только имя exe — как при
        # перетаскивании файла в него.
        if getattr(line_edit, "mode", "path") == "name":
            line_edit.setText(os.path.basename(path))
        else:
            line_edit.setText(os.path.normpath(path))