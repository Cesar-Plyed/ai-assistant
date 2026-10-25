import sys

from PySide6.QtWidgets import QApplication

from ui import theme
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    theme.apply_theme(app)
    theme.watch_system_theme(app)

    # Change this to manage separate chat histories per project.
    current_chat_id = "main_project"

    window = MainWindow(chat_id=current_chat_id)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
