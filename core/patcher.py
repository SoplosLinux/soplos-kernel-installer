"""
Patcher module — applies downloaded patches to kernel sources.
"""

import os
import sys
from typing import Dict, Optional, Callable, List
from utils.system import run_command, run_command_with_callback, ensure_directory


class KernelPatcher:
    """Applies patches to a kernel source tree."""

    def __init__(self, build_dir: str,
                 progress_callback: Optional[Callable[[str, int], None]] = None):
        self._build_dir = build_dir
        self._progress_callback = progress_callback
        self._cancel_check: Optional[Callable[[], bool]] = None

    def set_cancel_check(self, check_func: Callable[[], bool]) -> None:
        self._cancel_check = check_func

    def _is_cancelled(self) -> bool:
        return self._cancel_check() if self._cancel_check else False

    def _report_progress(self, message: str, percent: int = -1) -> None:
        if self._progress_callback:
            self._progress_callback(message, percent)

    def get_applied_patches(self, version: str) -> List[str]:
        """Return list of patch ids recorded as applied in the source tree."""
        marker = os.path.join(self._build_dir, f"linux-{version}", ".applied_patches")
        if not os.path.exists(marker):
            return []
        try:
            with open(marker, 'r') as f:
                return [l.strip() for l in f if l.strip()]
        except Exception:
            return []

    def _save_applied_patches(self, version: str, patch_ids: List[str]) -> None:
        marker = os.path.join(self._build_dir, f"linux-{version}", ".applied_patches")
        try:
            with open(marker, 'w') as f:
                f.write('\n'.join(patch_ids))
        except Exception:
            pass

    def apply_patches(self, version: str, patches: Dict[str, List[str]]) -> bool:
        """
        Apply patches to the kernel source tree.

        Args:
            version: Kernel version string (e.g. "6.12.30")
            patches: {patch_id: [local_patch_paths]} — from KernelDownloader.download_patches()

        Returns True if all patches applied successfully.
        """
        if not patches:
            return True

        source_dir = os.path.join(self._build_dir, f"linux-{version}")
        if not os.path.isdir(source_dir):
            self._report_progress(f"Error: Source dir not found: {source_dir}", -1)
            return False

        total = len(patches)
        applied = 0

        # Apply in a sensible order: rt first (large), then bore, then others
        ordered_ids = self._sort_patch_ids(list(patches.keys()))

        for patch_id in ordered_ids:
            if self._is_cancelled():
                return False

            patch_paths = patches[patch_id]
            self._report_progress(f"Applying patch: {patch_id}...", -1)

            for patch_path in patch_paths:
                ok = self._apply_single_patch(source_dir, patch_id, patch_path)
                if not ok:
                    self._report_progress(f"Error applying patch: {patch_id}", -1)
                    print(f"Failed to apply patch: {patch_id} ({patch_path})", file=sys.stderr)
                    return False

            applied += 1
            self._report_progress(
                f"Patch {patch_id} applied ({applied}/{total})", -1
            )

        self._save_applied_patches(version, list(patches.keys()))
        return True

    def _sort_patch_ids(self, ids: List[str]) -> List[str]:
        """Return patch ids in preferred application order."""
        order = ["rt", "bore", "zen"]
        sorted_ids = [p for p in order if p in ids]
        remaining = [p for p in ids if p not in sorted_ids]
        return sorted_ids + remaining

    def _apply_single_patch(self, source_dir: str,
                             patch_id: str, patch_path: str) -> bool:
        """Apply a single patch file."""
        if not os.path.exists(patch_path):
            print(f"Patch file not found: {patch_path}", file=sys.stderr)
            return False

        # All patches: apply with patch -p1 (standard for kernel patches)
        cmd = f'patch -p1 --batch --forward -i "{patch_path}"'
        exit_code = run_command_with_callback(
            cmd, cwd=source_dir,
            stop_check=self._is_cancelled
        )
        if exit_code == 0:
            return True
        dry = run_command(
            f'patch -p1 --batch --forward --dry-run -i "{patch_path}"',
            cwd=source_dir
        )
        if "already applied" in (dry.stdout + dry.stderr).lower():
            print(f"Patch {patch_id} already applied, skipping.", file=sys.stderr)
            return True
        return False
