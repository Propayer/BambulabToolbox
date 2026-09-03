from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QPushButton, QVBoxLayout, QWidget)
from .components import Card
from .help_content import HELP, search_help


class HelpPanel(Card):
    closed = Signal()

    def __init__(self):
        super().__init__("Ayuda", "Selecciona una opción para ver su ayuda.")
        self.close_button = QPushButton("Cerrar"); self.close_button.clicked.connect(self.closed)
        self.layout.addWidget(self.close_button)

    def show_help(self, help_id):
        item = HELP[help_id]; self.title.setText(f"<h3>{item.title}</h3>")
        text = f"{item.detailed_description}<br><br><b>Recomendación</b><br>{item.recommendations}"
        if item.example: text += f"<br><br><b>Ejemplo</b><br>{item.example}"
        self.body.setText(text); self.show()


class GuideWidget(QWidget):
    def __init__(self):
        super().__init__(); layout = QVBoxLayout(self); self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar en la ayuda..."); layout.addWidget(self.search)
        row = QHBoxLayout(); self.topics = QListWidget(); self.panel = HelpPanel()
        row.addWidget(self.topics, 1); row.addWidget(self.panel, 3); layout.addLayout(row)
        self.search.textChanged.connect(self.filter_topics)
        self.topics.currentRowChanged.connect(self.select_topic); self.filter_topics("")

    def filter_topics(self, text):
        self.filtered = search_help(text); self.topics.clear()
        self.topics.addItems([item.title for item in self.filtered])
        if self.filtered: self.topics.setCurrentRow(0)

    def select_topic(self, row):
        if 0 <= row < len(self.filtered): self.panel.show_help(self.filtered[row].id)
