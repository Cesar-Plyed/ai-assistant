import sys

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Change this to manage separate chat histories/logs per project.
    current_chat_id = "main_project"

    window = MainWindow(chat_id=current_chat_id)
    window.show()

    sys.exit(app.exec())
