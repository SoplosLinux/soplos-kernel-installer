"""
NVIDIA GPU detection for Soplos Linux.

After a kernel is installed, DKMS automatically recompiles the nvidia module
and signs it with its own key (/var/lib/dkms/mok.key) when one exists.
"""

import shutil
from utils.system import run_command


def _gpu_lines() -> list:
    """Return lspci lines that describe a display/GPU device."""
    if not shutil.which("lspci"):
        return []
    res = run_command("lspci")
    keywords = ("vga", "display", "3d controller", "3d")
    return [l.lower() for l in res.stdout.splitlines()
            if any(k in l.lower() for k in keywords)]


def has_nvidia_gpu() -> bool:
    """Detect NVIDIA GPU via lspci — checks only display/GPU lines."""
    return any("nvidia" in l for l in _gpu_lines())


def get_gpu_description() -> str:
    """Return the model name(s) reported by lspci for detected display/GPU devices."""
    if not shutil.which("lspci"):
        return ''
    keywords = ("vga", "display", "3d controller", "3d")
    models = []
    for line in run_command("lspci").stdout.splitlines():
        if any(k in line.lower() for k in keywords) and ':' in line:
            models.append(line.split(':', 2)[-1].strip())
    return ", ".join(models)
