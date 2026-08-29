import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSystemTrayIcon,
)

import model
import runner
import settings
import winapi
from ui_style import BORDER, READONLY, apply_light_theme
from ui_widgets import step_icon

ERROR_COLOR = "#c0392b"
MAX_HEIGHT = 16777215  # QWIDGETSIZE_MAX — снимает ограничение высоты

STYLE = f"""
QWidget#card {{
    background: palette(base);
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QLabel#name {{
    font-weight: bold;
}}
QLabel#counter {{
    color: palette(mid);
}}
QLabel#result {{
    color: {ERROR_COLOR};
}}
QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {READONLY};
}}
QProgressBar::chunk {{
    background: palette(highlight);
    border-radius: 2px;
}}
QPushButton {{
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 3px 10px;
    background: palette(button);
}}
QPushButton:hover {{
    border: 1px solid #9a9a9a;
}}
"""


class ProgressWindow(QWidget):
    """Окно хода выполнения у самого трея.

    Не системный пузырь: тот живёт по своим правилам, исчезает когда хочет
    и не умеет показывать прогресс. Это обычное окно без рамки, поставленное
    в угол рабочей области.
    """

    # Колонка под значок шага плюс отступ — ровно на столько окно и шире,
    # чем было: иначе значок отъел бы место у названия, и длинные шаги
    # начали бы резаться раньше прежнего.
    WIDTH = 320 + 16 + 8
    MARGIN = 12

    def __init__(self, name):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool,
        )
        # Фокус окно забирать не должно: сценарий шлёт клавиши в активное
        # окно, и если фокус уедет сюда, они уйдут не туда.
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        self.setStyleSheet(STYLE)
        self.setFixedWidth(self.WIDTH)

        self.stop_requested = False
        self.finished = False

        badge = QLabel()
        badge.setPixmap(QIcon(model.icon_path()).pixmap(20, 20))
        badge.setFixedSize(20, 20)

        self.name = QLabel(name)
        self.name.setObjectName("name")

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        header.addWidget(badge)
        header.addWidget(self.name)
        header.addStretch()

        self.counter = QLabel("")
        self.counter.setObjectName("counter")

        self.current = QLabel("")
        self.current.setWordWrap(True)
        # Место под две строки резервируем сразу: иначе окно меняет высоту
        # от длины названия шага и дёргается на каждом переходе.
        block = self.current.fontMetrics().height() * 2 + 2
        self.current.setFixedHeight(block)

        # Значок шага — тот же, что в списке редактора. Блок ему даём такой
        # же высоты, как метке названия, и центруем так же. Иначе они не
        # сойдутся: метка по умолчанию ставит текст по центру своего блока,
        # а название почти всегда в одну строку из двух отведённых — значок,
        # прижатый к верху, оказывался выше текста на полстроки.
        self.step_badge = QLabel()
        self.step_badge.setFixedSize(16, block)
        self.step_badge.setAlignment(Qt.AlignCenter)

        current_row = QHBoxLayout()
        current_row.setContentsMargins(0, 0, 0, 0)
        current_row.setSpacing(8)
        current_row.addWidget(self.step_badge, 0)
        current_row.addWidget(self.current, 1)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)

        self.button = QPushButton("Прервать")
        self.button.clicked.connect(self._on_button)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.addStretch()
        bottom.addWidget(self.button)

        card = QWidget()
        card.setObjectName("card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 12, 14, 12)
        inner.setSpacing(6)
        inner.addLayout(header)
        inner.addWidget(self.counter)
        inner.addLayout(current_row)
        inner.addWidget(self.bar)
        inner.addLayout(bottom)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

    # --- размещение ---

    def show_at_tray(self):
        self.show()
        self._fit()

    # --- ход выполнения ---

    def set_step(self, index, total, title, step=None):
        self.bar.setRange(0, total)
        self.bar.setValue(index)
        self.counter.setText(f"Шаг {index} из {total}")
        self.current.setText(title)
        self._set_badge(step)
        self._refresh()

    def _set_badge(self, step):
        icon = step_icon(step) if step else None
        if icon is None:
            self.step_badge.clear()
        else:
            self.step_badge.setPixmap(icon.pixmap(16, 16))

    def set_result(self, text, failed=False):
        self.counter.setText(text)
        self.counter.setObjectName("result" if failed else "counter")
        # Смена objectName требует пересчёта стиля — иначе цвет не поменяется.
        self.counter.setStyleSheet("")

        # Кнопка не исчезает, а меняет смысл: прерывать уже нечего,
        # зато окном можно распорядиться, не дожидаясь таймера.
        self.finished = True
        self.button.setText("Закрыть")
        self.button.setEnabled(True)

        if not failed:
            self.bar.setValue(self.bar.maximum())
        self._refresh()

    def set_error(self, text):
        # У ошибки своей программы нет, а чужой значок рядом с красным
        # текстом читался бы как «это она виновата».
        self.step_badge.clear()
        self.current.setText(text)
        self.current.setStyleSheet(f"color: {ERROR_COLOR};")
        # Здесь высота меняется по делу: полоса уходит, а текст ошибки
        # бывает длиннее двух строк.
        self.current.setMinimumHeight(0)
        self.current.setMaximumHeight(MAX_HEIGHT)
        self.bar.hide()
        self._fit()

    def _refresh(self):
        # Размер не трогаем: он задан при показе и меняться не должен.
        QApplication.processEvents()

    def _fit(self):
        self.adjustSize()
        # availableGeometry уже без панели задач, поэтому окно встаёт
        # ровно над треем и ничего не перекрывает.
        area = QApplication.primaryScreen().availableGeometry()
        self.move(
            area.right() - self.width() - self.MARGIN,
            area.bottom() - self.height() - self.MARGIN,
        )
        QApplication.processEvents()

    # --- прерывание ---

    def _on_button(self):
        if self.finished:
            QApplication.quit()
            return

        self.stop_requested = True
        self.button.setEnabled(False)
        self.counter.setText("Останавливаюсь…")
        self._refresh()

    def should_stop(self):
        QApplication.processEvents()
        return self.stop_requested



def run_script_file(path):
    """Выполняет сценарий, показывая значок в трее и окно хода выполнения."""
    app = QApplication.instance() or QApplication(sys.argv)
    apply_light_theme(app)
    winapi.set_app_id()

    icon = QIcon(model.icon_path())
    app.setWindowIcon(icon)

    file_name = os.path.basename(path)

    tray = QSystemTrayIcon(icon)
    tray.setToolTip(f"{model.APP_NAME} — {file_name}")
    tray.show()

    try:
        script = model.load_script(path)
    except Exception as e:
        window = ProgressWindow(file_name)
        window.show_at_tray()
        window.set_result("Не удалось прочитать файл", failed=True)
        window.set_error(str(e))
        _linger(app, 8000)
        return 1

    window = ProgressWindow(script.get("name") or file_name)
    window.show_at_tray()

    log = runner.Log(lambda line, level: None)
    ok = runner.run_script(
        script, log, path,
        should_stop=window.should_stop,
        on_progress=window.set_step,
    )

    if ok:
        window.set_result("Готово")
        _linger(app, 1500)
        return 0

    log_path = log.dump_to_file(path) if settings.get("write_log") else None

    if window.stop_requested:
        window.set_result("Прервано")
        _linger(app, 2000)
        return 1

    window.set_result("Ошибка", failed=True)
    text = log.last_error or "Сценарий завершился с ошибкой"
    if log_path:
        text += f"\nЛог: {os.path.basename(log_path)}"
    window.set_error(text)
    _linger(app, 8000)
    return 1


def _linger(app, ms):
    """Держит окно на экране, пока пользователь читает результат."""
    QTimer.singleShot(ms, app.quit)
    app.exec()
