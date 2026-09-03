from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from .help_content import HELP


class Card(QFrame):
    def __init__(self, title="", body=""):
        super().__init__(); self.setProperty("card", True); self.layout = QVBoxLayout(self)
        self.title = QLabel(f"<b>{title}</b>"); self.body = QLabel(body); self.body.setWordWrap(True)
        self.layout.addWidget(self.title); self.layout.addWidget(self.body)


class HelpButton(QPushButton):
    helpRequested = Signal(str)

    def __init__(self, help_id):
        super().__init__("?"); self.help_id = help_id; self.setProperty("help", True)
        self.setAccessibleName(f"Ayuda: {HELP[help_id].title}")
        self.setToolTip(HELP[help_id].short_description)
        self.clicked.connect(lambda: self.helpRequested.emit(self.help_id))
