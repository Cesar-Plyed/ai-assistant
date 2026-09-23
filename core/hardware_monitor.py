"""
Cross-platform hardware monitoring for Linux and Windows.

Uses psutil for CPU/RAM/disk/network, which works the same way on both
platforms. GPU stats are best-effort: NVIDIA GPUs are read via `nvidia-smi`
(present on both Linux and Windows once the driver is installed); if no
supported GPU tool is found, the GPU section is simply omitted instead of
raising an error.
"""

import shutil
import subprocess
from typing import Any

import psutil


def _bytes_to_gb(value: int) -> float:
    return round(value / (1024 ** 3), 2)


def get_cpu_info() -> dict[str, Any]:
    return {
        "percent": psutil.cpu_percent(interval=0.2),
        "per_core_percent": psutil.cpu_percent(interval=0.0, percpu=True),
        "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical": psutil.cpu_count(logical=True),
        "frequency_mhz": getattr(psutil.cpu_freq(), "current", None) if psutil.cpu_freq() else None,
    }


def get_memory_info() -> dict[str, Any]:
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total_gb": _bytes_to_gb(mem.total),
        "used_gb": _bytes_to_gb(mem.used),
        "percent": mem.percent,
        "swap_total_gb": _bytes_to_gb(swap.total),
        "swap_used_gb": _bytes_to_gb(swap.used),
    }


def get_disk_info() -> list[dict[str, Any]]:
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append({
            "mountpoint": part.mountpoint,
            "total_gb": _bytes_to_gb(usage.total),
            "used_gb": _bytes_to_gb(usage.used),
            "percent": usage.percent,
        })
    return disks


def get_network_info() -> dict[str, Any]:
    counters = psutil.net_io_counters()
    return {
        "sent_gb": _bytes_to_gb(counters.bytes_sent),
        "received_gb": _bytes_to_gb(counters.bytes_recv),
    }


def get_gpu_info() -> list[dict[str, Any]]:
    """Best-effort NVIDIA GPU stats via nvidia-smi. Returns an empty list on
    systems without a supported GPU tool (AMD/Intel GPUs are not queried to
    avoid depending on vendor-specific tooling that may not be installed)."""
    if not shutil.which("nvidia-smi"):
        return []

    query = "name,utilization.gpu,memory.used,memory.total,temperature.gpu"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    gpus = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            continue
        name, util, mem_used, mem_total, temp = parts
        gpus.append({
            "name": name,
            "utilization_percent": float(util),
            "memory_used_mb": float(mem_used),
            "memory_total_mb": float(mem_total),
            "temperature_c": float(temp),
        })
    return gpus


def get_snapshot() -> dict[str, Any]:
    """Single call returning a full hardware snapshot for the UI widget or the AI tool."""
    return {
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "disks": get_disk_info(),
        "network": get_network_info(),
        "gpus": get_gpu_info(),
    }


def format_snapshot_as_text(snapshot: dict[str, Any] | None = None) -> str:
    """Human-readable summary, used as the AI tool's return value."""
    snapshot = snapshot or get_snapshot()
    cpu = snapshot["cpu"]
    mem = snapshot["memory"]

    lines = [
        "Hardware status:",
        f"- CPU: {cpu['percent']}% used "
        f"({cpu['cores_physical']} physical / {cpu['cores_logical']} logical cores)",
        f"- RAM: {mem['used_gb']} GB / {mem['total_gb']} GB ({mem['percent']}%)",
    ]

    for disk in snapshot["disks"]:
        lines.append(f"- Disk {disk['mountpoint']}: {disk['used_gb']} GB / {disk['total_gb']} GB ({disk['percent']}%)")

    if snapshot["gpus"]:
        for gpu in snapshot["gpus"]:
            lines.append(
                f"- GPU {gpu['name']}: {gpu['utilization_percent']}% used, "
                f"{gpu['memory_used_mb']}/{gpu['memory_total_mb']} MB VRAM, {gpu['temperature_c']} C"
            )
    else:
        lines.append("- GPU: no supported GPU monitoring tool detected (nvidia-smi not found).")

    return "\n".join(lines)
