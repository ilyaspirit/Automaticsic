import os
import shutil

from PySide6.QtCore import (
    Qt, QRect, QSize, QPointF, QEvent, QFileInfo, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QFontMetrics, QIcon, QImage, QPainter, QPalette, QPen,
    QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QFormLayout, QLineEdit, QListWidget, QWidget, QHBoxLayout,
    QFrame, QSpinBox, QSizePolicy, QStyledItemDelegate, QStyle, QLabel,
    QComboBox, QPushButton, QCheckBox, QStyleOptionButton, QPlainTextEdit,
    QFileIconProvider,
)

import model
import settings
import winapi
from ui_style import ACCENT, ACCENT_TEXT, CONTROL_TOTAL, DISABLED_ON_ACCENT, READONLY


class CheckBox(QCheckBox):
    """Галочка с нарисованной птичкой.

    Стилизованный QCheckBox рисует пустой квадрат: саму птичку Qt берёт
    картинкой, а её у нас нет. Квадрат и его цвет задаёт таблица стилей,
    птичку дорисовываем поверх.
    """

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.isChecked():
            return

        option = QStyleOptionButton()
        self.initStyleOption(option)
        box = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        color = QColor(ACCENT_TEXT if self.isEnabled() else READONLY)
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        cx = box.center().x() + 0.5
        cy = box.center().y() + 0.5
        painter.drawPolyline(QPolygonF([
            QPointF(cx - 3.5, cy),
            QPointF(cx - 1, cy + 2.5),
            QPointF(cx + 3.5, cy - 2.5),
        ]))
        painter.end()


class ComboBox(QComboBox):
    """Выпадающий список со своей стрелкой.

    Как только на QComboBox ложится таблица стилей, Windows перестаёт
    рисовать его родными средствами и берётся встроенный запасной стиль —
    отсюда угловатая стрелка родом из девяностых. Прячем её в ui_style
    и рисуем шеврон сами, поверх всего остального.
    """

    ARROW_BOX = 22

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        role = QPalette.Normal if self.isEnabled() else QPalette.Disabled
        pen = QPen(self.palette().color(role, QPalette.Text), 1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        cx = self.width() - self.ARROW_BOX / 2
        cy = self.height() / 2
        painter.drawPolyline(QPolygonF([
            QPointF(cx - 4, cy - 2),
            QPointF(cx, cy + 2.5),
            QPointF(cx + 4, cy - 2),
        ]))
        painter.end()


class TextEdit(QPlainTextEdit):
    """Многострочное поле ввода — для команды оболочки.

    Отдельный класс нужен из-за высоты: у поля в форме её никто не задаёт,
    и оно растянулось бы на всю панель. Считаем по числу строк, чтобы
    команда из четырёх строк была видна целиком без прокрутки.
    """

    def __init__(self, rows=4, parent=None):
        super().__init__(parent)
        # Свойство, а не своя таблица стилей: фон и рамка берутся
        # из ui_style, где живёт всё остальное оформление.
        self.setProperty("editable", True)
        self.setProperty("label_top", True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabChangesFocus(True)
        line = QFontMetrics(self.font()).lineSpacing()
        self.setFixedHeight(line * rows + 12)


def combo_header(combo, text):
    """Заголовок группы в выпадающем списке.

    Групп в QComboBox нет, поэтому заголовок — обычная строка, у которой
    сняты флаги: мышь её не берёт, стрелки перескакивают через неё.
    """
    combo.addItem(text)
    item = combo.model().item(combo.count() - 1)
    item.setFlags(item.flags() & ~(Qt.ItemIsSelectable | Qt.ItemIsEnabled))
    font = item.font()
    font.setBold(True)
    item.setFont(font)


def resolve_shortcut(path):
    """Разворачивает .lnk в (путь к цели, аргументы).

    Аргументы у ярлыка часто и есть весь смысл: без «-a SwitchProfile»
    или адреса страницы запускается пустая программа.
    """
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        link = shell.CreateShortCut(path)
        return link.Targetpath or path, (link.Arguments or "").strip()
    except Exception:
        return path, ""


class PathEdit(QLineEdit):
    def __init__(self, mode="path", parent=None):
        super().__init__(parent)
        self.mode = mode
        # Поле аргументов, куда уедет вторая половина ярлыка. Ставится
        # снаружи — есть только у шага запуска.
        self.args_edit = None
        self.setAcceptDrops(True)
        self.setDragEnabled(False)

    def _extract(self, mime):
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            path = url.toLocalFile()
            if path:
                return path
        return None

    def dragEnterEvent(self, event):
        if self._extract(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._extract(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._extract(event.mimeData())
        if not path:
            event.ignore()
            return
        if path.lower().endswith(".lnk"):
            path, arguments = resolve_shortcut(path)
            if arguments and self.args_edit is not None:
                self.args_edit.setText(arguments)
        self.setText(os.path.basename(path) if self.mode == "name" else os.path.normpath(path))
        event.setDropAction(Qt.CopyAction)
        event.accept()


# Значки спрашиваем у проводника и держим найденное: список шагов
# перерисовывается на каждый чих, а поиск процесса по имени — не бесплатный.
_icons = {}
_icon_provider = None


def file_icon(source):
    """Значок файла — тот же, что показывает проводник.

    Источник бывает трёх видов: путь к файлу, голое имя exe и адрес схемы
    вроде steam://. У последнего файла нет вовсе, у имени файл ищется —
    сперва среди программ Windows, потом среди запущенных процессов.
    """
    global _icon_provider

    source = os.path.expandvars((source or "").strip().strip('"'))
    if not source or winapi.is_uri(source):
        return None
    if source in _icons:
        cached = _icons[source]
        # За «не нашли» держимся только пока путь и правда неизвестен:
        # стоило его выяснить — ищем заново, иначе значок не появился бы
        # до перезапуска программы.
        if cached is not None or not settings.known_exe(source):
            return cached

    path = source if os.path.isfile(source) else ""
    if not path and not os.path.dirname(source) and source.lower().endswith(".exe"):
        # Голое имя ищем в четыре захода. Требование «.exe» на конце тут
        # не придирка: поиск среди процессов небыстрый, а поле правится
        # по букве, и без него он запускался бы на «c», «ch», «chr» и так
        # далее до самого конца слова.
        path = (
            shutil.which(source)                # программы самой Windows
            or winapi.registered_exe(source)    # что записал установщик
            or settings.known_exe(source)       # что мы видели раньше
            or winapi.exe_path_by_name(source)  # что запущено прямо сейчас
        )
        if path:
            # Запоминаем: в следующий раз значок найдётся и у закрытой
            # программы — а её как раз чаще всего и закрывают шагом.
            settings.remember_exe(source, path)

    icon = None
    if path:
        if _icon_provider is None:
            _icon_provider = QFileIconProvider()
        found = _icon_provider.icon(QFileInfo(path))
        if not found.isNull():
            icon = found

    _icons[source] = icon
    return icon


def shell_icon(index):
    """Системный значок из SHELL32.dll — по номеру внутри библиотеки.

    Берём оба размера сразу: в библиотеке мелкий нарисован отдельно, а не
    уменьшен, и в списке он куда чётче уменьшенного крупного.
    """
    key = f"shell32:{index}"
    if key in _icons:
        return _icons[key]

    library = winapi.shell32_path()
    icon = QIcon()
    for size in (16, 32):
        raw = winapi.library_icon(library, index, size)
        if not raw:
            continue
        data, side = raw
        image = QImage(data, side, side, QImage.Format_ARGB32).copy()
        if not image.isNull():
            icon.addPixmap(QPixmap.fromImage(image))

    _icons[key] = None if icon.isNull() else icon
    return _icons[key]


def step_icon(step):
    """Значок шага: сперва самой программы, иначе системный по номеру.

    Программа информативнее: у шага закрытия Chrome полезнее видеть Chrome,
    а не общий крестик. Системный подставляется там, где программы нет —
    у паузы, обоев, монитора — и там, где её ещё не выбрали.
    """
    icon = file_icon(model.step_icon_source(step))
    if icon is not None:
        return icon

    index = model.STEP_SHELL_ICONS.get(step.get("type"))
    return shell_icon(index) if index is not None else None


class StepDelegate(QStyledItemDelegate):
    HANDLE_WIDTH = 22
    NUMBER_GAP = 8
    ICON = 16
    ICON_GAP = 8

    @staticmethod
    def _number_width(option, index):
        """Ширина колонки номеров — по самому длинному номеру в списке.

        Меряем по количеству шагов, а не по номеру строки: иначе у «10.»
        колонка шире, чем у «9.», и названия разъезжаются по вертикали.
        """
        source = index.model()
        total = source.rowCount() if source is not None else 1
        return option.fontMetrics.horizontalAdvance(f"{max(total, 1)}.")

    def paint(self, painter, option, index):
        painter.save()

        # Отключённость шага приходит цветом в ForegroundRole. Под выделением
        # эта роль не годится — серый на синей заливке не прочитать, — поэтому
        # она здесь только признак: отключённый или нет.
        brush = index.data(Qt.ForegroundRole)
        disabled = brush is not None

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            if disabled:
                text_color = QColor(DISABLED_ON_ACCENT)
            else:
                text_color = option.palette.highlightedText().color()
            handle_color = text_color
        else:
            if option.state & QStyle.State_MouseOver:
                painter.fillRect(option.rect, option.palette.alternateBase())
            text_color = brush.color() if disabled else option.palette.text().color()
            handle_color = option.palette.mid().color()

        number_width = self._number_width(option, index)
        number_rect = option.rect.adjusted(10, 0, 0, 0)
        number_rect.setWidth(number_width)

        # Колонка значков одной ширины на всех шагах, даже когда значка нет:
        # иначе названия у паузы и у запуска начинались бы с разных мест.
        icon_left = option.rect.left() + 10 + number_width + self.NUMBER_GAP
        # Верх считаем от края строки, а не от её центра: центр у нечётной
        # высоты округляется, и значок вставал на пиксель выше положенного.
        icon_top = option.rect.top() + (option.rect.height() - self.ICON) // 2

        icon = index.data(Qt.DecorationRole)
        if icon is not None and not icon.isNull():
            icon.paint(
                painter,
                QRect(icon_left, icon_top, self.ICON, self.ICON),
                Qt.AlignCenter,
                QIcon.Disabled if disabled else QIcon.Normal,
            )

        shift = 10 + number_width + self.NUMBER_GAP + self.ICON + self.ICON_GAP
        text_rect = option.rect.adjusted(shift, 0, -self.HANDLE_WIDTH - 6, 0)

        # Текст ставим по своей базовой линии, а не через AlignVCenter.
        # Тот центрует кегельную площадку — вместе с местом под выносные
        # элементы снизу, которых в названии шага чаще всего нет. Из-за
        # этого буквы оказывались ниже значка. Считаем так, чтобы ровно
        # посередине строки оказалась площадка заглавных букв: тогда текст
        # и значок выровнены по-настоящему, при любом шрифте.
        # Отсчитываем от середины значка, а не от середины строки: так текст
        # и значок выровнены друг относительно друга по построению, а не по
        # совпадению округлений.
        metrics = option.fontMetrics
        middle = icon_top + self.ICON / 2
        baseline = round(middle + metrics.capHeight() / 2)

        number = f"{index.row() + 1}."
        painter.setPen(text_color if option.state & QStyle.State_Selected
                       else option.palette.mid().color())
        painter.drawText(
            number_rect.right() - metrics.horizontalAdvance(number), baseline, number
        )

        painter.setPen(text_color)
        painter.drawText(
            text_rect.left(),
            baseline,
            metrics.elidedText(
                index.data(Qt.DisplayRole) or "", Qt.ElideRight, text_rect.width()
            ),
        )

        painter.setPen(handle_color)
        cx = option.rect.right() - self.HANDLE_WIDTH // 2 - 6
        cy = option.rect.center().y()
        for dy in (-4, 0, 4):
            painter.drawLine(cx - 5, cy + dy, cx + 5, cy + dy)

        painter.restore()

    def sizeHint(self, option, index):
        # Высоту считаем сами, а не берём у родителя: тот прибавляет к ней
        # размер значка, и строка со значком становилась выше соседней без
        # него — список дёргался, стоило задать программу. Теперь высота
        # одна на всех и со значком не связана.
        text = option.fontMetrics.height()
        # Ширину не запрашиваем совсем: иначе длинное название шага растянуло
        # бы строку и внизу списка появилась бы горизонтальная прокрутка.
        # Строка занимает ширину списка, а текст рисуется с многоточием.
        return QSize(0, max(text, self.ICON) + 12)


class StepList(QListWidget):
    """Список шагов, который на пустом месте объясняет, что делать.

    Пустой сценарий — первое, что видит человек, открыв программу. Молчащий
    белый прямоугольник не подсказывает ничего, поэтому пишем прямо в нём.
    """

    MARGIN = 24
    GAP = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.placeholder = []

    def set_placeholder(self, lines):
        """Первая строка — заголовком, остальные — обычным текстом."""
        self.placeholder = [line for line in lines]
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count() or not self.placeholder:
            return

        title, *body = self.placeholder
        area = self.viewport().rect().adjusted(
            self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN
        )

        painter = QPainter(self.viewport())
        font = painter.font()

        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.palette().text().color())
        height = QFontMetrics(font).height()
        painter.drawText(
            QRect(area.left(), area.top(), area.width(), height),
            Qt.AlignLeft | Qt.AlignTop,
            title,
        )

        font.setBold(False)
        painter.setFont(font)
        painter.setPen(self.palette().mid().color())
        painter.drawText(
            area.adjusted(0, height + self.GAP, 0, 0),
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            "\n".join(body),
        )
        painter.end()


class MonitorBadge(QWidget):
    """Большой номер посреди экрана — как «Определить» в параметрах Windows.

    Фокус не забирает и мышь не ловит: пока номера висят, с редактором
    можно продолжать работать.
    """

    WIDTH = 240
    HEIGHT = 180
    MARGIN = 24

    def __init__(self, number, caption):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        self.number = number
        self.caption = caption

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawRoundedRect(self.rect(), 16, 16)

        painter.setPen(QColor(ACCENT_TEXT))
        font = painter.font()

        font.setBold(True)
        font.setPointSize(76)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(0, 0, 0, -30), Qt.AlignCenter, str(self.number))

        font.setBold(False)
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(
            self.rect().adjusted(0, 0, 0, -20),
            Qt.AlignHCenter | Qt.AlignBottom,
            self.caption,
        )


# Показанные сейчас плашки. Держим ссылку здесь, а не только в замыкании
# таймера: без неё окна собрал бы сборщик мусора, и они бы мигнули.
_badges = []


def identify_monitors(ms=6000):
    """Показывает номер на каждом экране и сам их убирает.

    Нумеруем экраны так же, как winapi.monitors(), — слева направо,
    сверху вниз, чтобы номер на экране совпал с номером в списке. Ставим
    окна по координатам Qt, а не Windows: при разном масштабе на разных
    мониторах системные пиксели и пиксели Qt не совпадают.
    """
    # Повторное нажатие начинает отсчёт заново, а не копит плашки поверх.
    for badge in _badges:
        badge.close()
    _badges.clear()

    primary = QApplication.primaryScreen()
    screens = sorted(
        QApplication.screens(),
        key=lambda s: (s.geometry().x(), s.geometry().y()),
    )

    badges = []
    for number, screen in enumerate(screens, 1):
        area = screen.geometry()
        scale = screen.devicePixelRatio()
        caption = f"{round(area.width() * scale)}×{round(area.height() * scale)}"
        if screen is primary:
            caption += " · основной"

        badge = MonitorBadge(number, caption)
        # В правый верхний угол рабочей области: по центру плашка накрывает
        # то, на что человек как раз и смотрит. Рабочая область, а не весь
        # экран, — чтобы не залезть под панель задач, если она сверху.
        free = screen.availableGeometry()
        badge.move(
            free.x() + free.width() - badge.width() - MonitorBadge.MARGIN,
            free.y() + MonitorBadge.MARGIN,
        )
        badge.show()
        badges.append(badge)

    _badges.extend(badges)
    QTimer.singleShot(ms, lambda: [badge.close() for badge in badges])
    return badges


def row(*widgets):
    wrapper = QWidget()
    wrapper.setAcceptDrops(True)
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    for widget in widgets:
        layout.addWidget(widget)
    return wrapper


def stretch():
    filler = QWidget()
    filler.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return filler


def separator():
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setProperty("separator", True)
    return line


# --- запись сочетания клавиш ---

QT_KEY_NAMES = {
    Qt.Key_Return: "Enter",
    Qt.Key_Enter: "Enter",
    Qt.Key_Escape: "Esc",
    Qt.Key_Tab: "Tab",
    Qt.Key_Space: "Space",
    Qt.Key_Backspace: "Backspace",
    Qt.Key_Delete: "Delete",
    Qt.Key_Insert: "Insert",
    Qt.Key_Home: "Home",
    Qt.Key_End: "End",
    Qt.Key_PageUp: "PageUp",
    Qt.Key_PageDown: "PageDown",
    Qt.Key_Up: "Up",
    Qt.Key_Down: "Down",
    Qt.Key_Left: "Left",
    Qt.Key_Right: "Right",
}

# Сами по себе эти клавиши сочетанием не являются — ждём, что нажмут дальше.
MODIFIER_KEYS = {
    Qt.Key_Control, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_Shift, Qt.Key_Meta,
    Qt.Key_CapsLock, Qt.Key_NumLock, Qt.Key_ScrollLock,
}


def qt_key_name(key):
    """Имя клавиши в том виде, в каком его понимает winapi.key_to_vk."""
    if key in QT_KEY_NAMES:
        return QT_KEY_NAMES[key]
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return f"F{key - Qt.Key_F1 + 1}"
    if Qt.Key_A <= key <= Qt.Key_Z:
        return chr(key)
    if Qt.Key_0 <= key <= Qt.Key_9:
        return chr(key)
    return None


class HotkeyEdit(QLineEdit):
    """Поле записи сочетания: нажимаешь — запоминается, но не срабатывает.

    Сигнал captured отдаёт словарь с флагами модификаторов и именем клавиши —
    ровно те ключи, что лежат в параметрах шага.
    """

    captured = Signal(dict)

    WAITING_TEXT = "жду сочетание…"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("щёлкни и нажми сочетание")
        self.setToolTip(
            "Щёлкни в поле и нажми сочетание — оно запишется.\n"
            "Пока идёт запись, клавиатура перехвачена целиком: даже Alt+F4\n"
            "и Win+D сюда попадут, а не сработают."
        )
        self._grabber = None
        self._saved_text = None

    # --- перехват на время записи ---

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._start_grab()

    def focusOutEvent(self, e):
        self._stop_grab()
        super().focusOutEvent(e)

    def hideEvent(self, e):
        # Панель свойств пересобирается при каждом переключении шага —
        # хук не должен пережить своё поле.
        self._stop_grab()
        super().hideEvent(e)

    def _start_grab(self):
        if self._grabber is None:
            try:
                import winapi

                self._grabber = winapi.KeyGrabber(self._on_grabbed)
            except Exception:
                # Не Windows или что-то с ctypes — обойдёмся событиями Qt.
                self._grabber = False

        if self._grabber and self._grabber.start():
            self._saved_text = self.text()
            self.setText(self.WAITING_TEXT)

    def _stop_grab(self):
        if self._grabber:
            self._grabber.stop()
        if self._saved_text is not None:
            self.setText(self._saved_text)
            self._saved_text = None

    def _on_grabbed(self, combo):
        self._saved_text = None
        self.captured.emit(combo)
        # Клавиатуру держим ровно до первого сочетания и сразу отпускаем.
        self.clearFocus()

    # --- запасной путь, когда хук недоступен ---

    def event(self, e):
        # Перехватываем до того, как Qt раздаст нажатие горячим клавишам окна:
        # иначе Ctrl+S, набранный в этом поле, сохранил бы сценарий.
        if e.type() == QEvent.ShortcutOverride:
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        key = e.key()
        if key in MODIFIER_KEYS:
            return

        name = qt_key_name(key)
        if not name:
            return

        mods = e.modifiers()
        self._saved_text = None
        self.captured.emit({
            "ctrl": bool(mods & Qt.ControlModifier),
            "alt": bool(mods & Qt.AltModifier),
            "shift": bool(mods & Qt.ShiftModifier),
            "win": bool(mods & Qt.MetaModifier),
            "key": name,
        })
        e.accept()


SPIN_WIDTH = 72
STEP_BUTTON_WIDTH = 30


def make_spin(minimum, maximum, step=100, width=SPIN_WIDTH):
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setButtonSymbols(QSpinBox.NoButtons)
    # Свой sizeHint у QSpinBox выше, чем разрешает таблица стилей: сам он
    # ужимался до общей высоты, а строка формы оставалась на три пикселя
    # выше соседних. Фиксируем высоту, чтобы hint совпал с фактом.
    spin.setFixedHeight(CONTROL_TOTAL)
    spin.setFixedWidth(width)
    return spin


def spin_row(spin, step=500, unit_text="мс"):
    """Поле числа, единицы измерения и две кнопки быстрого шага."""
    minus = QPushButton("−")
    plus = QPushButton("+")
    for button in (minus, plus):
        button.setFixedWidth(STEP_BUTTON_WIDTH)
        button.setToolTip(f"шаг {step} {unit_text}")

    # setValue сам подрезает по границам диапазона — проверять руками не надо.
    minus.clicked.connect(lambda: spin.setValue(spin.value() - step))
    plus.clicked.connect(lambda: spin.setValue(spin.value() + step))

    return row(spin, unit(unit_text), minus, plus, stretch())


def unit(text="мс"):
    label = QLabel(text)
    label.setStyleSheet("color: palette(mid);")
    return label


# Ширина колонки подписей, общая на все шаги. QFormLayout меряет колонку
# по своей самой длинной подписи, поэтому у «Паузы» она узкая, у закрытия —
# широкая, и поля прыгают вбок при каждом переключении шага.
_label_width = 0


def label_column_width(texts=()):
    """Запоминает самую широкую подпись и отдаёт ширину колонки.

    Ширина только растёт: наткнувшись на подпись длиннее известных, колонка
    один раз расширится и дальше останется прежней. Так забытая в списке
    подпись не обрежется.
    """
    global _label_width
    metrics = QFontMetrics(QApplication.font())
    for text in texts:
        _label_width = max(_label_width, metrics.horizontalAdvance(text))
    return _label_width


def align_form_labels(form):
    """Ставит подписи вровень с текстом в полях и держит ширину колонки.

    QFormLayout выдаёт метке её собственную высоту и прижимает к верху
    строки, а вертикальную часть labelAlignment не смотрит вовсе. Поле выше
    метки на рамку и внутренние отступы, поэтому текст расходится на четыре
    пикселя. Растягиваем метку на высоту строки — тогда AlignVCenter ставит
    её ровно посередине, напротив текста в поле.
    """
    labels = []
    for index in range(form.rowCount()):
        label_item = form.itemAt(index, QFormLayout.LabelRole)
        field_item = form.itemAt(index, QFormLayout.FieldRole)
        if label_item is None or field_item is None:
            continue

        label = label_item.widget()
        if not isinstance(label, QLabel):
            continue

        label.setMinimumHeight(field_item.sizeHint().height())
        # У высокого поля подпись по центру смотрится потерянной —
        # ставим её вровень с первой строкой.
        field = field_item.widget()
        if field is not None and field.property("label_top"):
            label.setAlignment(Qt.AlignRight | Qt.AlignTop)
            label.setContentsMargins(0, 5, 0, 0)
        else:
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        labels.append(label)

    width = label_column_width(label.text() for label in labels)
    for label in labels:
        label.setMinimumWidth(width)


def set_row_enabled(form, field, enabled):
    """Гасит поле вместе с его подписью.

    setEnabled на самом виджете подпись не трогает — получается активный
    текст рядом с серым полем.
    """
    field.setEnabled(enabled)
    label = form.labelForField(field)
    if label is not None:
        label.setEnabled(enabled)

