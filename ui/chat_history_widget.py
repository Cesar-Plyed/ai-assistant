from datetime import datetime
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QMenu, QInputDialog, QMessageBox,
)

from core import memory
from ui.icons import get_icon


class ChatHistoryWidget(QWidget):
    """Sidebar widget to list, switch, create, rename, and delete chat sessions."""
    chat_selected = pyqtSignal(str)

    def __init__(self, current_chat_id: str, parent=None):
        super().__init__(parent)
        self.current_chat_id = current_chat_id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel("Chat History")
        title.setStyleSheet("font-weight: bold; color: #ffffff;")
        self.new_chat_button = QPushButton()
        self.new_chat_button.setIcon(get_icon("plus"))
        self.new_chat_button.setToolTip("Start a new chat")
        self.new_chat_button.clicked.connect(self._create_new_chat)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.new_chat_button)
        layout.addLayout(header)

        self.chat_list = QListWidget()
        self.chat_list.itemClicked.connect(self._on_item_clicked)
        self.chat_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.chat_list)

        self.refresh()

    def refresh(self):
        """Refreshes chat list items from storage."""
        self.chat_list.clear()
        chats = memory.list_chats()

        known_ids = {c["id"] for c in chats}
        if self.current_chat_id not in known_ids:
            chats.insert(0, {"id": self.current_chat_id, "message_count": 0, "last_updated": None})

        for chat in chats:
            label = chat["id"]
            if chat["message_count"]:
                label
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, chat["id"])
            self.chat_list.addItem(item)
            
            if chat["id"] == self.current_chat_id:
                item.setSelected(True)
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                self.chat_list.setCurrentItem(item)

    def _on_item_clicked(self, item: QListWidgetItem):
        chat_id = item.data(Qt.ItemDataRole.UserRole)
        if chat_id and chat_id != self.current_chat_id:
            self.current_chat_id = chat_id
            self.chat_selected.emit(chat_id)
            self.refresh()

    def _create_new_chat(self):
        suggested = f"chat_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        new_id, ok = QInputDialog.getText(self, "New Chat", "Enter chat name:", text=suggested)
        if not ok or not new_id.strip():
            return
        new_id = new_id.strip().replace(" ", "_")
        memory.save_chat(new_id, [])   # <-- so a file exists on disk
        self.current_chat_id = new_id
        self.chat_selected.emit(new_id)
        self.refresh()

    def _show_context_menu(self, position):
        item = self.chat_list.itemAt(position)
        if not item:
            return
        chat_id = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        rename_action = menu.addAction(get_icon("edit"), "Rename chat")
        delete_action = menu.addAction(get_icon("trash"), "Delete chat")

        chosen_action = menu.exec(self.chat_list.mapToGlobal(position))

        if chosen_action == rename_action:
            new_id, ok = QInputDialog.getText(self, "Rename Chat", "New chat name:", text=chat_id)
            if ok and new_id.strip() and new_id.strip() != chat_id:
                sanitized_id = new_id.strip().replace(" ", "_")
                if memory.rename_chat(chat_id, sanitized_id):
                    if chat_id == self.current_chat_id:
                        self.current_chat_id = sanitized_id
                        self.chat_selected.emit(sanitized_id)
                    self.refresh()
                else:
                    QMessageBox.warning(
                        self, "Rename failed",
                        f"Could not rename '{chat_id}' to '{sanitized_id}'.\n\n"
                        "A chat with that name may already exist.",
                    )
        elif chosen_action == delete_action:
            if chat_id == self.current_chat_id:
                QMessageBox.warning(
                    self, "Cannot Delete",
                    "Switch to another chat before deleting this one.",
                )
                return
            confirm = QMessageBox.question(
                self, "Delete Chat",
                f"Delete '{chat_id}'? This action cannot be undone.",
            )
            if confirm == QMessageBox.StandardButton.Yes:
                if memory.delete_chat(chat_id):
                    self.refresh()
                else:
                    QMessageBox.warning(
                        self, "Delete failed",
                        f"Could not delete '{chat_id}'. The file may have been moved or renamed.",
                    )