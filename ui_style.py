from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

CONTROL_HEIGHT = 26
# Полная высота поля: содержимое плюс отступы 2+2 и рамка 1+1.
CONTROL_TOTAL = CONTROL_HEIGHT + 6
BORDER = "#d4d4d4"
BORDER_FOCUS = "#9a9a9a"
HOVER = "#ececec"
PRESSED = "#dcdcdc"
READONLY = "#f4f4f4"

# Скругление углов. Тройка выглядела обкусанной: на такой радиус приходится
# два-три пикселя дуги, и сглаживание не успевает её сгладить. Четыре даёт
# заметно ровнее, а круглее уже не нужно.
RADIUS = 4

# Цвет взят из icon.png: круг залит градиентом от #5ae6ff сверху
# к #066aff снизу. Берём нижний, глубокий, и затемняем на четверть —
# так белый текст на заливке читается уверенно, контраст 7.2.
ACCENT = "#0550bf"
ACCENT_TEXT = "#ffffff"
ACCENT_FADED = "#b3d1ff"

# Отключённый шаг под выделением: на синей заливке серый цвет отключённого
# текста (#a0a0a0) тонет — контраст 2.8. Этот светлее, контраст 4.2:
# видно, что шаг приглушён, и название всё ещё читается.
DISABLED_ON_ACCENT = "#c4c4c4"

LIGHT_COLORS = {
    QPalette.Window: "#f0f0f0",
    QPalette.WindowText: "#1a1a1a",
    QPalette.Base: "#ffffff",
    QPalette.AlternateBase: "#f2f6fc",
    QPalette.Text: "#1a1a1a",
    QPalette.Button: "#fbfbfb",
    QPalette.ButtonText: "#1a1a1a",
    QPalette.Light: "#ffffff",
    QPalette.Midlight: "#e8e8e8",
    QPalette.Mid: "#8a8a8a",
    QPalette.Dark: "#9a9a9a",
    QPalette.Shadow: "#d0d0d0",
    QPalette.Highlight: ACCENT,
    QPalette.HighlightedText: ACCENT_TEXT,
    QPalette.ToolTipBase: "#ffffff",
    QPalette.ToolTipText: "#1a1a1a",
    QPalette.PlaceholderText: "#9a9a9a",
    QPalette.Link: ACCENT,
}

DISABLED_COLORS = {
    QPalette.WindowText: "#a0a0a0",
    QPalette.Text: "#a0a0a0",
    QPalette.ButtonText: "#a0a0a0",
}


def light_palette():
    palette = QPalette()
    for role, value in LIGHT_COLORS.items():
        palette.setColor(role, QColor(value))
    for role, value in DISABLED_COLORS.items():
        palette.setColor(QPalette.Disabled, role, QColor(value))
    return palette


def apply_light_theme(app):
    """Держит светлое оформление независимо от системной темы.

    Qt на Windows по умолчанию следует теме системы: в тёмной палитра
    становится тёмной. Наши же рамки, фон лога и цвет выделения прописаны
    числами и светлыми остаются — вышла бы каша из тёмных и светлых кусков.
    Проще зафиксировать светлую тему, чем поддерживать обе.
    """
    hints = app.styleHints()
    scheme = getattr(Qt, "ColorScheme", None)
    if scheme is not None and hasattr(hints, "setColorScheme"):
        hints.setColorScheme(scheme.Light)
    app.setPalette(light_palette())

STYLE = f"""
QLineEdit, QSpinBox, QComboBox, QPushButton {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    padding: 2px 6px;
    min-height: {CONTROL_HEIGHT}px;
    max-height: {CONTROL_HEIGHT}px;
}}
QPushButton {{
    padding: 2px 12px;
    background: palette(button);
}}
QPushButton:hover {{
    border: 1px solid {BORDER_FOCUS};
}}
QPushButton:pressed {{
    background: palette(midlight);
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {BORDER_FOCUS};
}}
QComboBox {{
    padding-right: 22px;
}}
QComboBox::drop-down {{
    width: 22px;
    border: none;
    background: transparent;
    /* Кнопка стрелки сидит вплотную к правому краю и без своих скруглений
       срезала бы углы поля — правый верхний в первую очередь. */
    border-top-right-radius: {RADIUS}px;
    border-bottom-right-radius: {RADIUS}px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
}}
QComboBox QAbstractItemView {{
    border: 1px solid {BORDER};
    background: palette(base);
    outline: none;
    padding: 2px;
}}
QComboBox QAbstractItemView::item {{
    min-height: 22px;
    padding: 0 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {BORDER};
    /* Галка вдвое ниже поля, и общий радиус на ней смотрелся бы кругляшом. */
    border-radius: 3px;
    background: palette(base);
}}
QCheckBox::indicator:hover {{
    border: 1px solid {ACCENT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}
QCheckBox::indicator:disabled {{
    background: {READONLY};
    border: 1px solid {BORDER};
}}
QCheckBox::indicator:checked:disabled {{
    background: {ACCENT_FADED};
    border: 1px solid {ACCENT_FADED};
}}
QSpinBox {{
    padding-left: 4px;
    padding-right: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 0;
    border: none;
    background: transparent;
}}
QToolBar {{
    padding: 1px 4px;
    spacing: 2px;
    border: none;
    border-bottom: 1px solid {BORDER};
}}
QToolBar QToolButton {{
    padding: 2px 6px;
    border: none;
    border-radius: {RADIUS}px;
}}
QToolBar QToolButton:hover {{
    background: {HOVER};
}}
QToolBar QToolButton:pressed {{
    background: {PRESSED};
}}
QToolBar::separator {{
    background: {BORDER};
    width: 1px;
    margin: 4px 8px;
}}
QListWidget {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    background: palette(base);
}}
QPlainTextEdit {{
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
    background: {READONLY};
    color: palette(text);
    padding: 2px;
}}
QPlainTextEdit[editable="true"] {{
    background: palette(base);
}}
QPlainTextEdit[editable="true"]:focus {{
    border: 1px solid {BORDER_FOCUS};
}}
QStatusBar {{
    border-top: 1px solid {BORDER};
    background: transparent;
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    color: palette(mid);
    padding: 1px 4px;
}}
QSplitter::handle {{
    background: transparent;
}}
QFrame[separator="true"] {{
    background: {BORDER};
    max-height: 1px;
    border: none;
}}
"""