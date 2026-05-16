"""
NVIDIA DKMS management for Soplos Linux.

After a kernel is installed, DKMS automatically recompiles the nvidia module.
If Secure Boot is active, the DKMS module must also be signed with the MOK key.
"""

import os
import sys
import shutil
from typing import Optional, Callable, List
from utils.system import run_command, run_privileged, run_privileged_with_callback


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


def has_intel_gpu() -> bool:
    """Detect Intel GPU (i915) via lspci — checks only display/GPU lines."""
    return any("intel" in l for l in _gpu_lines())


def get_dkms_nvidia_module(kernel_release: str) -> Optional[str]:
    """
    Return the DKMS nvidia module path for the given kernel release,
    or None if not built yet.
    """
    res = run_command(f"dkms status -k {kernel_release} 2>/dev/null")
    for line in res.stdout.splitlines():
        if "nvidia" in line.lower() and ("installed" in line or "built" in line):
            # Module is at /lib/modules/{kernel_release}/updates/dkms/nvidia.ko (or .ko.zst)
            for ext in [".ko", ".ko.zst", ".ko.xz"]:
                path = f"/lib/modules/{kernel_release}/updates/dkms/nvidia{ext}"
                if os.path.exists(path):
                    return path
            # Broader search
            res2 = run_command(
                f"find /lib/modules/{kernel_release} -name 'nvidia.ko*' 2>/dev/null"
            )
            if res2.stdout.strip():
                return res2.stdout.strip().splitlines()[0]
    return None


def rebuild_dkms_modules(kernel_release: str,
                          progress_callback: Optional[Callable[[str, int], None]] = None) -> bool:
    """
    Force DKMS to rebuild all modules for the given kernel release.
    Usually not needed — DKMS triggers automatically on kernel install.
    """
    if not shutil.which("dkms"):
        return True  # Nothing to do

    def _progress(line: str) -> None:
        if progress_callback:
            progress_callback(line, -1)

    exit_code = run_privileged_with_callback(
        f"dkms autoinstall -k {kernel_release}",
        line_callback=_progress
    )
    return exit_code == 0


def sign_nvidia_module(kernel_release: str, sb_manager) -> bool:
    """
    Sign the NVIDIA DKMS module with the MOK key after build.
    Only needed when Secure Boot is active.
    """
    if not sb_manager.keys_exist():
        print("SecureBoot: No MOK keys — skipping NVIDIA module signing.", file=sys.stderr)
        return True

    module_path = get_dkms_nvidia_module(kernel_release)
    if not module_path:
        print(f"NVIDIA module not found for {kernel_release}, skipping signing.", file=sys.stderr)
        return True

    print(f"Signing NVIDIA module: {module_path}", file=sys.stderr)
    return sb_manager.sign_file(module_path)


def get_nvidia_signing_commands(kernel_release: str, sb_manager) -> List[str]:
    """
    Return shell commands for signing NVIDIA DKMS modules with sign-file.
    Handles .ko, .ko.xz and .ko.zst formats (decompress → sign → recompress).
    sbsign is for ELF binaries only — kernel modules must use sign-file.
    """
    if not sb_manager.keys_exist():
        return []

    pem = str(sb_manager.pem_key)
    priv = str(sb_manager.priv_key)

    # Locate sign-file from the installed kernel headers
    find_sign_file = (
        f'SIGN_FILE="/usr/lib/linux-headers-{kernel_release}/scripts/sign-file"; '
        f'if [ ! -x "$SIGN_FILE" ]; then '
        f'  SIGN_FILE=$(find /usr/src -name "sign-file" -path "*{kernel_release}*" 2>/dev/null | head -1); '
        f'fi; '
        f'if [ ! -x "$SIGN_FILE" ]; then '
        f'  echo "sign-file not found for {kernel_release}, skipping NVIDIA signing."; '
        f'  exit 0; '
        f'fi'
    )

    sign_loop = (
        f'for MOD in $(find /lib/modules/{kernel_release} -name "nvidia*.ko*" 2>/dev/null); do '
        f'  echo "Signing $MOD..."; '
        f'  if [[ "$MOD" == *.ko.xz ]]; then '
        f'    xz -d "$MOD" && BASE="${{MOD%.xz}}" && '
        f'    "$SIGN_FILE" sha256 "{priv}" "{pem}" "$BASE" && '
        f'    xz -T0 "$BASE"; '
        f'  elif [[ "$MOD" == *.ko.zst ]]; then '
        f'    zstd -d --rm "$MOD" && BASE="${{MOD%.zst}}" && '
        f'    "$SIGN_FILE" sha256 "{priv}" "{pem}" "$BASE" && '
        f'    zstd --rm -T0 "$BASE"; '
        f'  else '
        f'    "$SIGN_FILE" sha256 "{priv}" "{pem}" "$MOD"; '
        f'  fi; '
        f'done'
    )

    return [find_sign_file, sign_loop]
