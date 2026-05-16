# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/en/).

## [1.0.0] - 2026-04-05

### ✨ Added
- **PREEMPT_RT Integration**: For kernels ≥6.12, PREEMPT_RT is integrated upstream — no external patch download, automatically enables `CONFIG_PREEMPT_RT=y`
- **Source Reuse**: Recycle existing kernel sources for faster subsequent compilations with automatic patch conflict detection
- **Expandable History**: Installation history with automatic kernel tags (XanMod, Liquorix, Zen, System...) and improved UI
- **Keyboard Shortcuts**: Ctrl+Q (quit), Ctrl+W (close), F5 (refresh), F1 (help/about), Ctrl+Tab / Ctrl+Shift+Tab (switch tabs)
- **About Dialog**: Application information with version, author, license and website
- **NTSYNC Patch**: Added NT synchronization primitives support for Wine/Proton gaming
- **NVIDIA Kernel 7.x Patch**: Automatically applies VMA locking API compatibility patch to NVIDIA DKMS sources before build (fixes DKMS failure on kernel 7.0+, from [SoplosLinux/nvidia-patches](https://github.com/SoplosLinux/nvidia-patches))
- **DKMS MOK Auto-Enroll**: After installation with Secure Boot active, automatically prompts to enroll the DKMS signing key when an NVIDIA GPU is detected — fixes NVENC and CUDA not working with Secure Boot
- **Save .deb Before Cleanup**: When the build directory cleanup option is active, offers to save the compiled .deb packages to a chosen folder before deleting
- **MOK Key Path in UI**: The key management dialog now shows the storage path of MOK keys so users know where to find them

### 🐛 Fixed
- **Debug Package Generation**: Fixed incorrect generation of -dbg packages by correcting `apply_to_config` method
- **History Duplicates**: Fixed duplicate entries for versions like 7.0-rc6 vs 7.0.0-rc6
- **Package Isolation**: Fixed kernel packages isolated in subdirectories (`~/kernel_build/{version}/` with image + headers + libc-dev only)
- **External Kernel Tags**: Correct automatic tagging of external kernels (XanMod, Liquorix, Zen, System...) in history
- **Patch State Tracking**: Added `.applied_patches` metadata for proper patch conflict detection during source reuse
- **Kernel Profile Bugs**: Fixed PREEMPT_DYNAMIC, HZ, THP and DEBUG_INFO Kconfig choice block handling — all profiles now compile correctly
- **GPU Detection**: NVIDIA and Intel GPU detection now checks only display/VGA/3D lines in lspci output — AMD CPU lines no longer cause false positives
- **Base Config Fallback**: Fixed `_find_base_config()` Python literal bug — now correctly uses `run_command("uname -r")` at runtime
- **Path Quoting**: Fixed missing quotes around paths in `cp` and `make -C` commands — prevents failures if paths contain spaces
- **rt-i915 Patch**: CachyOS rt-i915 fix now only downloaded on systems with an Intel GPU
- **BORE Fallback**: BORE patch now falls back to CachyOS/kernel-patches when not available in the firelzrd repo
- **Cleanup Checkbox**: The "Clean build directory after installation" checkbox now actually triggers the cleanup
- **EOL Kernel Detection**: End-of-Life kernels from kernel.org are now correctly parsed and shown as "(EOL)" in the version list with a red warning label
- **Mainline Label**: Mainline kernels (e.g. 7.0) are no longer incorrectly shown as "(latest)" — now correctly labelled "(mainline)"

### 🔒 Security
- **MOK Password Injection**: Fixed shell injection vulnerability in MOK enroll/delete/reset operations — password is now safely quoted with `shlex.quote()` before being passed to `mokutil`
- **Kernel Name Validation**: Install button now validates the custom kernel name against `[a-zA-Z0-9._-]` before proceeding — prevents invalid names reaching `scripts/config`
- **Remove Kernel Validation**: `remove_kernel()` now validates the release string against a strict regex before constructing any shell commands

### ✨ Added
- **Stock Profile** (hidden): New "Soplos Stock" kernel profile accessible via Ctrl+Shift+D — compiles a vanilla kernel with no profile modifications, suffix `soplos`, compatible with all Soplos distributions (Boro, Tyron, Tyson). Toggling the shortcut again hides the profile card and reverts to the previous selection
- **Double-click Protection**: Install button is disabled immediately on click and re-enabled only if validation fails — prevents launching duplicate builds
- **DKMS Rebuild Explanation**: MOK key dialog now explains that DKMS automatically rebuilds NVIDIA modules on each new kernel install and that those modules need the signing key enrolled to load with Secure Boot active
- **Config Resolution Pass**: A second `make olddefconfig` is now run after all profile and patch options are applied — prevents interactive configuration prompts appearing mid-build when new Kconfig symbols are introduced by a profile

### 🌍 Internationalization
- Completed 9 missing translation strings across all 8 languages (en, es, de, fr, it, pt, ro, ru): mainline label, Soplos Stock profile name and description, EOL warning markup, invalid kernel name error, DKMS enrolled/not-enrolled texts, and post-install DKMS rebuild prompt

### ✨ Added
- **Soplos Kernels Tab**: New tab to install pre-built Soplos kernels (Stock, BORE, Zen, NTSYNC, BORE+NTSYNC, Real-Time) directly from the official Soplos repository — no compilation required
- **Tabbed Interface**: Main window now uses `Gtk.Notebook` with two tabs: "Build Kernel" and "Soplos Kernels"
- **Repository Management**: One-click button to add the Soplos kernels apt repository with GPG key verification
- **Dynamic Kernel List**: Soplos Kernels tab reads available packages from apt-cache at runtime — any package added to the repository appears automatically without code changes
- **Refresh Button**: New button in the Soplos Kernels tab forces `apt-get update` and reloads the kernel list
- **Stock Profile Post-Build**: When building with the hidden Stock profile, automatically creates the corresponding metapackage .deb and prompts to save all packages (image + headers + metapackage) to a chosen folder — does not install the kernel on the system
- **Kernel Version Display**: Available version shown next to each kernel name in the Soplos Kernels tab
- **Update Button**: When a newer kernel version is available in the repository, an Update button appears — upgrades the metapackage and purges the old kernel image and headers automatically
- **Persistent Build History**: History file moved to `~/.local/share/soplos-kernel-installer/history.json` — survives build directory cleanup. Automatic migration from previous locations (`~/kernel_build/` and `~/.soplos_kernel_installer_history.json`)
- **Clean Package Naming**: Added `KDEB_PKGVERSION=1` to `make bindeb-pkg` — packages now named `linux-image-7.0.3-soplos_1_amd64.deb` instead of repeating the version twice

### 🐛 Fixed
- **MOK Signed Kernel Detection**: `sb_has_mok_signed_kernels()` now also physically verifies `/boot/vmlinuz-*` files with `sbverify --cert MOK.pem` — detects kernels signed outside the installer
- **STOCK Profile Package Naming**: Removed trailing dash from package and kernel names when building with the Stock profile (empty suffix)
- **STOCK Profile Suffix Matching**: Fixed `_suffix_match` always returning True for Stock profile — now correctly uses the computed suffix variable
- **STOCK Profile Install Fallback**: Fixed fallback name construction using `profile.suffix` (always empty for Stock) instead of the computed suffix
- **Soplos Kernels Detection**: Installed kernel detection now checks `/boot/vmlinuz-*` existence — correctly reflects actual status regardless of how the kernel was installed or removed
- **Soplos Kernels Remove Button**: Remove button stays active for installed kernels even when the repository is not configured
- **Cross-Tab Refresh**: Kernel history list refreshes automatically after install/remove from the Soplos Kernels tab
- **Kernel Release Name**: Kernel release is now read from `include/config/kernel.release` in the source tree — correctly handles patch-injected version suffixes (e.g. `zen1` added by the Zen patch to the Makefile EXTRAVERSION)
- **Stock Post-Build Package Discovery**: Fixed Stock profile post-build saving only the metapackage when a patch injects a version suffix (e.g. `zen1`) — `last_kernel_release` is now captured before the build-only return and the deb search no longer relies on a fallback name that omits the injected suffix
- **Old Kernel Cleanup on Update**: After updating a Soplos kernel via the Update button, old image and headers packages for the same kernel variant are purged — apt autoremove was insufficient because packages installed via `apt install` are marked as manually installed

### 🎨 Improved
- **Installation**: Simplified to `sudo apt install soplos-kernel-installer` only
- **Documentation**: Updated README with new features and corrected screenshot paths
- **UI**: Enhanced user experience with better feedback and navigation

---

## Types of Changes

- **Added** for new features
- **Improved** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for removed features
- **Fixed** for bug fixes
- **Security** for vulnerabilities

## Author

Developed and maintained by Sergi Perich  
Website: https://soplos.org  
Contact: info@soploslinux.com

## Contributing

To report bugs or request features:
- **Issues**: https://github.com/SoplosLinux/soplos-kernel-installer/issues
- **Email**: info@soploslinux.com

## Support

- **Documentation**: https://soplos.org
- **Community**: https://soplos.org/forums/
- **Support**: info@soploslinux.com
