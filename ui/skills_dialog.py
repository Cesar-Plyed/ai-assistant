"""Skills manager dialog: enable/disable discovered skills and install new ones."""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QLabel, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt

import config
from core import skills_manager



class SkillsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Skills")
        self.resize(480, 420)


        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addWidget(QLabel("Installed skills — check to enable a skill's tools for the assistant:"))

        self.skill_list = QListWidget()
        self.skill_list.setAccessibleName("Installed skills")
        self.skill_list.currentItemChanged.connect(lambda *_: self._update_detail())
        layout.addWidget(self.skill_list)
        self.detail_label = QLabel("")
        self.detail_label.setWordWrap(True)
        self.detail_label.setProperty("muted", True)
        layout.addWidget(self.detail_label)

        install_row = QHBoxLayout()
        install_row.setSpacing(8)
        self.install_folder_button = QPushButton("Install from folder...")
        self.install_folder_button.clicked.connect(self._install_from_folder)
        self.install_zip_button = QPushButton("Install from .zip...")
        self.install_zip_button.clicked.connect(self._install_from_zip)
        install_row.addWidget(self.install_folder_button)
        self.migrate_button = QPushButton("Migrate legacy…")
        self.migrate_button.clicked.connect(self._migrate_selected)
        install_row.addWidget(self.install_zip_button)
        install_row.addWidget(self.migrate_button)
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
            errors = [i for i in skill.issues if i.level == "error"]
            warnings = [i for i in skill.issues if i.level == "warning"]
            badge = "✖ invalid" if errors else ("⚠ " + ("legacy" if skill.legacy else "warnings") if warnings else "✔ valid")
            text = f"{skill.name}  (v{skill.version})  [{badge}] — {skill.description}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, skill.id)
            flags = item.flags() | Qt.ItemFlag.ItemIsUserCheckable
            if errors:
                flags &= ~Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags)
            if not errors:
                item.setCheckState(Qt.CheckState.Checked if skill.enabled else Qt.CheckState.Unchecked)
            details = [f"{i}" for i in skill.issues]
            if skill.allowed_tools:
                details.append("allowed-tools: " + ", ".join(skill.allowed_tools))
            if skill.read_only:
                details.append("read-only")
            item.setToolTip("\n".join(details) or "No issues found.")
            self.skill_list.addItem(item)
        self._update_detail()

    def _update_detail(self):
        item = self.skill_list.currentItem()
        if item is None:
            self.detail_label.setText("")
            return
        self.detail_label.setText(item.toolTip())

    def _confirm_install(self, summary: dict) -> bool:
        lines = [
            f"Name: {summary['name']}",
            f"Description: {summary['description'] or '—'}",
            f"Allowed tools: {', '.join(summary['allowed_tools']) or '—'}",
            f"Read-only: {'yes' if summary['read_only'] else 'no'}",
            f"Includes Python code (skill.py): {'YES — it runs when enabled' if summary['has_code'] else 'no'}",
            f"SHA-256: {summary['sha256']}",
        ]
        if summary["issues"]:
            lines.append("Warnings:\n  " + "\n  ".join(summary["issues"]))
        answer = QMessageBox.question(
            self, "Install skill?", "\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _install_from_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select skill folder (must contain SKILL.md)")
        if not folder:
            return
        result = skills_manager.install_skill_from_folder(folder, confirm=self._confirm_install)
        QMessageBox.information(self, "Install skill", result)
        self._refresh()

    def _install_from_zip(self):
        zip_path, _ = QFileDialog.getOpenFileName(self, "Select skill .zip", filter="Zip archives (*.zip)")
        if not zip_path:
            return
        result = skills_manager.install_skill_from_zip(zip_path, confirm=self._confirm_install)
        QMessageBox.information(self, "Install skill", result)
        self._refresh()

    def _migrate_selected(self):
        item = self.skill_list.currentItem()
        if item is None:
            return
        QMessageBox.information(self, "Migrate skill",
                                skills_manager.migrate_legacy_skill(item.data(Qt.ItemDataRole.UserRole)))
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
