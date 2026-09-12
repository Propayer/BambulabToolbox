"""Shared Nebu v1.1 desktop tokens: hierarchy, restrained surfaces and focus."""
from PySide6.QtGui import QColor,QPalette


def nebu_palette():
    p=QPalette()
    for role,color in [(QPalette.Window,'#10191D'),(QPalette.WindowText,'#F2F6F4'),(QPalette.Base,'#1B282E'),
                       (QPalette.AlternateBase,'#25363E'),(QPalette.Text,'#F2F6F4'),(QPalette.Button,'#1B282E'),
                       (QPalette.ButtonText,'#F2F6F4'),(QPalette.Highlight,'#72E2C0'),(QPalette.HighlightedText,'#10191D'),
                       (QPalette.Mid,'#43555E'),(QPalette.ToolTipBase,'#25363E'),(QPalette.ToolTipText,'#F2F6F4')]:p.setColor(role,QColor(color))
    p.setColor(QPalette.Disabled,QPalette.Text,QColor('#81949C'))
    p.setColor(QPalette.Disabled,QPalette.ButtonText,QColor('#81949C'))
    return p


APP_STYLESHEET = """
QWidget { font-family: 'Ubuntu', 'Segoe UI'; font-size: 14px; color: #F2F6F4; }
QMainWindow, QWidget#appRoot, QStackedWidget#workspace { background: #10191D; }
QLabel { background: transparent; }
QLabel[role='pageTitle'] { font-size: 30px; font-weight: 600; }
QLabel[role='eyebrow'] { color: #72E2C0; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel[role='muted'] { color: #A9BABF; font-size: 13px; }
QLabel[role='bodyStrong'] { font-weight: 600; font-size: 13px; }
QLabel[role='warning'] { color: #F1C36A; font-size: 13px; }
QLabel[role='badge'] { color: #BBAAFF; background: #25363E; border-radius: 6px; padding: 6px 10px; font-size: 10px; font-weight: 600; }
QLabel[role='status'] { color: #A9BABF; font-size: 13px; }
QFrame[card='true'], QFrame#fileBar { background: #1B282E; border: 1px solid #34464E; border-radius: 12px; }
QFrame#exportBar { background: #1B282E; border: 1px solid #43555E; border-radius: 12px; }
QPushButton { min-height: 30px; border: 1px solid #81949C; border-radius: 8px; padding: 5px 12px; background: #1B282E; font-weight: 500; }
QPushButton:hover { background: #25363E; border-color: #72E2C0; }
QPushButton:pressed { background: #34464E; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border: 1px solid #72E2C0; }
QPushButton[primary='true'] { background: #72E2C0; border-color: #72E2C0; color: #10191D; font-weight: 600; }
QPushButton[primary='true']:hover { background: #94EACE; }
QPushButton:disabled { background: #25363E; color: #81949C; border-color: #34464E; }
QPushButton[quiet='true'] { background: transparent; border-color: #43555E; font-size: 13px; }
QPushButton[quiet='true']:hover, QPushButton[quiet='true']:checked { background: #25363E; border-color: #72E2C0; color: #72E2C0; }
QPushButton[selectable='true']:checked { border: 2px solid #72E2C0; font-weight: 600; }
QPushButton[help='true'] { min-width: 24px; max-width: 24px; min-height: 30px; padding: 5px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
 border: 1px solid #81949C; border-radius: 8px; padding: 7px; background: #142126; selection-background-color: #72E2C0; selection-color: #10191D;
}
QComboBox { min-height: 26px; padding-right: 26px; }
QComboBox::drop-down { width: 22px; border: 0; }
QDoubleSpinBox { min-height: 24px; }
QProgressBar { min-height: 4px; max-height: 4px; border: 0; background: #34464E; border-radius: 2px; }
QProgressBar::chunk { background: #72E2C0; border-radius: 2px; }
QToolTip { padding: 8px; color: #F2F6F4; background: #25363E; border: 1px solid #81949C; }
QListWidget { border: 0; background: transparent; padding: 0; outline: 0; }
QListWidget::item { padding: 8px; margin: 2px 0; border-radius: 8px; }
QListWidget::item:selected { background: #25363E; color: #72E2C0; }
QListWidget::item:hover { background: #1B282E; }
QListWidget#zoneList { background: #142126; border-radius: 8px; }
QListWidget#navigation::item { min-height: 32px; padding: 8px 12px; border-left: 3px solid transparent; }
QListWidget#navigation::item:selected { border-left: 3px solid #72E2C0; background: #25363E; }
QWidget#sidebar { background: #142126; border-right: 1px solid #26383F; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 0; }
QScrollBar::handle:vertical { background: #43555E; min-height: 28px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #A9BABF; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical { background: transparent; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: transparent; color: #A9BABF; padding: 12px 16px; border-bottom: 2px solid #34464E; }
QTabBar::tab:selected { color: #72E2C0; border-bottom: 2px solid #72E2C0; }
QTabBar::tab:hover { color: #F2F6F4; }
QHeaderView::section { background: #25363E; color: #F2F6F4; padding: 8px; border: 1px solid #43555E; }
"""
