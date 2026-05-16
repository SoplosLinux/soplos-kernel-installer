"""
KernelManager — high-level API bridge for the UI.
Orchestrates download, patch, build and install workflows.
"""

import os
import sys
import subprocess
import tempfile
import threading
from typing import List, Optional, Callable
from .downloader import KernelDownloader
from .patcher import KernelPatcher
from .installer import SoplosInstaller
from .secure_boot import SecureBootManager
from .history import HistoryManager
from .profiles import KernelProfile, get_all_profiles, ProfileType
from .common_types import KernelVersion, InstalledKernel, PatchInfo
from utils.system import run_command, run_privileged, get_build_directory

# Available patches catalogue
AVAILABLE_PATCHES: List[PatchInfo] = [
    PatchInfo(
        id="bore",
        name="BORE",
        description="Burst-Oriented Response Enhancer — improved CPU scheduler for responsiveness.",
        source_url="https://github.com/firelzrd/bore-scheduler",
    ),
    PatchInfo(
        id="rt",
        name="PREEMPT_RT",
        description="Full real-time preemption — ultra-low latency for audio/video production.",
        source_url="https://www.kernel.org/pub/linux/kernel/projects/rt",
    ),
    PatchInfo(
        id="zen",
        name="Zen",
        description="Zen kernel optimizations — gaming and desktop performance.",
        source_url="https://github.com/zen-kernel/zen-kernel",
    ),
    PatchInfo(
        id="ntsync",
        name="NTSYNC",
        description="NT synchronization primitives — improves Wine/Proton gaming performance.",
        source_url="https://www.kernel.org",
        is_config_only=True,
    ),
]


class KernelManager:
    """Unified API for the Soplos Kernel Installer UI."""

    def __init__(self):
        self._build_dir = get_build_directory()
        self._progress_callback: Optional[Callable[[str, int], None]] = None

        self._cancel_event: Optional[threading.Event] = None

        self._downloader = KernelDownloader(self._build_dir)
        self._patcher    = KernelPatcher(self._build_dir)
        self._installer  = SoplosInstaller(self._build_dir)
        self._history    = HistoryManager()
        self._secure_boot = SecureBootManager()

    def set_progress_callback(self, callback: Callable[[str, int], None]) -> None:
        self._progress_callback = callback
        for mod in [self._downloader, self._patcher, self._installer]:
            mod._progress_callback = callback

    def _report_progress(self, message: str, percent: int = -1) -> None:
        if self._progress_callback:
            self._progress_callback(message, percent)

    def cancel(self, cleanup: bool = False) -> None:
        if self._cancel_event:
            self._cancel_event.set()
        if cleanup:
            self._installer.cleanup_build_files()

    # ------------------------------------------------------------------
    # System info
    # ------------------------------------------------------------------

    def get_current_kernel(self) -> str:
        res = run_command("uname -r")
        return res.stdout.strip() if res.returncode == 0 else "Unknown"

    def get_system_label(self) -> str:
        """Pretty system label for the status bar."""
        try:
            with open("/etc/os-release") as f:
                data = dict(
                    line.strip().split('=', 1)
                    for line in f if '=' in line
                )
            pretty = data.get('PRETTY_NAME', 'Soplos Linux').strip('"')
        except Exception:
            pretty = "Soplos Linux"

        desktop = (
            os.environ.get('XDG_CURRENT_DESKTOP') or
            os.environ.get('DESKTOP_SESSION', '')
        )
        return f"{pretty} — {desktop}" if desktop else pretty

    # ------------------------------------------------------------------
    # Versions
    # ------------------------------------------------------------------

    def fetch_available_versions(self) -> List[KernelVersion]:
        return self._downloader.fetch_available_versions()

    def get_all_versions(self) -> List[KernelVersion]:
        """Return stable + lts + rc versions from kernel.org."""
        return self.fetch_available_versions()

    # ------------------------------------------------------------------
    # Patches catalogue
    # ------------------------------------------------------------------

    def get_available_patches(self) -> List[PatchInfo]:
        return list(AVAILABLE_PATCHES)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_installation_history(self) -> List[InstalledKernel]:
        return self._history.get_history(current_version=self.get_current_kernel())

    # ------------------------------------------------------------------
    # Dependency check
    # ------------------------------------------------------------------

    _REQUIRED_PACKAGES = [
        'make', 'gcc', 'g++', 'flex', 'bison', 'bc',
        'wget', 'tar', 'rsync', 'cpio', 'kmod',
        'binutils', 'fakeroot',
        'libssl-dev',
        'libelf-dev',
        'linux-libc-dev',
        'libncurses-dev',
        'pkg-config',
        'gettext',
        'dwarves',
        'libdw-dev',
        'grub-common',
        'sbsigntool',
        'mokutil',
    ]

    @staticmethod
    def _is_package_installed(package: str) -> bool:
        import shutil
        if shutil.which(package):
            return True
        try:
            res = subprocess.run(
                ['dpkg-query', '-W', '-f=${Status}', package],
                capture_output=True, text=True
            )
            return 'ok installed' in res.stdout
        except Exception:
            return False

    def _are_headers_broken(self) -> bool:
        extra_flags = []
        try:
            ma = subprocess.check_output(
                ['gcc', '-print-multiarch'], stderr=subprocess.DEVNULL, text=True
            ).strip()
            if ma:
                extra_flags = [f'-I/usr/include/{ma}']
        except Exception:
            pass

        test_code = "#include <linux/limits.h>\n#include <sys/types.h>\nint main() { return 0; }\n"
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as f:
            fname = f.name
            f.write(test_code)
        try:
            cmd = ['gcc', '-c', fname, '-o', '/dev/null'] + extra_flags
            res = subprocess.run(cmd, capture_output=True, timeout=10)
            return res.returncode != 0
        except Exception:
            return True
        finally:
            try:
                os.unlink(fname)
            except Exception:
                pass

    # Files that must exist on disk for a package to be considered healthy
    _PACKAGE_INTEGRITY: dict = {
        'libssl-dev': '/usr/include/openssl/opensslv.h',
    }

    def _is_package_healthy(self, package: str) -> bool:
        """Return False if the package is installed but a critical file is missing."""
        sentinel = self._PACKAGE_INTEGRITY.get(package)
        if sentinel:
            import os as _os
            return _os.path.exists(sentinel)
        return True

    def check_and_install_dependencies(self) -> bool:
        """Check and install missing build dependencies with a single pkexec call."""
        missing = [p for p in self._REQUIRED_PACKAGES if not self._is_package_installed(p)]

        corrupted = [
            p for p in self._REQUIRED_PACKAGES
            if p not in missing and not self._is_package_healthy(p)
        ]

        headers_broken = self._are_headers_broken()
        if headers_broken:
            for pkg in ['linux-libc-dev', 'libc6-dev']:
                if pkg not in missing:
                    corrupted.append(pkg)

        if not missing and not corrupted:
            return True

        # Build a single script so pkexec is only invoked once
        parts = []
        if missing or corrupted:
            parts.append("apt-get update -qq")
        if missing:
            pkgs = ' '.join(missing)
            self._report_progress(f"Installing missing packages: {pkgs}...")
            parts.append(f"apt-get install -y {pkgs}")
        if corrupted:
            pkgs = ' '.join(corrupted)
            self._report_progress(f"Reinstalling corrupted packages: {pkgs}...")
            parts.append(f"apt-get install -y --reinstall {pkgs}")

        script = " && ".join(parts)
        return run_privileged(script).returncode == 0

    def _repair_headers_if_broken(self) -> None:
        if self._are_headers_broken():
            self._report_progress("Reinstalling broken kernel headers...")
            run_privileged("apt install -y --reinstall linux-libc-dev libc6-dev")

    # ------------------------------------------------------------------
    # Full install workflow
    # ------------------------------------------------------------------

    def full_install(
        self,
        version: str,
        profile: KernelProfile,
        custom_name: str = "soplos",
        patch_ids: Optional[List[str]] = None,
        secure_boot: bool = False,
        reuse_source: bool = False,
        build_only: bool = False,
    ) -> bool:
        """
        Full kernel install:
          1. Download sources
          2. Download & apply patches
          3. Configure
          4. Build
          5. Install (.deb → dracut → update-grub)
          6. Sign (if Secure Boot)
        """
        patch_ids = patch_ids or []

        cancel_event = threading.Event()
        self._cancel_event = cancel_event

        def is_cancelled() -> bool:
            return cancel_event.is_set()

        self._downloader.set_cancel_check(is_cancelled)
        self._patcher.set_cancel_check(is_cancelled)
        self._installer.set_cancel_check(is_cancelled)

        try:
            # 0. Verify/repair headers and dependencies
            self.check_and_install_dependencies()

            # 1. Download sources
            self._report_progress("Downloading kernel sources...", 0)

            if reuse_source:
                # Check if applied patches match requested ones
                applied = sorted(self._patcher.get_applied_patches(version))
                requested = sorted(patch_ids)
                if applied != requested:
                    self._report_progress(
                        "Patch set changed — re-extracting sources from cache...", 2
                    )
                    if not self._downloader.reextract(version):
                        return False
                else:
                    if not self._downloader.download(version, skip_download=True):
                        return False
            else:
                if not self._downloader.download(version, skip_download=False):
                    return False

            if is_cancelled():
                return False

            # 2. Download and apply patches
            if patch_ids:
                patches_dir = os.path.join(self._build_dir, "patches")

                self._report_progress("Downloading patches...", 20)
                downloaded = self._downloader.download_patches(
                    version, patch_ids, patches_dir
                )

                if is_cancelled():
                    return False

                if downloaded:
                    self._report_progress("Applying patches...", 24)
                    if not self._patcher.apply_patches(version, downloaded):
                        self._report_progress("Error applying patches.", -1)
                        return False
                else:
                    # Config-only patches (NTSYNC, RT on 6.12+) leave downloaded empty — not an error
                    self._report_progress("Patches are config-only for this kernel version — no files to apply.", -1)

            # 3. Configure
            # Populate hardware-optimized profile options at install time
            if profile.id == ProfileType.HARDWARE_OPTIMIZED:
                profile.config_options = KernelProfile.detect_hardware_optimizations()

            self._report_progress("Configuring kernel...", 26)
            if not self._installer.configure(
                version, profile, custom_name,
                secure_boot=secure_boot, patch_ids=patch_ids
            ):
                return False

            if is_cancelled():
                return False

            # 4. Build
            self._report_progress("Building kernel...", 30)
            if not self._installer.build(version):
                return False

            if is_cancelled():
                return False

            if build_only:
                source_dir = os.path.join(self._build_dir, f"linux-{version}")
                kr_file = os.path.join(source_dir, "include", "config", "kernel.release")
                if os.path.exists(kr_file):
                    with open(kr_file) as f:
                        self._installer.last_kernel_release = f.read().strip()
                self._report_progress("Build complete.", 100)
                return True

            # 5. Install
            self._report_progress("Installing kernel...", 95)
            if not self._installer.install(
                version, profile, custom_name, secure_boot=secure_boot,
                patch_ids=patch_ids
            ):
                return False

            # 6. Save history using the actual installed kernel release string
            kernel_release = (
                self._installer.last_kernel_release
                or (f"{version}-{custom_name}-{profile.suffix}" if profile.suffix else f"{version}-{custom_name}")
            )
            patches_str = ", ".join(patch_ids) if patch_ids else "none"
            self._history.save(
                kernel_release,
                profile.name,
                patches=patches_str,
                secure_boot=secure_boot,
            )

            self._report_progress("Done!", 100)
            return True

        except Exception as e:
            self._report_progress(f"Error: {e}", -1)
            print(f"full_install error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return False

    def cleanup_build_files(self) -> bool:
        return self._installer.cleanup_build_files()

    # ------------------------------------------------------------------
    # Secure Boot helpers (exposed for UI)
    # ------------------------------------------------------------------

    def is_secure_boot_active(self) -> bool:
        return self._secure_boot.is_secure_boot_active()

    def sb_keys_exist(self) -> bool:
        return self._secure_boot.keys_exist()

    def sb_generate_keys(self) -> bool:
        return self._secure_boot.generate_keys()

    def sb_is_enrolled(self) -> bool:
        return self._secure_boot.is_key_enrolled()

    def sb_get_enroll_command(self) -> str:
        return self._secure_boot.get_enroll_command()

    def sb_delete_keys(self) -> bool:
        return self._secure_boot.delete_local_keys()

    def sb_get_delete_mok_command(self) -> Optional[str]:
        return self._secure_boot.get_delete_mok_command()

    def sb_has_mok_signed_kernels(self, exclude_version: str = "") -> bool:
        if self._history.has_mok_signed_kernels(exclude_version):
            return True
        if not self._secure_boot.keys_exist():
            return False
        import glob as _glob
        _, pem, _ = self._secure_boot.get_key_paths()
        for vmlinuz in _glob.glob("/boot/vmlinuz-*"):
            ver = os.path.basename(vmlinuz).replace("vmlinuz-", "")
            if ver.casefold() == exclude_version.casefold():
                continue
            if run_command(f'sbverify --cert "{pem}" "{vmlinuz}" 2>/dev/null').returncode == 0:
                return True
        return False

    def remove_kernel(self, kernel_release: str) -> bool:
        ok = self._installer.remove_kernel(kernel_release)
        if ok:
            self._history.remove(kernel_release)
        return ok
