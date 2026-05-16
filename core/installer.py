"""
Installer module for Soplos Linux (Debian Testing + Dracut).

Build flow:
  1. configure  — copy /boot/config-$(uname -r), apply profile, apply fixes
  2. build      — make -j{n} bindeb-pkg
  3. install    — dpkg -i *.deb
  4. dracut     — dracut --force --kver {version}
  5. grub       — update-grub
  6. secure boot — sign kernel + EFI binaries + NVIDIA module (if needed)
"""

import os
import sys
import re
import glob
import shutil
from typing import Optional, Callable, List
from .profiles import KernelProfile
from .secure_boot import SecureBootManager
from .nvidia import has_nvidia_gpu
from .nvidia_dkms_patch import get_nvidia_dkms_patch_commands
from utils.system import (
    run_command, run_command_with_callback,
    run_privileged, run_privileged_with_callback,
    get_cpu_count,
)

DRACUT_CONF_DIR = "/etc/dracut.conf.d/"
DRACUT_SOPLOS_CONF = DRACUT_CONF_DIR + "soplos.conf"


class SoplosInstaller:
    """Orchestrates kernel build and installation on Soplos Linux."""

    def __init__(self, build_dir: str,
                 progress_callback: Optional[Callable[[str, int], None]] = None):
        self._build_dir = build_dir
        self._progress_callback = progress_callback
        self._cancel_check: Optional[Callable[[], bool]] = None
        self._secure_boot = SecureBootManager()
        self.last_kernel_release: Optional[str] = None

    def set_cancel_check(self, check_func: Callable[[], bool]) -> None:
        self._cancel_check = check_func

    def _is_cancelled(self) -> bool:
        return self._cancel_check() if self._cancel_check else False

    def _report_progress(self, message: str, percent: int = -1) -> None:
        if self._progress_callback:
            self._progress_callback(message, percent)

    # ------------------------------------------------------------------
    # Configure
    # ------------------------------------------------------------------

    def configure(self, version: str, profile: KernelProfile,
                  custom_name: str = "soplos",
                  secure_boot: bool = False,
                  patch_ids: Optional[List[str]] = None) -> bool:
        """Configure the kernel for building."""
        source_dir = os.path.join(self._build_dir, f"linux-{version}")

        self._report_progress("Copying current kernel configuration...", 26)
        base_config = self._find_base_config()
        run_command(f'cp "{base_config}" .config', cwd=source_dir)
        run_command("chmod +x scripts/config", cwd=source_dir)

        # Apply profile options
        self._report_progress(f"Applying profile: {profile.name}...", 28)
        for cmd in profile.get_config_commands():
            run_command(cmd, cwd=source_dir)

        # Local version tag
        tag = f"-{custom_name}-{profile.suffix}" if profile.suffix else f"-{custom_name}"
        run_command(f'./scripts/config --set-str LOCALVERSION "{tag}"', cwd=source_dir)

        # NTSYNC: mainlined in 6.14+, config option only
        if patch_ids and "ntsync" in patch_ids and self._kernel_supports_ntsync(version):
            self._report_progress("Enabling NTSYNC...", 28)
            run_command("./scripts/config --enable NTSYNC", cwd=source_dir)

        # PREEMPT_RT — independent of the preemption choice block.
        # Enable PREEMPT_RT and disable PREEMPT_DYNAMIC (depends on !PREEMPT_RT in Kconfig).
        # Do NOT touch the choice members (PREEMPT, PREEMPT_VOLUNTARY, PREEMPT_NONE, PREEMPT_LAZY).
        if patch_ids and "rt" in patch_ids:
            self._report_progress("Enabling PREEMPT_RT...", 28)
            run_command("./scripts/config --enable PREEMPT_RT", cwd=source_dir)
            run_command("./scripts/config --disable PREEMPT_DYNAMIC", cwd=source_dir)

        # Apply all fixes before olddefconfig so it can resolve their dependencies
        sb_key = None
        if secure_boot and self._secure_boot.keys_exist():
            _, _, combined = self._secure_boot.get_key_paths()
            sb_key = combined

        for fix in self._get_config_fixes(sb_key):
            run_command(fix, cwd=source_dir)

        # Resolve all Kconfig dependencies (profile + fixes) so make bindeb-pkg
        # never triggers an interactive make oldconfig mid-build.
        # olddefconfig may reset DEBUG_INFO_NONE to the Debian default,
        # so we re-apply only the DEBUG_INFO fixes afterwards.
        self._report_progress("Resolving config dependencies...", 29)
        ret = run_command_with_callback(
            "make olddefconfig", cwd=source_dir,
            stop_check=self._is_cancelled
        )
        if ret != 0:
            return False

        # Re-apply DEBUG_INFO fixes — olddefconfig resets the choice to Debian default
        for fix in self._get_debug_info_fixes():
            run_command(fix, cwd=source_dir)

        return True

    @staticmethod
    def _kernel_supports_ntsync(version: str) -> bool:
        """NTSYNC is mainlined in kernel 6.14+."""
        import re
        m = re.match(r'(\d+)\.(\d+)', version)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            return (major, minor) >= (6, 14)
        return False

    def _get_debug_info_fixes(self) -> List[str]:
        return [
            "./scripts/config --disable DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT",
            "./scripts/config --disable DEBUG_INFO_DWARF4",
            "./scripts/config --disable DEBUG_INFO_DWARF5",
            "./scripts/config --disable DEBUG_INFO_BTF",
            "./scripts/config --disable DEBUG_INFO_BTF_MODULES",
            "./scripts/config --disable DEBUG_INFO_REDUCED",
            "./scripts/config --disable DEBUG_INFO_SPLIT",
            "./scripts/config --disable DEBUG_KERNEL",
            "./scripts/config --disable DEBUG_PREEMPT",
            "./scripts/config --disable GDB_SCRIPTS",
            "./scripts/config --enable DEBUG_INFO_NONE",
        ]

    def _get_config_fixes(self, secure_boot_key: Optional[str] = None) -> List[str]:
        fixes = [
            './scripts/config --set-str SYSTEM_TRUSTED_KEYS ""',
            './scripts/config --set-str SYSTEM_REVOCATION_KEYS ""',
        ] + self._get_debug_info_fixes()
        if secure_boot_key:
            fixes += [
                "./scripts/config --enable MODULE_SIG",
                "./scripts/config --enable MODULE_SIG_ALL",
                f'./scripts/config --set-str MODULE_SIG_KEY "{secure_boot_key}"',
            ]
        else:
            fixes += [
                "./scripts/config --disable MODULE_SIG",
                "./scripts/config --disable MODULE_SIG_ALL",
            ]
        return fixes

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, version: str) -> bool:
        """Compile the kernel as Debian packages."""
        source_dir = os.path.join(self._build_dir, f"linux-{version}")
        cpu_count = get_cpu_count()

        self._report_progress(f"Compiling with {cpu_count} cores...", 30)

        cmd = (
            f'C_INCLUDE_PATH="/usr/include/$(gcc -print-multiarch 2>/dev/null)" '
            f'KDEB_PKGVERSION=1 '
            f'make -C "{source_dir}" -j{cpu_count} bindeb-pkg'
        )

        res = run_command(f"find {source_dir} -name '*.c' | wc -l")
        total_files = max(int(res.stdout.strip()), 15000) if res.returncode == 0 else 15000
        compiled_count = 0

        def line_callback(line: str) -> None:
            nonlocal compiled_count
            if any(x in line for x in [' CC ', ' LD ', ' AR ']):
                compiled_count += 1
                percent = min(30 + int((compiled_count / total_files) * 60), 90)
                self._report_progress(line[:80].strip(), percent)
            elif any(x in line for x in ['Packaging', 'dpkg-deb', 'Wrote:', 'dpkg-gencontrol']):
                self._report_progress("Packaging .deb files...", -1)
            elif line.strip():
                self._report_progress(line[:80].strip(), -1)

        exit_code = run_command_with_callback(
            cmd, cwd=source_dir,
            line_callback=line_callback,
            stop_check=self._is_cancelled
        )
        return exit_code == 0 and not self._is_cancelled()

    # ------------------------------------------------------------------
    # Package Discovery (isolated subdirectories like legacy)
    # ------------------------------------------------------------------

    def find_existing_packages(self, version: str, custom_name: str, 
                               profile: KernelProfile) -> List[str]:
        """Find packages in isolated subdirectories, excluding debug packages."""
        import re
        
        suffix = f"{custom_name}-{profile.suffix}" if profile.suffix else custom_name
        v_short = version
        v_long = f"{version}.0" if version.count('.') == 1 else version
        v_debian_rc = re.sub(r'^(\d+\.\d+)(-rc\d+)$', r'\1.0\2', version)
        
        # Build potential subdirectory names where packages might be isolated
        potential_subdirs = [
            f"{v_short}-{suffix}",
            f"{v_long}-{suffix}",
            f"{v_debian_rc}-{suffix}",
            v_short, v_long, v_debian_rc
        ]
        
        search_dirs = []
        for s in potential_subdirs:
            search_dirs.append(os.path.join(self._build_dir, s))
        search_dirs.append(self._build_dir)
        search_dirs.append(os.path.join(self._build_dir, f"linux-{version}"))
        
        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            
            deb_files = glob.glob(os.path.join(d, "*.deb"))
            
            # Filter by version match
            def _ver_match(f):
                b = os.path.basename(f).lower()
                return (v_short in b or v_long in b or v_debian_rc in b)
            
            # Filter by suffix match
            def _suffix_match(f):
                return suffix in os.path.basename(f).lower()
            
            # Select: image/headers only, exclude debug packages
            images = [
                f for f in deb_files 
                if _ver_match(f) and _suffix_match(f) 
                and ("linux-image" in os.path.basename(f) or "linux-bin" in os.path.basename(f))
                and "-dbg" not in os.path.basename(f)
            ]
            headers = [
                f for f in deb_files 
                if _ver_match(f) and _suffix_match(f) 
                and "linux-headers" in os.path.basename(f)
                and "-dbg" not in os.path.basename(f)
            ]
            # Also include libc-dev if present (doesn't require suffix match)
            libc = [
                f for f in deb_files 
                if _ver_match(f)
                and "linux-libc-dev" in os.path.basename(f)
            ]
            
            if images and headers:
                images.sort(key=os.path.getmtime, reverse=True)
                headers.sort(key=os.path.getmtime, reverse=True)

                pkg_set = [os.path.abspath(images[0]), os.path.abspath(headers[0])]
                if libc:
                    libc.sort(key=os.path.getmtime, reverse=True)
                    pkg_set.append(os.path.abspath(libc[0]))
                return pkg_set
        
        return []

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def install(self, version: str, profile: KernelProfile,
                custom_name: str = "soplos",
                secure_boot: bool = False,
                patch_ids: Optional[List[str]] = None) -> bool:
        """Install built .deb packages and regenerate initramfs with Dracut."""
        source_dir = os.path.join(self._build_dir, f"linux-{version}")

        # Find isolated packages (excludes debug by design)
        self._report_progress("Locating kernel packages...", 91)
        deb_files = self.find_existing_packages(version, custom_name, profile)
        
        if not deb_files:
            # Fallback: raw search (for compatibility)
            deb_search_dirs = [self._build_dir, source_dir]
            deb_files = []
            for d in deb_search_dirs:
                if os.path.isdir(d):
                    deb_files.extend(glob.glob(os.path.join(d, "*.deb")))
            
            # Filter: image, headers, and libc-dev; exclude debug
            deb_files = [
                f for f in deb_files
                if (
                    "linux-image" in os.path.basename(f)
                    or "linux-headers" in os.path.basename(f)
                    or "linux-libc-dev" in os.path.basename(f)
                )
                and "-dbg" not in os.path.basename(f)
            ]

        if not deb_files:
            self._report_progress("Error: No .deb packages found after build.", -1)
            return False
        
        # Isolate packages in a subdirectory (like legacy does)
        # Determine kernel release for subdirectory name
        kernel_release_file = os.path.join(source_dir, "include", "config", "kernel.release")
        if os.path.exists(kernel_release_file):
            with open(kernel_release_file, 'r') as f:
                kernel_release = f.read().strip()
        else:
            kernel_release = self._find_installed_release(version, custom_name, profile)
            if not kernel_release:
                kernel_release = f"{version}-{custom_name}-{profile.suffix}" if profile.suffix else f"{version}-{custom_name}"
        
        # Create isolated directory and move packages there
        target_dir = os.path.join(self._build_dir, kernel_release)
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception:
                pass
        
        final_install_set = []
        for p in deb_files:
            if os.path.dirname(p) != target_dir:
                dest = os.path.join(target_dir, os.path.basename(p))
                try:
                    shutil.move(p, dest)
                    final_install_set.append(dest)
                except Exception:
                    final_install_set.append(p)
            else:
                final_install_set.append(p)

        # Move libc-dev from build root to target_dir if not already there
        for libc in glob.glob(os.path.join(self._build_dir, "linux-libc-dev_*.deb")):
            dest = os.path.join(target_dir, os.path.basename(libc))
            try:
                shutil.move(libc, dest)
                final_install_set.append(dest)
            except Exception:
                pass

        deb_files = final_install_set

        self._report_progress("Installing kernel packages...", 96)

        pkgs = " ".join(f'"{f}"' for f in deb_files)
        install_cmd = (
            f"apt install -y --allow-downgrades --allow-change-held-packages {pkgs}"
        )

        # Store kernel release for later reference
        self.last_kernel_release = kernel_release

        # For RT kernels with NVIDIA:
        # 1. Set IGNORE_PREEMPT_RT_PRESENCE=1 so DKMS does not refuse to build
        #    the NVIDIA module when it detects CONFIG_PREEMPT_RT.  The variable
        #    must be exported into the environment inherited by apt/dkms postinst
        #    scripts, so we prepend it inline and also persist it in
        #    /etc/environment so future kernel updates work without manual steps.
        # 2. Ensure fbdev=1 is set for nvidia-drm so KMS can initialise the
        #    display correctly under PREEMPT_RT.  Must exist before dracut runs.
        pre_install_cmd = ""
        is_rt = bool(patch_ids and "rt" in patch_ids)
        if has_nvidia_gpu():
            # Apply NVIDIA DKMS source patches before apt triggers DKMS rebuild.
            # Idempotent — skips trees that are already patched.
            pre_install_cmd += get_nvidia_dkms_patch_commands() + " && "

        if is_rt and has_nvidia_gpu():
            nvidia_rt_conf = "/etc/modprobe.d/nvidia-drm-rt.conf"
            env_file = "/etc/environment"
            pre_install_cmd += (
                # fbdev=1 for nvidia-drm
                f'if ! grep -q "fbdev=1" "{nvidia_rt_conf}" 2>/dev/null; then '
                f'echo "options nvidia-drm fbdev=1" > "{nvidia_rt_conf}"; '
                f'fi && '
                # Persist IGNORE_PREEMPT_RT_PRESENCE for future kernel updates
                f'if ! grep -q "IGNORE_PREEMPT_RT_PRESENCE" "{env_file}" 2>/dev/null; then '
                f'echo "IGNORE_PREEMPT_RT_PRESENCE=1" >> "{env_file}"; '
                f'fi && '
            )
            # Also set it in the current process so apt inherits it
            install_cmd = "IGNORE_PREEMPT_RT_PRESENCE=1 " + install_cmd

        full_cmd = pre_install_cmd + install_cmd

        # Sign the kernel image with MOK key if Secure Boot is requested.
        # DKMS modules (NVIDIA etc.) are signed automatically by DKMS itself
        # using /var/lib/dkms/mok.key — do NOT touch them here.
        if secure_boot and self._secure_boot.keys_exist():
            signing_cmds = self._secure_boot.get_signing_commands(kernel_release)
            if signing_cmds:
                full_cmd += " && " + " && ".join(signing_cmds)

        def install_progress(line: str) -> None:
            if "dracut" in line.lower() or "update-initramfs" in line.lower():
                self._report_progress(f"Regenerating initramfs for {kernel_release}...", 97)
            elif "update-grub" in line.lower() or "generating grub" in line.lower():
                self._report_progress("Updating GRUB...", 98)
            else:
                self._report_progress(line[:80], -1)

        exit_code = run_privileged_with_callback(
            full_cmd, line_callback=install_progress,
            stop_check=self._is_cancelled
        )

        if exit_code != 0:
            if os.path.exists(f"/boot/vmlinuz-{kernel_release}"):
                self._report_progress(
                    f"⚠ DKMS module build failed (likely NVIDIA driver incompatibility). "
                    f"Kernel is installed. To fix, reinstall NVIDIA drivers from soplos-welcome.", -1
                )
            else:
                self._report_progress("Error installing kernel packages.", -1)
                return False

        self._report_progress("Installation complete.", 100)
        return True

    def _find_base_config(self) -> str:
        """Return the config of the Debian stock kernel, not the running custom one.
        Falls back to the running kernel's config if no stock kernel is found."""
        candidates = sorted([
            c for c in glob.glob("/boot/config-*")
            if "soplos" not in c
        ])
        if candidates:
            return candidates[-1]
        # Fallback: use the currently running kernel's config
        result = run_command("uname -r")
        running = result.stdout.strip() if result.returncode == 0 else ""
        fallback = f"/boot/config-{running}" if running else ""
        if fallback and os.path.exists(fallback):
            return fallback
        self._report_progress(
            "⚠ No stock Debian kernel config found — using first available config.", -1
        )
        all_configs = sorted(glob.glob("/boot/config-*"))
        return all_configs[-1] if all_configs else "/boot/config"

    def _find_installed_release(self, version: str, custom_name: str,
                                 profile: KernelProfile) -> Optional[str]:
        """Find the kernel release string from /boot after install."""
        suffix = f"{custom_name}-{profile.suffix}" if profile.suffix else custom_name
        import glob as glob_mod
        for vmlinuz in glob_mod.glob(f"/boot/vmlinuz-*{version}*{suffix}*"):
            return os.path.basename(vmlinuz).replace("vmlinuz-", "")
        # Fallback
        for vmlinuz in glob_mod.glob(f"/boot/vmlinuz-*{version}*"):
            return os.path.basename(vmlinuz).replace("vmlinuz-", "")
        return None

    # ------------------------------------------------------------------
    # Remove
    # ------------------------------------------------------------------

    def remove_kernel(self, kernel_release: str) -> bool:
        """Remove an installed kernel and all associated files."""
        if not re.match(r'^[0-9]+\.[0-9]+[a-zA-Z0-9._+-]*$', kernel_release):
            self._report_progress(f"Error: invalid kernel release name '{kernel_release}'", -1)
            return False
        self._report_progress(f"Removing kernel {kernel_release}...", -1)
        cmd = (
            # Remove .deb packages correctly using apt so metapackages are uninstalled automatically
            f"apt remove --purge -y linux-image-{kernel_release} linux-headers-{kernel_release} && apt autoremove --purge -y && "
            # Remove any leftover boot files
            f"rm -f /boot/vmlinuz-{kernel_release} "
            f"/boot/initrd.img-{kernel_release} "
            f"/boot/System.map-{kernel_release} "
            f"/boot/config-{kernel_release} && "
            # Remove modules directory if dpkg purge left it
            f"rm -rf /lib/modules/{kernel_release} && "
            # Remove leftover header sources if any
            f"rm -rf /usr/src/linux-headers-{kernel_release} && "
            # Remove DKMS artifacts for this kernel (only if dkms is installed)
            f"command -v dkms >/dev/null 2>&1 && dkms remove --all -k {kernel_release} 2>/dev/null || true && "
            # Clean up nvidia-drm RT config if no other RT kernels remain installed.
            # By this point /boot/config-{kernel_release} is already deleted, so grepping
            # the remaining /boot/config-* files is sufficient to detect surviving RT kernels.
            f"if [ -f /etc/modprobe.d/nvidia-drm-rt.conf ] && "
            f"! grep -rl 'CONFIG_PREEMPT_RT=y' /boot/config-* 2>/dev/null | grep -q .; then "
            f"rm -f /etc/modprobe.d/nvidia-drm-rt.conf; "
            f"fi && "
            f"update-grub"
        )
        return run_privileged(cmd).returncode == 0

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_build_files(self) -> bool:
        """Delete the build directory."""
        try:
            if os.path.exists(self._build_dir):
                shutil.rmtree(self._build_dir)
            return True
        except Exception as e:
            print(f"Cleanup error: {e}", file=sys.stderr)
            return False

