APP_STYLESHEET = """
QWidget { font-family: 'Segoe UI'; font-size: 10.5pt; }
QMainWindow, QWidget#page { background: palette(window); }
QFrame[card='true'] { border: 1px solid palette(mid); border-radius: 12px; padding: 12px; background: palette(base); }
QPushButton { min-height: 34px; border-radius: 8px; padding: 4px 12px; }
QPushButton[primary='true'] { background: palette(highlight); color: palette(highlighted-text); font-weight: 600; }
QPushButton[selectable='true']:checked { border: 2px solid palette(highlight); font-weight: 600; }
QPushButton[help='true'] { min-width: 28px; max-width: 28px; min-height: 28px; border-radius: 14px; }
QProgressBar { min-height: 10px; max-height: 10px; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: palette(highlight); border-radius: 5px; }
QToolTip { padding: 8px; max-width: 360px; }
QListWidget { border: 0; padding: 8px; }
QListWidget::item { padding: 11px; border-radius: 8px; }
QListWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }
"""
