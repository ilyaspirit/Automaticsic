import psutil

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QDialogButtonBox,
)


class ProcessPicker(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Запущенные процессы")
        self.resize(680, 460)
        self.selected = None
        self.selected_name = None
        self.shown = []

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Фильтр по имени или пути")
        self.filter.textChanged.connect(self._apply_filter)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Процесс", "PID", "Путь"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.accept)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 380)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Выбрать")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.filter)
        layout.addWidget(self.table)
        layout.addWidget(buttons)

        self.rows = self._collect()
        self._fill(self.rows)

    def _collect(self):
        seen = {}
        for proc in psutil.process_iter(["name", "pid", "exe"]):
            try:
                name = proc.info["name"] or ""
                exe = proc.info["exe"] or ""
            except psutil.Error:
                continue

            if not name:
                continue

            key = name.lower()
            # Путь Windows отдаёт не про всякий процесс: у запущенных от
            # администратора или от системы читать его не даёт. Раньше такие
            # процессы просто выбрасывались из списка — программа была
            # в диспетчере задач, а здесь её не было. Имя доступно всегда,
            # и для закрытия, окон и хоткеев хватает именно имени.
            known = seen.get(key)
            if known is None or (exe and not known[2]):
                seen[key] = (name, proc.info["pid"], exe)

        return sorted(seen.values(), key=lambda r: r[0].lower())

    def _fill(self, rows):
        self.shown = rows
        self.table.setRowCount(len(rows))
        for index, (name, pid, exe) in enumerate(rows):
            self.table.setItem(index, 0, QTableWidgetItem(name))
            self.table.setItem(index, 1, QTableWidgetItem(str(pid)))
            self.table.setItem(index, 2, QTableWidgetItem(exe or "путь недоступен"))

    def _apply_filter(self, text):
        needle = text.strip().lower()
        if not needle:
            self._fill(self.rows)
            return
        self._fill([
            r for r in self.rows
            if needle in r[0].lower() or needle in (r[2] or "").lower()
        ])

    def accept(self):
        row_index = self.table.currentRow()
        if 0 <= row_index < len(self.shown):
            # Берём из данных, а не из ячейки: там может стоять
            # «путь недоступен».
            self.selected_name, _, self.selected = self.shown[row_index]
        super().accept()