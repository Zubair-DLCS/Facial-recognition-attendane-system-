STYLE = """
QMainWindow, QWidget { font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 10pt; }
QWidget#header { background: #1f4e79; }
QLabel#appname { color: white; font-size: 17pt; font-weight: 600; }
QLabel#credit { color: #d6e4f0; font-size: 9.5pt; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 9px 20px; margin-right: 2px; background: #e8edf3; color: #333;
               border-top-left-radius: 6px; border-top-right-radius: 6px; }
QTabBar::tab:selected { background: white; color: #1f4e79; font-weight: 600; }
QGroupBox { border: 1px solid #d5dce4; border-radius: 6px; margin-top: 12px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #1f4e79; font-weight: 600; }
QPushButton { padding: 6px 14px; border: 1px solid #b8c4d0; border-radius: 5px; background: #f6f8fa; }
QPushButton:hover { background: #eaf1f8; }
QPushButton:disabled { color: #9aa5b1; background: #f1f3f5; }
QPushButton#primary { background: #1f6fb2; color: white; border-color: #1a5e98; }
QPushButton#primary:hover { background: #1a5e98; }
QPushButton#primary:disabled { background: #a9c3da; border-color: #a9c3da; }
QPushButton#success { background: #2e8b57; color: white; border-color: #26744a; font-weight: 600; }
QPushButton#success:disabled { background: #b9d8c6; }
QPushButton#danger { color: #b02a2a; }
QPushButton:checked { background: #dbe8f5; }
QLabel#video { background: #10161d; color: #8fa1b3; border-radius: 6px; font-size: 12pt; }
QLabel#muted { color: #66717c; }
QLabel#hint { color: #1f4e79; font-weight: 600; padding: 4px 0; }
QLabel#counter { font-size: 14pt; font-weight: 600; color: #2e8b57; }
QLabel#flash { font-size: 14pt; font-weight: 600; color: #2e8b57; min-height: 28px; }
QTableWidget { gridline-color: #e3e7eb; selection-background-color: #cfe2f5; selection-color: black; }
QHeaderView::section { background: #eef2f6; padding: 5px; border: none; border-right: 1px solid #dde3e9;
                       font-weight: 600; }
QStatusBar { color: #66717c; }
"""
