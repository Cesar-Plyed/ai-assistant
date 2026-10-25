# ui/hardware_widget.py
"""Live hardware monitor panel (CPU / RAM / GPU), works on Linux, Windows and macOS."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar

from core import hardware_monitor

from ui import theme


def _bar_color(percent: int) -> str:
    """Return a severity-based color for the progress bar fill."""
    t = theme.tokens()
    if percent >= 90:
        return t["error"]
    if percent >= 70:
        return t["warning"]
    return t["success"]


def _section_label(text: str) -> QLabel:
    """Small muted section heading (CPU / RAM / GPU)."""
    label = QLabel(text)
    label.setProperty("muted", True)
    label.setStyleSheet("font-weight: 600; font-size: 11px; margin-top: 8px;")
    return label


def _bar(max_value: int = 100) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, max_value)
    bar.setTextVisible(True)
    return bar


def _update_bar(bar: QProgressBar, percent: int):
    """Update value; only restyle the chunk when the severity colour changes."""
    bar.setValue(percent)
    color = _bar_color(percent)
    if bar.property("_chunk_color") != color:
        bar.setProperty("_chunk_color", color)
        bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}")


class HardwareWidget(QWidget):
    def __init__(self, parent=None, poll_interval_ms: int = 2000):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        title = QLabel("Hardware Monitor")
        title.setStyleSheet("font-weight: 600; font-size: 14px; margin-bottom: 8px;")
        layout.addWidget(title)

        self.cpu_bar = _bar()
        self.ram_bar = _bar()
        self.gpu_bar = _bar()
        self.gpu_label = QLabel("GPU: not detected")
        self.gpu_label.setProperty("muted", True)
        self.gpu_label.setStyleSheet("font-size: 11px; margin-top: 4px;")

        layout.addWidget(_section_label("CPU"))
        layout.addWidget(self.cpu_bar)
        layout.addWidget(_section_label("RAM"))
        layout.addWidget(self.ram_bar)
        layout.addWidget(_section_label("GPU"))
        layout.addWidget(self.gpu_bar)
        layout.addWidget(self.gpu_label)

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

        _update_bar(self.cpu_bar, int(cpu["percent"]))
        self.cpu_bar.setFormat(f"{cpu['percent']:.0f}%  ({cpu['cores_logical']} threads)")

        _update_bar(self.ram_bar, int(mem["percent"]))
        self.ram_bar.setFormat(f"{mem['used_gb']:.1f} / {mem['total_gb']:.1f} GB")

        if snapshot["gpus"]:
            gpu = snapshot["gpus"][0]
            _update_bar(self.gpu_bar, int(gpu["utilization_percent"]))
            self.gpu_bar.setFormat(f"{gpu['utilization_percent']:.0f}%")
            self.gpu_label.setText(
                f"{gpu['name']} — {gpu['memory_used_mb']:.0f}/{gpu['memory_total_mb']:.0f} MB — {gpu['temperature_c']:.0f}°C"
            )
        else:
            self.gpu_bar.setValue(0)
            self.gpu_bar.setFormat("n/a")
            self.gpu_label.setText("GPU: no supported monitoring tool detected")
