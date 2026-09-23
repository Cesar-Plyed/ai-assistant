# ui/hardware_widget.py
"""Live hardware monitor panel (CPU / RAM / Disk / GPU), works on Linux and Windows."""

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QGroupBox

from core import hardware_monitor


def _section_label(text: str) -> QLabel:
    """Small section heading (CPU / RAM / GPU) with an explicit color, since
    an unstyled QLabel falls back to Qt's default palette text color, which
    is nearly invisible against a dark background."""
    label = QLabel(text)
    label.setStyleSheet("color: #9cdcfe; font-weight: bold; font-size: 12px; margin-top: 4px;")
    return label


def _bar(max_value: int = 100) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, max_value)
    bar.setTextVisible(True)
    bar.setStyleSheet("""
        QProgressBar { background-color: #2b2b2b; border: 1px solid #3c3c3c; border-radius: 4px; text-align: center; color: #ffffff; }
        QProgressBar::chunk { background-color: #0e639c; border-radius: 3px; }
    """)
    return bar


class HardwareWidget(QWidget):
    def __init__(self, parent=None, poll_interval_ms: int = 2000):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Hardware Monitor")
        title.setStyleSheet("font-weight: bold; color: #ffffff;")
        layout.addWidget(title)

        self.cpu_bar = _bar()
        self.ram_bar = _bar()
        self.gpu_bar = _bar()
        self.disk_labels: list[QLabel] = []
        self.gpu_label = QLabel("GPU: not detected")
        self.gpu_label.setStyleSheet("color: #aaaaaa; font-size: 11px;")

        layout.addWidget(_section_label("CPU"))
        layout.addWidget(self.cpu_bar)
        layout.addWidget(_section_label("RAM"))
        layout.addWidget(self.ram_bar)
        layout.addWidget(_section_label("GPU"))
        layout.addWidget(self.gpu_bar)
        layout.addWidget(self.gpu_label)

        self.disk_group = QGroupBox("Disks")
        self.disk_group.setStyleSheet(
            "QGroupBox { color: #9cdcfe; font-weight: bold; border: 1px solid #3c3c3c; "
            "border-radius: 4px; margin-top: 10px; padding-top: 12px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        self.disk_layout = QVBoxLayout()
        self.disk_group.setLayout(self.disk_layout)
        layout.addWidget(self.disk_group)
        layout.addStretch()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(poll_interval_ms)
        self.refresh()

    def refresh(self):
        try:
            snapshot = hardware_monitor.get_snapshot()
        except Exception:
            return

        cpu = snapshot["cpu"]
        mem = snapshot["memory"]

        self.cpu_bar.setValue(int(cpu["percent"]))
        self.cpu_bar.setFormat(f"{cpu['percent']:.0f}%  ({cpu['cores_logical']} threads)")

        self.ram_bar.setValue(int(mem["percent"]))
        self.ram_bar.setFormat(f"{mem['used_gb']:.1f} / {mem['total_gb']:.1f} GB")

        if snapshot["gpus"]:
            gpu = snapshot["gpus"][0]
            self.gpu_bar.setValue(int(gpu["utilization_percent"]))
            self.gpu_bar.setFormat(f"{gpu['utilization_percent']:.0f}%")
            self.gpu_label.setText(
                f"{gpu['name']} - {gpu['memory_used_mb']:.0f}/{gpu['memory_total_mb']:.0f} MB - {gpu['temperature_c']:.0f}C"
            )
        else:
            self.gpu_bar.setValue(0)
            self.gpu_bar.setFormat("n/a")
            self.gpu_label.setText("GPU: no supported monitoring tool detected")

        # Rebuild disk rows (cheap: at most a handful of mount points).
        while self.disk_layout.count():
            item = self.disk_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for disk in snapshot["disks"]:
            bar = _bar()
            bar.setValue(int(disk["percent"]))
            bar.setFormat(f"{disk['mountpoint']}: {disk['used_gb']:.0f}/{disk['total_gb']:.0f} GB")
            self.disk_layout.addWidget(bar)