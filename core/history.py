"""
Installation history manager for Soplos Kernel Installer.
"""

import os
import json
import glob
from datetime import datetime
from typing import List
from pathlib import Path
from .common_types import InstalledKernel
from .profiles import get_all_profiles

_EXTERNAL_KERNELS = [
    ("xanmod",   "XanMod"),
    ("liquorix", "Liquorix"),
    ("zen",      "Zen"),
    ("rt",       "PREEMPT_RT"),
    ("lowlatency", "Low Latency"),
    ("cloud",    "Cloud"),
    ("deb14",    "System"),
    ("deb13",    "System"),
    ("deb12",    "System"),
    ("generic",  "System"),
    ("amd64",    "System"),
]

def _detect_external_profile(ver: str) -> str:
    v = ver.lower()
    for keyword, label in _EXTERNAL_KERNELS:
        if keyword in v:
            return label
    return "System"


class HistoryManager:
    """Manages kernel installation history from JSON and /boot scans."""

    HISTORY_FILE = "history.json"
    DATA_DIR = Path.home() / ".local" / "share" / "soplos-kernel-installer"

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path = self.DATA_DIR / self.HISTORY_FILE
        self._migrate_legacy()

    def _migrate_legacy(self) -> None:
        """Migrate history from old locations to ~/.local/share/soplos-kernel-installer/."""
        candidates = [
            Path.home() / "kernel_build" / self.HISTORY_FILE,
            Path.home() / ".soplos_kernel_installer_history.json",
        ]
        for legacy in candidates:
            if legacy.exists() and not self._path.exists():
                try:
                    legacy.rename(self._path)
                except Exception:
                    pass
                break

    def save(self, version: str, profile_name: str,
             patches: str = "", secure_boot: bool = False) -> None:
        history = self._load()
        history = [k for k in history if k.version.casefold() != version.casefold()]
        history.insert(0, InstalledKernel(
            version=version,
            profile=profile_name,
            patches=patches,
            installed_date=datetime.now().isoformat(),
            secure_boot=secure_boot,
        ))
        self._save(history[:20])

    def has_mok_signed_kernels(self, exclude_version: str = "") -> bool:
        """Return True if any installed kernel (other than exclude_version) used Secure Boot."""
        history = self._load()
        return any(
            k.secure_boot and k.version.casefold() != exclude_version.casefold()
            for k in history
        )

    def get_history(self, current_version: str = "") -> List[InstalledKernel]:
        history = self._load()
        history = self._sync_with_boot(history)
        history = self._purge_missing(history)

        unique = []
        seen = set()
        for k in history:
            cf = k.version.casefold()
            if cf not in seen:
                k.is_current = (k.version == current_version)
                unique.append(k)
                seen.add(cf)
        return unique

    def remove(self, version: str) -> None:
        history = self._load()
        self._save([k for k in history if k.version != version])

    def _load(self) -> List[InstalledKernel]:
        try:
            if self._path.exists():
                with open(self._path, 'r') as f:
                    data = json.load(f)
                    return [InstalledKernel(**item) for item in data]
        except Exception:
            pass
        return []

    def _save(self, history: List[InstalledKernel]) -> None:
        try:
            with open(self._path, 'w') as f:
                json.dump([
                    {
                        'version': k.version,
                        'profile': k.profile,
                        'patches': k.patches,
                        'installed_date': k.installed_date,
                        'secure_boot': k.secure_boot,
                    }
                    for k in history
                ], f, indent=2)
        except Exception as e:
            print(f"History save error: {e}")

    def _purge_missing(self, history: List[InstalledKernel]) -> List[InstalledKernel]:
        """Remove from history kernels whose vmlinuz no longer exists in /boot."""
        clean = [k for k in history if os.path.exists(f"/boot/vmlinuz-{k.version}")]
        if len(clean) != len(history):
            self._save(clean)
        return clean

    def _sync_with_boot(self, history: List[InstalledKernel]) -> List[InstalledKernel]:
        """Scan /boot/vmlinuz-* for kernels not in history."""
        try:
            existing = {k.version.casefold() for k in history}
            suffixes = {p.suffix: p.name for p in get_all_profiles()}

            for vmlinuz in glob.glob("/boot/vmlinuz-*"):
                ver = os.path.basename(vmlinuz).replace("vmlinuz-", "")
                if ver.casefold() in existing:
                    continue
                profile_name = _detect_external_profile(ver)
                for suffix, name in suffixes.items():
                    if ver.endswith(f"-{suffix}"):
                        profile_name = name
                        break
                history.append(InstalledKernel(
                    version=ver,
                    profile=profile_name,
                    patches="",
                    installed_date=datetime.fromtimestamp(
                        os.path.getmtime(vmlinuz)
                    ).isoformat()
                ))
            history.sort(key=lambda k: k.installed_date, reverse=True)
        except Exception:
            pass
        return history
