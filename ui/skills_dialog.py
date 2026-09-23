"""Skills manager dialog: enable/disable discovered skills and install new ones."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QLabel, QMessageBox, QFileDialog,
)
from PyQt6.QtCore import Qt

import config
from core import skills_manager


class SkillsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Skills")
        self.resize(480, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Installed skills - check to enable a skill's tools for the assistant:"))

        self.skill_list = QListWidget()
        layout.addWidget(self.skill_list)

        install_row = QHBoxLayout()
        self.install_folder_button = QPushButton("Install from folder...")
        self.install_folder_button.clicked.connect(self._install_from_folder)
        self.install_zip_button = QPushButton("Install from .zip...")
        self.install_zip_button.clicked.connect(self._install_from_zip)
        install_row.addWidget(self.install_folder_button)
        install_row.addWidget(self.install_zip_button)
        layout.addLayout(install_row)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.save_button = QPushButton("Save and close")
        self.save_button.clicked.connect(self._save_and_close)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.save_button)
        layout.addLayout(bottom)

        self._refresh()

    def _refresh(self):
        self.skill_list.clear()
        for skill in skills_manager.discover_skills():
            text = f"{skill['name']}  (v{skill['version']}) - {skill['description']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, skill["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if skill["enabled"] else Qt.CheckState.Unchecked)
            self.skill_list.addItem(item)

    def _install_from_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select skill folder (must contain skill.json and skill.py)")
        if not folder:
            return
        result = skills_manager.install_skill_from_folder(folder)
        QMessageBox.information(self, "Install skill", result)
        self._refresh()

    def _install_from_zip(self):
        zip_path, _ = QFileDialog.getOpenFileName(self, "Select skill .zip", filter="Zip archives (*.zip)")
        if not zip_path:
            return
        result = skills_manager.install_skill_from_zip(zip_path)
        QMessageBox.information(self, "Install skill", result)
        self._refresh()

    def _save_and_close(self):
        enabled_ids = []
        for i in range(self.skill_list.count()):
            item = self.skill_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                enabled_ids.append(item.data(Qt.ItemDataRole.UserRole))

        settings = dict(config.SETTINGS)
        settings["enabled_skills"] = enabled_ids
        config.save_settings(settings)
        config.reload_settings()
        self.accept()
