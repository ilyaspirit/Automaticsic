import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QVBoxLayout, QHBoxLayout, QPushButton, QSplitter, QPlainTextEdit,
    QMenu, QLabel, QFormLayout, QLineEdit,
    QFileDialog, QMessageBox, QToolBar, QToolButton, QSizePolicy,
    QScrollArea,
)

import actions
import install
import model
import runner
import settings
import winapi
from ui_process_picker import ProcessPicker
from ui_props import FORM_LABELS, PropsBuilder
from ui_style import STYLE, apply_light_theme
from ui_widgets import (
    CheckBox, ComboBox, StepDelegate, StepList, align_form_labels,
    combo_header, label_column_width, separator, step_icon,
)


class MainWindow(QMainWindow):
    # Ширина правой колонки. Закреплена, чтобы сплиттер не ездил: у разных
    # шагов панель свойств просит разного места — «Запуску» нужно 534 px,
    # «Паузе» 341, — и без общей ширины список шагов дёргался бы при каждом
    # переключении. Если какому-то шагу не хватит, колонка один раз
    # расширится и такой и останется.
    PROPS_WIDTH = 560

    def __init__(self):
        super().__init__()
        self.script = model.new_script()
        self.path = None
        self.buffer = None
        self.dirty = False
        self._ctx = None
        self._stop_requested = False
        self.elevated = winapi.is_elevated()
        self.props_builder = PropsBuilder(self)
        # Меряем колонку подписей заранее, по всем подписям сразу:
        # иначе она подрастала бы при первом заходе на шаг с длинной.
        label_column_width(FORM_LABELS)

        # Ниже этого форма ломается: правой колонке нужно PROPS_WIDTH
        # плюс полоса прокрутки, левой с рядом кнопок — 359, плюс ручка
        # сплиттера и отступы.
        self.setMinimumSize(960, 700)
        self.resize(1120, 760)
        self._build_ui()
        self._build_toolbar()
        self._build_status_bar()
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self._update_title()
        self._refresh_list()

    # --- построение интерфейса ---

    def _build_ui(self):
        bar = QHBoxLayout()
        self.btn_add = QPushButton("Добавить шаг")
        self.btn_add.clicked.connect(self._show_add_menu)
        self.btn_delete = QPushButton("Удалить шаг")
        self.btn_delete.clicked.connect(self._delete_step)
        self.btn_run_one = QPushButton("Выполнить шаг")
        self.btn_run_one.clicked.connect(self._run_current)
        bar.addWidget(self.btn_add)
        bar.addWidget(self.btn_delete)
        bar.addStretch()
        bar.addWidget(self.btn_run_one)

        self.list = StepList()
        self.list.set_placeholder(self._placeholder_lines())
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.setItemDelegate(StepDelegate(self.list))
        self.list.setMouseTracking(True)
        # Длинное название шага не должно растягивать список: оно обрезается
        # многоточием, а целиком показывается во всплывающей подсказке.
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.model().rowsMoved.connect(self._on_rows_moved)
        self.list.currentRowChanged.connect(self._on_current_changed)

        run_row = QHBoxLayout()
        # Своих отступов у строки нет: сверху воздух даёт шаг левой колонки,
        # снизу — шаг центральной раскладки до лога. Оба по 6, кнопка ровно
        # посередине этого промежутка.
        run_row.setContentsMargins(0, 0, 0, 0)

        self.btn_stop = QPushButton("Прервать выполнение")
        self.btn_stop.clicked.connect(self._request_stop)
        run_row.addWidget(self.btn_stop)

        run_row.addStretch()


        self.btn_run_all = QPushButton("Выполнить всё")
        self.btn_run_all.clicked.connect(self._run_all)
        run_row.addWidget(self.btn_run_all)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addLayout(bar)
        left_layout.addWidget(self.list)
        left_layout.addLayout(run_row)

        self.props = QWidget()
        self.props_layout = QVBoxLayout(self.props)
        self.props_layout.setAlignment(Qt.AlignTop)
        self.props_layout.setContentsMargins(0, 0, 0, 0)

        # Панель свойств живёт в прокрутке. Без неё форма длинного шага
        # не помещалась в правую колонку, когда лог внизу вырастал после
        # выполнения, — и QFormLayout, которому не хватило высоты, сжимал
        # строки: высокое поле команды наезжало на соседнее.
        props_scroll = QScrollArea()
        props_scroll.setWidget(self.props)
        props_scroll.setWidgetResizable(True)
        props_scroll.setFrameShape(QScrollArea.NoFrame)
        props_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Место под полосу прокрутки держим всегда: появляясь и пропадая,
        # она сдвигала бы поля формы туда-сюда.
        self.scrollbar_width = props_scroll.verticalScrollBar().sizeHint().width()

        self.right_column = QWidget()
        self.right_column.setMinimumWidth(self.PROPS_WIDTH + self.scrollbar_width)
        right_layout = QVBoxLayout(self.right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(props_scroll)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left)
        splitter.addWidget(self.right_column)
        # Правой ровно её ширина, остальное — списку шагов.
        column = self.PROPS_WIDTH + self.scrollbar_width
        splitter.setSizes([1120 - column, column])

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(160)
        # Строки и так переносятся по ширине — горизонтальная полоса только
        # занимает место снизу.
        self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log.setFrameShape(QPlainTextEdit.NoFrame)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setSpacing(6)
        layout.addWidget(splitter)
        layout.addWidget(self.log)
        self.setCentralWidget(central)

        # Сочетания привязаны к списку, а не к окну: иначе Ctrl+C в поле
        # «Аргументы» копировал бы шаг вместо текста, а Del стирал бы шаг
        # вместо символа.
        for keys, handler in (
            (QKeySequence.Copy, self._copy_step),
            (QKeySequence.Paste, self._paste_step),
            (QKeySequence("Ctrl+D"), self._duplicate_step),
            (QKeySequence.Delete, self._delete_step),
        ):
            shortcut = QShortcut(keys, self.list, handler)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)

    def _build_toolbar(self):
        # Строки меню нет: файловые команды стоят кнопками, редкие сервисные
        # спрятаны под «Параметры». Сочетания клавиш живут на самих действиях,
        # поэтому работают и без меню.
        bar = QToolBar("Основная")
        bar.setMovable(False)
        self.addToolBar(bar)
        self.toolbar = bar

        actions_by_label = {}
        for label, shortcut, handler in (
            ("Новый", QKeySequence.New, self._file_new),
            ("Открыть", QKeySequence.Open, self._file_open),
            ("Сохранить", QKeySequence.Save, self._file_save),
            ("Сохранить как…", QKeySequence.SaveAs, self._file_save_as),
        ):
            action = bar.addAction(label)
            action.setShortcut(shortcut)
            action.triggered.connect(handler)
            actions_by_label[label] = action

        # Пустой сценарий сохранять незачем — гасим вместе с кнопками шагов.
        self.action_save = actions_by_label["Сохранить"]
        self.action_save_as = actions_by_label["Сохранить как…"]

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)

        bar.addWidget(self._build_tools_button())

        exit_action = bar.addAction("Выход")
        exit_action.setShortcut(QKeySequence.Quit)
        exit_action.triggered.connect(self.close)

    def _build_status_bar(self):
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)

        self.status_left = QLabel("")
        bar.addWidget(self.status_left)

        version = QLabel(f"v{model.VERSION}")
        bar.addPermanentWidget(version)

        link = QLabel(
            f'<a href="{model.REPO_URL}" style="text-decoration: none;">'
            f"{model.REPO_OWNER}</a>"
        )
        link.setOpenExternalLinks(True)
        link.setToolTip(model.REPO_URL)
        # addPermanentWidget прижимает к правому краю и не даёт затирать
        # временными сообщениями строки состояния.
        bar.addPermanentWidget(link)

    def _build_tools_button(self):
        menu = QMenu(self)
        menu_font = QFont()
        menu_font.setPointSize(8)
        menu.setFont(menu_font)

        self.log_action = menu.addAction("Писать лог в файл при ошибке")
        self.log_action.setCheckable(True)
        self.log_action.setChecked(settings.get("write_log"))
        self.log_action.toggled.connect(lambda on: settings.set_value("write_log", on))

        menu.addAction("Очистить лог").triggered.connect(self.log_clear)

        menu.addSeparator()
        menu.addAction("Переустановить ассоциацию .asic").triggered.connect(
            self._reinstall_association
        )
        menu.addAction("Проверить привязку .asic").triggered.connect(
            self._check_association_state
        )
        menu.addAction("Удалить ассоциацию").triggered.connect(self._remove_association)

        menu.addSeparator()
        self.admin_action = menu.addAction("Перезапустить от администратора")
        self.admin_action.triggered.connect(self._restart_as_admin)
        self.admin_action.setEnabled(not self.elevated)

        button = QToolButton()
        button.setText("Параметры")
        # Меню открываем сами: setMenu() пририсовал бы к кнопке стрелку вниз,
        # и убрать её стилями получается не во всех темах.
        button.clicked.connect(
            lambda: menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        )
        return button

    # --- панель свойств ---

    def _build_props(self):
        while self.props_layout.count():
            item = self.props_layout.takeAt(0)
            widget = item.widget()
            if widget:
                # Сначала прячем, потом ставим на удаление: deleteLater
                # отрабатывает только когда управление вернётся в цикл
                # событий, а до тех пор старая панель висела бы поверх новой.
                # Именно hide(), а не setParent(None): виджет без родителя
                # Qt считает самостоятельным окном, и оно мигает на экране.
                widget.hide()
                widget.deleteLater()

        step = self._current_step()
        if step is None:
            return

        step_type = step.get("type")
        known = step_type in model.KNOWN_TYPES

        common = QWidget()
        form = QFormLayout(common)
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        type_combo = ComboBox()
        # Строки идут теми же группами, что и в меню «Добавить шаг».
        # type_values — что стоит за каждой строкой; у заголовка None.
        type_values = []
        for title, types in model.STEP_GROUPS:
            combo_header(type_combo, title)
            type_values.append(None)
            for known_type in types:
                type_combo.addItem(model.TYPE_NAMES[known_type])
                type_values.append(known_type)

        if known:
            type_combo.setCurrentIndex(type_values.index(step_type))
        else:
            # Показываем чужой тип первым пунктом, чтобы шаг можно было
            # починить, выбрав нормальный тип из списка.
            type_values.insert(0, step_type)
            type_combo.insertItem(0, f"неизвестный: {step_type or 'не задан'}")
            type_combo.setCurrentIndex(0)

        def on_type_changed(index):
            new_type = type_values[index]
            if new_type is not None:
                self._change_type(step, new_type)

        type_combo.currentIndexChanged.connect(on_type_changed)
        form.addRow("Тип шага", type_combo)

        enabled = CheckBox("Шаг включён")
        enabled.setChecked(step.get("enabled", True))
        enabled.stateChanged.connect(
            lambda _: (step.__setitem__("enabled", enabled.isChecked()), self._refresh_list())
        )
        # Пустая подпись, а не addRow(enabled): так галочка встаёт в колонку
        # полей, а не вылезает к левому краю.
        form.addRow("", enabled)

        ignore = CheckBox("Игнорировать ошибку")
        ignore.setChecked(step.get("ignore_error", False))
        ignore.stateChanged.connect(lambda _: step.__setitem__("ignore_error", ignore.isChecked()))
        form.addRow("", ignore)

        comment = QLineEdit()
        comment.setText(step.get("comment", ""))
        comment.textChanged.connect(
            lambda text: (step.__setitem__("comment", text), self.touch())
        )
        form.addRow("Комментарий", comment)

        form.addRow(separator())

        self.props_builder.build(step["type"], step["params"], form)
        align_form_labels(form)

        self.props_layout.addWidget(common)
        # Распорка снизу забирает всю лишнюю высоту себе. Без неё форма
        # растягивается на всю панель, и QFormLayout раздаёт лишнее строкам:
        # в высоком окне поля разъезжались.
        self.props_layout.addStretch()

        # Подстраховка на случай шага, которому закреплённой ширины мало:
        # колонка расширится один раз и дальше останется прежней — лучше,
        # чем обрезанное поле.
        needed = common.minimumSizeHint().width() + self.scrollbar_width
        if needed > self.right_column.minimumWidth():
            self.right_column.setMinimumWidth(needed)

    def bind_line(self, widget, params, key):
        widget.setText(str(params.get(key, "")))
        widget.textChanged.connect(lambda text: (params.__setitem__(key, text), self.touch()))

    def bind_text(self, widget, params, key):
        widget.setPlainText(str(params.get(key, "")))
        widget.textChanged.connect(
            lambda: (params.__setitem__(key, widget.toPlainText()), self.touch())
        )

    def bind_spin(self, widget, params, key, scale=1):
        """scale — во сколько раз хранимое больше показанного.

        В файле все времена в миллисекундах, но минуту ожидания удобнее
        видеть как «60 с», а не «60000 мс».
        """
        widget.setValue(int(params.get(key, 0)) // scale)
        widget.valueChanged.connect(
            lambda value: (params.__setitem__(key, value * scale), self.touch())
        )

    def bind_check(self, widget, params, key):
        widget.setChecked(bool(params.get(key, False)))
        widget.stateChanged.connect(
            lambda _: (params.__setitem__(key, widget.isChecked()), self.touch())
        )

    def bind_combo(self, widget, params, key, values):
        current = params.get(key)
        if current in values:
            widget.setCurrentIndex(values.index(current))
        widget.currentIndexChanged.connect(
            lambda index: (params.__setitem__(key, values[index]), self.touch())
        )

    def pick_process(self, line_edit, full_path):
        dialog = ProcessPicker(self)
        if not dialog.exec() or not dialog.selected_name:
            return

        # Запоминаем путь, даже когда в поле пойдёт одно имя: значок лежит
        # в файле, а спросить путь у закрытой программы будет не у кого.
        settings.remember_exe(dialog.selected_name, dialog.selected or "")

        if not full_path:
            line_edit.setText(dialog.selected_name)
            return

        if not dialog.selected:
            QMessageBox.warning(
                self,
                model.APP_NAME,
                f"Windows не отдаёт путь к «{dialog.selected_name}».\n"
                "Так бывает с программами, запущенными от администратора "
                "или от системы.\n\nУкажи файл кнопкой «…».",
            )
            return

        line_edit.setText(os.path.normpath(dialog.selected))

    # --- работа со списком шагов ---

    def _current_step(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.script["steps"]):
            return self.script["steps"][row]
        return None

    def _show_add_menu(self):
        menu = QMenu(self)
        for title, types in model.STEP_GROUPS:
            menu.addSection(title)
            for step_type in types:
                action = menu.addAction(model.TYPE_NAMES[step_type])
                action.triggered.connect(
                    lambda checked=False, t=step_type: self._add_step(t)
                )
        menu.exec(self.btn_add.mapToGlobal(self.btn_add.rect().bottomLeft()))

    def _add_step(self, step_type):
        self._mark_dirty()
        # Новый шаг встаёт следом за выбранным, как вставка и дубль.
        # В конец — только когда ничего не выбрано.
        row = self.list.currentRow()
        at = row + 1 if row >= 0 else len(self.script["steps"])
        self.script["steps"].insert(at, model.new_step(step_type))
        self._refresh_list()
        self.list.setCurrentRow(at)

    def _delete_step(self):
        row = self.list.currentRow()
        if row < 0:
            return
        self._mark_dirty()
        del self.script["steps"][row]
        self._refresh_list()
        self._build_props()

    def _copy_step(self):
        step = self._current_step()
        if not step:
            return
        self.buffer = model.copy_step(step)
        # В буфер обмена — чтобы шаг доехал до другого окна программы:
        # окна живут в разных процессах и общей памяти у них нет.
        QApplication.clipboard().setText(model.step_to_text(step))

    def _paste_step(self):
        # Буфер обмена свежее своей копии: он мог прийти из другого окна.
        # Свой буфер остаётся запасным вариантом на случай, если в системный
        # успели положить что-то другое.
        step = model.step_from_text(QApplication.clipboard().text())
        if step is None and self.buffer:
            step = model.copy_step(self.buffer)
        if step is None:
            return

        self._mark_dirty()
        row = self.list.currentRow()
        at = row + 1 if row >= 0 else len(self.script["steps"])
        self.script["steps"].insert(at, step)
        self._refresh_list()
        self.list.setCurrentRow(at)

    def _duplicate_step(self):
        step = self._current_step()
        if not step:
            return
        self._mark_dirty()
        row = self.list.currentRow()
        self.script["steps"].insert(row + 1, model.copy_step(step))
        self._refresh_list()
        self.list.setCurrentRow(row + 1)

    def _change_type(self, step, new_type):
        if step["type"] == new_type:
            return
        self._mark_dirty()
        model.change_type(step, new_type)
        self._refresh_list()
        self._build_props()

    def _on_rows_moved(self, parent, start, end, dest, row):
        self._mark_dirty()
        steps = self.script["steps"]
        moved = steps.pop(start)
        steps.insert(row if row < start else row - 1, moved)
        self._refresh_list()

    def _refresh_list(self):
        row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for step in self.script["steps"]:
            item = QListWidgetItem()
            self._set_item_look(item, step)
            if not step.get("enabled", True):
                item.setForeground(Qt.gray)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if 0 <= row < self.list.count():
            self.list.setCurrentRow(row)
        self._update_buttons()

    def _placeholder_lines(self):
        """Что написать в пустом списке шагов."""
        if self.elevated:
            admin = (
                "Права администратора есть — чужие окна, клавиши "
                "и процессы слушаются."
            )
        else:
            admin = (
                "Сейчас без прав администратора: чужие окна и процессы "
                "могут не поддаться. Параметры → Перезапустить от администратора."
            )

        return [
            "Пустой сценарий",
            "Нажми «Добавить шаг» — или Ctrl+V, если шаг скопирован "
            "из другого сценария.",
            "",
            "Шаги выполняются сверху вниз, порядок меняется перетаскиванием. "
            "Ctrl+D дублирует шаг, Del удаляет.",
            "",
            admin,
        ]

    @staticmethod
    def _set_item_look(item, step):
        """Название, подсказка и значок программы, с которой шаг работает.

        Подсказка нужна ровно потому, что в строке текст обрезается: иначе
        конец длинного шага не прочитать никак. Значок есть не у всех шагов —
        у паузы и обоев программы нет, там останется пустое место.
        """
        title = model.step_title(step)
        item.setText(title)
        item.setToolTip(title)
        item.setIcon(step_icon(step) or QIcon())

    def _on_current_changed(self, _row):
        self._build_props()
        self._update_buttons()

    def _update_buttons(self):
        # Нечего удалять и нечего выполнять — кнопки не должны выглядеть
        # рабочими.
        steps = self.script.get("steps") or []
        has_current = self._current_step() is not None

        self.btn_delete.setEnabled(has_current)
        self.btn_run_one.setEnabled(has_current)
        self.btn_run_all.setEnabled(bool(steps))
        self.btn_stop.setEnabled(False)
        self.action_save.setEnabled(bool(steps))
        self.action_save_as.setEnabled(bool(steps))

        self._update_status(steps)

    def _update_status(self, steps):
        if not steps:
            self.status_left.setText("Нет шагов")
            return

        row = self.list.currentRow()
        if 0 <= row < len(steps):
            self.status_left.setText(f"Шаг {row + 1} из {len(steps)}")
        else:
            self.status_left.setText(f"Шагов: {len(steps)}")

    def touch(self):
        self._mark_dirty()
        row = self.list.currentRow()
        if 0 <= row < self.list.count():
            self._set_item_look(self.list.item(row), self.script["steps"][row])

    # --- выполнение ---

    def _make_log(self):
        return runner.Log(lambda line, level: self._log_line(line))

    def _log_line(self, line):
        self.log.appendPlainText(line)
        QApplication.processEvents()

    def log_clear(self):
        self.log.clear()

    def _request_stop(self):
        self._stop_requested = True
        self.btn_stop.setEnabled(False)

    def _should_stop(self):
        """Ядро зовёт это, чтобы узнать, не пора ли остановиться.

        Выполнение идёт в главном потоке, поэтому нажатие кнопки дойдёт
        до нас, только если прокрутить очередь событий. Делаем это здесь —
        так ядро остаётся без единой строчки про Qt.
        """
        QApplication.processEvents()
        return self._stop_requested

    def _set_running(self, running):
        # Отключаем виджеты поимённо, а не всё окно: у выключенного окна
        # выключаются и дочерние кнопки, и «Прервать» стала бы недоступна.
        for widget in (self.list, self.props, self.toolbar, self.btn_add,
                       self.btn_delete, self.btn_run_one, self.btn_run_all):
            widget.setEnabled(not running)

        self.btn_stop.setEnabled(running)
        self._stop_requested = False

        if not running:
            self._update_buttons()
            # Панель свойств читает состояние системы — список мониторов,
            # какой из них основной, найденный Stream Deck. Шаг это состояние
            # и меняет, так что после выполнения панель врёт, пока её не
            # пересобрать. Список — по той же причине: выполнение могло
            # выяснить, где лежит программа, и у шага появится её значок.
            self._refresh_list()
            self._build_props()

    def _run_current(self):
        step = self._current_step()
        if step is None:
            return
        if self._ctx is None:
            self._ctx = actions.Context(self.script, self.path, self._should_stop)
        log = self._make_log()
        self._set_running(True)
        # Номер тот же, что в списке слева, — чтобы лог одиночного запуска
        # читался так же, как лог полного прогона.
        index = self.list.currentRow() + 1
        try:
            runner.run_step(step, self._ctx, log, index)
        except Exception as e:
            log.error(runner.line(runner.step_prefix(index), f"ошибка: {e}"))
        finally:
            self._set_running(False)

    def _run_all(self):
        self.log.clear()
        self._ctx = None
        log = self._make_log()


        self._set_running(True)
        try:
            runner.run_script(self.script, log, self.path, self._should_stop)
        finally:
            self._set_running(False)

    # --- файлы ---

    def _set_path(self, path):
        self.path = path
        self.dirty = False
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self.path) if self.path else "без имени"
        mark = " *" if self.dirty else ""
        # От прав зависит и перетаскивание, и доставка клавиш — пусть будет
        # видно, в каком режиме работаем.
        admin = " — администратор" if self.elevated else ""
        self.setWindowTitle(f"{model.APP_NAME} — {name}{mark}{admin}")

    def _mark_dirty(self, value=True):
        if self.dirty == value:
            return
        self.dirty = value
        self._update_title()

    def _load(self, path):
        try:
            self.script = model.load_script(path)
        except Exception as e:
            QMessageBox.critical(self, model.APP_NAME, f"Не удалось открыть файл:\n{e}")
            return False
        self._ctx = None
        self._set_path(path)
        self._refresh_list()
        self._build_props()
        self._warn_unknown_steps()
        return True

    def _warn_unknown_steps(self):
        unknown = model.unknown_steps(self.script)
        if not unknown:
            return
        listing = "\n".join(f"    шаг {i}: {t or 'без типа'}" for i, t in unknown)
        QMessageBox.warning(
            self,
            model.APP_NAME,
            "В файле есть шаги неизвестного типа:\n\n"
            f"{listing}\n\n"
            "Они выключены и при выполнении пропускаются. "
            "При сохранении вернутся в файл без изменений.",
        )

    def _file_new(self):
        if not self._confirm_discard():
            return
        self.script = model.new_script()
        self._ctx = None
        self._set_path(None)
        self._refresh_list()
        self._build_props()

    def _file_open(self):
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть сценарий", "", f"Сценарии (*{model.EXT});;Все файлы (*)"
        )
        if path:
            self._load(path)

    def _file_save(self):
        if not self.path:
            return self._file_save_as()
        return self._write(self.path)

    def _file_save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить сценарий", self.path or "", f"Сценарии (*{model.EXT})"
        )
        if not path:
            return False
        if not path.lower().endswith(model.EXT):
            path += model.EXT
        return self._write(path)

    def _write(self, path):
        self.script["alias_exe"] = {
            step["params"]["alias"]: step["params"]["path"]
            for step in self.script["steps"]
            if step.get("type") == model.LAUNCH
            and step["params"].get("alias")
            and step["params"].get("path")
        }
        try:
            model.save_script(path, self.script)
        except Exception as e:
            QMessageBox.critical(self, model.APP_NAME, f"Не удалось сохранить:\n{e}")
            return False
        self._set_path(path)
        return True

    def _ask_yes_no(self, text, yes="Да", no="Нет"):
        box = QMessageBox(self)
        box.setWindowTitle(model.APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText(text)
        yes_button = box.addButton(yes, QMessageBox.YesRole)
        box.addButton(no, QMessageBox.NoRole)
        box.setDefaultButton(yes_button)
        box.exec()
        return box.clickedButton() is yes_button

    def _confirm_discard(self):
        if not self.dirty:
            return True

        # Стандартные кнопки Qt подписаны по-английски: перевод лежит
        # в отдельном .qm, который в сборку не попадает. Проще задать текст.
        box = QMessageBox(self)
        box.setWindowTitle(model.APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText("Сценарий изменён. Сохранить перед закрытием?")
        save = box.addButton("Сохранить", QMessageBox.AcceptRole)
        discard = box.addButton("Не сохранять", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.setDefaultButton(save)
        box.exec()

        clicked = box.clickedButton()
        if clicked is save:
            return bool(self._file_save())
        # Отмена и закрытие крестиком — остаёмся в редакторе.
        return clicked is discard

    def closeEvent(self, event):
        event.accept() if self._confirm_discard() else event.ignore()

    # --- права ---

    def _restart_as_admin(self):
        """Поднимает редактор до администратора, не теряя открытый файл.

        Права нельзя добавить работающему процессу — только запустить новый.
        Поэтому запускаем себя же через UAC и закрываемся.
        """
        if self.elevated:
            QMessageBox.information(
                self, model.APP_NAME, "Программа уже запущена от администратора."
            )
            return

        if not self._confirm_discard():
            return

        arguments = f'--edit "{self.path}"' if self.path else "--edit"
        try:
            winapi.relaunch_elevated(arguments)
        except OSError as e:
            QMessageBox.warning(self, model.APP_NAME, f"Не удалось перезапустить:\n{e}")
            return

        # Файл уже сохранён или изменения отброшены — второй раз не спрашиваем.
        self.dirty = False
        self.close()

    # --- ассоциация ---

    def _reinstall_association(self):
        exe = install.exe_path()
        if not os.path.isfile(exe):
            QMessageBox.warning(
                self,
                model.APP_NAME,
                f"Не найден собранный exe:\n{exe}\n\nСначала собери проект через PyInstaller.",
            )
            return
        if install.install() != 0:
            return

        other = install.foreign_choice()
        if other:
            # Выбор из «Открыть с помощью» лежит в другой ветке реестра
            # и перебивает нашу запись — снять его можно только руками.
            QMessageBox.warning(
                self,
                model.APP_NAME,
                f"Файлы {model.EXT} привязаны к:\n{exe}\n\n"
                f"Но для них выбрана другая программа ({other}), и Windows "
                "слушает именно её — отсюда и чужой значок.\n\n"
                "Правый клик по файлу → Открыть с помощью → "
                "Выбрать другое приложение → Automaticsic → всегда.",
            )
            return

        QMessageBox.information(self, model.APP_NAME, f"Файлы {model.EXT} привязаны к:\n{exe}")

    def _check_association_state(self):
        box = QMessageBox(self)
        box.setWindowTitle(model.APP_NAME)
        box.setIcon(QMessageBox.Information)
        box.setText("Что записано о файлах .asic")
        # Моноширинный: пути и значения так читаются столбиком.
        box.setInformativeText(f"<pre>{install.report()}</pre>")
        box.exec()

    def _remove_association(self):
        if self._ask_yes_no(f"Удалить привязку файлов {model.EXT}?", yes="Удалить"):
            install.uninstall()
            QMessageBox.information(self, model.APP_NAME, "Привязка удалена")

    def check_association(self):
        if not install.needs_update():
            return
        first_time = install.current_target() is None
        text = (
            f"Привязать файлы {model.EXT} к этой программе?"
            if first_time
            else f"Файлы {model.EXT} привязаны к другому расположению.\nПеревязать на текущее?"
        )
        if self._ask_yes_no(text, yes="Привязать", no="Не сейчас"):
            install.install()

    # --- перетаскивание ---

    def dragEnterEvent(self, event):
        event.acceptProposedAction() if event.mimeData().hasUrls() else event.ignore()

    def dragMoveEvent(self, event):
        event.acceptProposedAction() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        path = next(
            (
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.toLocalFile().lower().endswith(model.EXT)
            ),
            None,
        )
        if not path or not self._confirm_discard():
            return
        if self._load(path):
            event.acceptProposedAction()


def run_editor(path=None):
    app = QApplication(sys.argv)
    apply_light_theme(app)
    # Своё имя процесса в панели задач — иначе Windows покажет значок
    # python.exe при запуске из исходников.
    winapi.set_app_id()
    app.setWindowIcon(QIcon(model.icon_path()))
    window = MainWindow()
    if path and os.path.isfile(path):
        window._load(path)
    window.show()
    window.check_association()
    return app.exec()