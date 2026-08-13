"""
Unattended batch builder for a full Soplos kernel release.

Builds every kernel of a release one after another without user interaction:
6 variants for v1 and v2, plus x3d for v3 and v4 (26 builds in total).

Each build starts from a completely fresh build directory: the directory is
deleted before the build and deleted again after the packages have been copied
to their destination. No sources, patches or object files are ever reused
between kernels.

If a build fails the queue stops immediately and the build directory is left
untouched, so the build log and the sources of the failing kernel remain
available for inspection.
"""

import glob
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .common_types import MarchLevel
from .profiles import ProfileType, get_profile
from .i18n_manager import _
from utils.system import get_build_directory, get_cpu_count


# Patch order used to compose the package name, identical to the Stock UI
_NAME_ORDER = {"bore": 0, "rt": 1, "zen": 2, "ntsync": 3, "x3d": 4}

# Variants built for every march level
_VARIANTS: List[List[str]] = [
    [],
    ["bore"],
    ["bore", "ntsync"],
    ["ntsync"],
    ["rt"],
    ["zen"],
]

# X3D implies bore and ntsync, and only makes sense on Zen 3 and newer
_X3D_VARIANT: List[str] = ["bore", "ntsync", "x3d"]
_X3D_MIN_MARCH = MarchLevel.V3

_MARCH_LABELS = {"v1", "v2", "v3", "v4"}


def kernel_name(patch_ids: List[str], march: str) -> str:
    """Compose the package name for a Stock build, e.g. soplos-bore-ntsync-v3.

    X3D is always packaged as soplos-x3d because bore and ntsync are implicit.
    """
    ordered = sorted(patch_ids, key=lambda p: _NAME_ORDER.get(p, 99))
    if "x3d" in ordered:
        parts = ["soplos", "x3d", march]
    else:
        parts = ["soplos"] + ordered + [march]
    return "-".join(parts)


def _display_name(pkg: str) -> str:
    """Human readable label for a linux-soplos* package name.

    Mirrors the label used by the Soplos Kernels tab so the metapackage
    description reads the same whether it was built one by one or in batch.
    """
    suffix = pkg[len("linux-soplos"):]
    if not suffix:
        return _("Stock")
    parts = suffix.lstrip("-").split("-")
    march = parts[-1] if parts[-1] in _MARCH_LABELS else None
    flavor = parts[:-1] if march else parts
    if not flavor:
        label = _("Stock")
    elif len("-".join(flavor)) <= 5:
        label = "-".join(flavor).upper()
    else:
        label = "-".join(flavor).replace("-", " ").title()
    return f"{label} {march.upper()}" if march else label


@dataclass
class BatchJob:
    """A single kernel of the release queue."""
    patch_ids: List[str]
    march: str

    @property
    def name(self) -> str:
        return kernel_name(self.patch_ids, self.march)

    @property
    def folder(self) -> str:
        """Destination subfolder for this job, e.g. V3."""
        return self.march.upper()


@dataclass
class BatchResult:
    """Outcome of a batch run."""
    completed: List[str] = field(default_factory=list)
    failed: Optional[str] = None
    failed_log: Optional[str] = None
    cancelled: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.failed is None and not self.cancelled and self.error is None


def release_queue() -> List[BatchJob]:
    """Return the full release queue, 26 jobs ordered from v1 to v4."""
    jobs: List[BatchJob] = []
    for march in MarchLevel.ALL:
        for patches in _VARIANTS:
            jobs.append(BatchJob(patch_ids=list(patches), march=march))
        if MarchLevel.ALL.index(march) >= MarchLevel.ALL.index(_X3D_MIN_MARCH):
            jobs.append(BatchJob(patch_ids=list(_X3D_VARIANT), march=march))
    return jobs


class BatchBuilder:
    """Runs the release queue unattended."""

    def __init__(self, kernel_manager=None,
                 progress_callback: Optional[Callable[[str, int], None]] = None,
                 job_callback: Optional[Callable[[int, int, str], None]] = None):
        if kernel_manager is None:
            from .kernel import KernelManager
            kernel_manager = KernelManager()
        self._manager = kernel_manager
        self._progress_callback = progress_callback
        self._job_callback = job_callback
        self._build_dir = get_build_directory()
        self._cancelled = threading.Event()

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def cancel(self, cleanup: bool = False) -> None:
        """Stop the queue as soon as the current build allows it.

        cleanup: delete the build directory, same meaning as in KernelManager.
        """
        self._cancelled.set()
        self._manager.cancel(cleanup=cleanup)

    def _is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def _report(self, message: str, percent: int = -1) -> None:
        if self._progress_callback:
            self._progress_callback(message, percent)

    def _reset_log(self) -> None:
        """Recreate the build directory with an empty build.log."""
        try:
            os.makedirs(self._build_dir, exist_ok=True)
            with open(os.path.join(self._build_dir, "build.log"), "w"):
                pass
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def run(self, version: str, dest_root: str,
            cpu_count: Optional[int] = None,
            jobs: Optional[List[BatchJob]] = None) -> BatchResult:
        """Build every kernel of the release into dest_root/<version>/V<n>/.

        Stops at the first failure, leaving the build directory in place.
        """
        result = BatchResult()
        jobs = jobs if jobs is not None else release_queue()
        total = len(jobs)

        if not cpu_count or cpu_count < 1:
            cpu_count = get_cpu_count()

        profile = get_profile(ProfileType.STOCK)
        if profile is None:
            result.error = _("Stock profile not found.")
            return result

        # Dependencies are resolved once, so the whole queue needs a single
        # authentication and never asks for anything again
        self._report(_("Checking build dependencies..."), 0)
        if not self._manager.check_and_install_dependencies():
            result.error = _("Could not install the build dependencies.")
            return result

        for index, job in enumerate(jobs, start=1):
            if self._is_cancelled():
                result.cancelled = True
                return result

            # Fresh start: no leftovers from the previous kernel
            self._manager.cleanup_build_files()

            # Recreate an empty log before the UI attaches its viewer to it,
            # otherwise the viewer would keep reading the deleted file
            self._reset_log()

            if self._job_callback:
                self._job_callback(index, total, job.name)
            self._report(
                _("[{i}/{n}] Building {name}...").format(
                    i=index, n=total, name=job.name
                ), 0
            )

            success = self._manager.full_install(
                version=version,
                profile=profile,
                custom_name=job.name,
                patch_ids=list(job.patch_ids),
                secure_boot=False,
                reuse_source=False,
                build_only=True,
                march_level=job.march,
                enable_sched_ext=True,
                cpu_count=cpu_count,
            )

            if self._is_cancelled():
                result.cancelled = True
                return result

            if not success:
                # Keep the build directory so the log and the sources survive
                result.failed = job.name
                result.failed_log = os.path.join(self._build_dir, "build.log")
                self._report(
                    _("Build failed for {name}. Queue stopped.").format(name=job.name), -1
                )
                return result

            saved = self._save_packages(version, job, dest_root)
            if saved is None:
                result.failed = job.name
                result.failed_log = os.path.join(self._build_dir, "build.log")
                self._report(
                    _("No packages found for {name}. Queue stopped.").format(name=job.name), -1
                )
                return result

            result.completed.append(job.name)
            self._report(
                _("[{i}/{n}] {name} saved to {path}").format(
                    i=index, n=total, name=job.name, path=saved
                ), 100
            )

            # Leave nothing behind before the next kernel
            self._manager.cleanup_build_files()

        return result

    # ------------------------------------------------------------------
    # Packaging
    # ------------------------------------------------------------------

    def _kernel_release(self, version: str) -> str:
        """Actual kernel release string of the build that just finished."""
        release = self._manager._installer.last_kernel_release or ""
        if release:
            return release
        release_file = os.path.join(
            self._build_dir, f"linux-{version}", "include", "config", "kernel.release"
        )
        if os.path.exists(release_file):
            with open(release_file) as f:
                return f.read().strip()
        return ""

    def _collect_debs(self, version: str, custom_name: str) -> List[str]:
        """Image and headers packages of the current build, debug ones excluded."""
        kernel_release = self._kernel_release(version)
        debs = []
        for path in glob.glob(os.path.join(self._build_dir, "*.deb")):
            base = os.path.basename(path)
            if "linux-image" not in base and "linux-headers" not in base:
                continue
            if "-dbg" in base:
                continue
            if kernel_release:
                if f"-{kernel_release}" not in base:
                    continue
            elif custom_name not in base:
                continue
            debs.append(path)
        return list(dict.fromkeys(debs))

    def _build_metapackage(self, version: str, custom_name: str) -> Optional[str]:
        """Create the linux-soplos* metapackage that pulls image and headers."""
        kernel_release = self._kernel_release(version)
        if not kernel_release:
            return None

        pkg_name = f"linux-{custom_name}"
        display_name = _display_name(pkg_name)
        meta_path = os.path.join(self._build_dir, f"{pkg_name}_{version}_amd64.deb")

        try:
            with tempfile.TemporaryDirectory() as tmp:
                debian_dir = os.path.join(tmp, "DEBIAN")
                os.makedirs(debian_dir)
                control = (
                    f"Package: {pkg_name}\n"
                    f"Version: {version}\n"
                    f"Architecture: amd64\n"
                    f"Maintainer: Soplos Linux Team <info@soplos.org>\n"
                    f"Depends: linux-image-{kernel_release}, linux-headers-{kernel_release}\n"
                    f"Section: kernel\n"
                    f"Priority: optional\n"
                    f"Description: Soplos {display_name} kernel\n"
                    f" Installs the {kernel_release} kernel and its headers.\n"
                    f" When a new version is released, upgrading this package will\n"
                    f" automatically pull in the new kernel.\n"
                )
                with open(os.path.join(debian_dir, "control"), "w") as f:
                    f.write(control)
                res = subprocess.run(
                    ["dpkg-deb", "--root-owner-group", "--build", tmp, meta_path],
                    capture_output=True, text=True
                )
                if res.returncode != 0:
                    return None
        except Exception:
            return None

        return meta_path if os.path.exists(meta_path) else None

    def _save_packages(self, version: str, job: BatchJob,
                       dest_root: str) -> Optional[str]:
        """Copy the packages of a finished build to dest_root/<version>/V<n>/.

        Returns the destination directory, or None if there was nothing to save.
        """
        debs = self._collect_debs(version, job.name)
        if not debs:
            return None

        meta = self._build_metapackage(version, job.name)
        if meta:
            debs.append(meta)

        dest_dir = os.path.join(dest_root, version, job.folder)
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError:
            return None

        for deb in debs:
            try:
                shutil.copy2(deb, dest_dir)
            except Exception:
                return None

        return dest_dir
