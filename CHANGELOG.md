# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/en/).

## [1.0.2] - 2026-08-17

### Fixed

- **x86-64 ISA level (march) patch silently never applied on any kernel
  other than exactly 7.1.x.** `_download_march()` requested a `7.x`-tagged
  fallback file for anything else, but that file never existed in
  `soplos-cpu-kernel-patch` — the download 404'd, `_download_march()`
  returned `None`, and the build proceeded without the patch. Builds
  requesting v2/v3/v4 silently fell back to v1 with no visible error.
  First surfaced when kernel 7.2 was released. Simplified the tag logic to
  always request the `7.x` file (now the only one that exists, verified to
  apply unchanged across 7.1.x and 7.2 — see `soplos-cpu-kernel-patch`
  1.0.1). The `7.1`-specific branch that caused the 404 is gone.

### Notes

- Revision was at the `-9` cap — bumped the base version and dropped the
  revision suffix instead of creating a `-10` (also applied to the in-app
  footer version, since it already uses the same bare `X.Y.Z` format).
- BORE, X3D and Zen also needed rebases for kernel 7.2 to become buildable
  again — those live entirely in `bore-soplos`, `x3d-soplos` and
  `zen-soplos` respectively, no code changes needed here beyond the march
  fix above (the existing fallback chains and tag logic already routed
  correctly once those repos had the right files).

## [1.0.1-9] - 2026-08-13

### Added

- **Unattended release build** (Stock mode): builds every kernel of a release
  one after another with no interaction — 6 variants for v1 and v2 plus x3d for
  v3 and v4. Destination folder and core count are chosen once, dependencies are
  resolved once, and the machine is kept awake for the whole queue.
  - Every kernel starts from a completely fresh build directory: it is deleted
    before the build and again after its packages have been copied out. No
    sources, patches or object files are ever reused between kernels.
  - Packages are saved to `<destination>/<version>/V1` through `V4`, created on
    demand as each level completes.
  - The queue stops at the first failure and keeps that build directory intact,
    so the build log and the sources of the failing kernel survive for
    inspection.
  - Uses the existing build screen, with its live log, system stats and cancel
    button. The cancel button stops the whole queue, not just the current
    kernel.

### Fixed

- **The x86-64 architecture level was never applied.** The build set
  `CONFIG_GENERIC_CPU{2,3,4}`, symbols that do not exist in mainline — they come
  from an out-of-tree patch that was never applied. `scripts/config` wrote them,
  `olddefconfig` dropped them without a word, and every kernel was compiled at
  the v1 baseline. Kernels named `-v2`, `-v3` and `-v4` were byte-identical to
  `-v1` apart from `CONFIG_LOCALVERSION`. This affected every release built with
  the selector since 1.0.1, including the published 7.1.4, 7.1.5 and 7.1.7
  kernel sets.
  - The level now comes from
    [SoplosLinux/soplos-cpu-kernel-patch](https://github.com/SoplosLinux/soplos-cpu-kernel-patch),
    which adds a proper Kconfig choice (`X86_64_ISA_V1` to `V4`) and the matching
    `-march=x86-64-v{2,3,4}` branches in `arch/x86/Makefile`. Mainline only
    offers `X86_NATIVE_CPU` (`-march=native`), which targets the build machine
    and cannot be redistributed.
  - The patch is downloaded and applied automatically whenever the level is
    above v1, with or without other patches selected. It never appears in the
    package name or the installation history.
  - **The build now aborts** if the level symbol does not survive
    `olddefconfig`, instead of silently producing a mislabelled kernel.
  - Verified on 7.1.8 binaries: the v1 `ext4` module contains 1 BMI1/BMI2
    instruction, the v3 one contains 627.

### Changed

- v1 no longer writes any architecture symbol at all. It is the upstream
  baseline and now builds exactly as vanilla does.

### Translations

- Translated the batch interface into all eight languages, plus six older
  strings that had been left untranslated since 1.0.1-7: `Profile:`,
  `Version:`, `Cores to use for compilation:`, its tooltip, the empty-filter
  message and the build directory deletion error.

### Known limitation

- **v4 produces the same binary as v3.** The only difference between the two
  levels is AVX-512, and the kernel disables vector code generation
  (`-mno-avx`), so nothing changes. Confirmed on 7.1.8: the disassembly of the
  v3 and v4 modules is identical, zero lines differ. v4 is kept for catalogue
  consistency.

## [1.0.1-8] - 2026-07-28

### Fixed
- **NVIDIA DKMS patch silently skipped on open kernel modules**: `get_nvidia_dkms_patch_commands()` only looked for `nvidia/nv-mmap.c` inside each `/usr/src/nvidia-*/` tree. The `nvidia-open-590` and `nvidia-open-610` packages keep their sources under `kernel-open/nvidia/`, so the patch was skipped without a word on every system using them — which is now everything Turing and newer. Both layouts are walked now.
- **Failed-patch warning on sources that do not need it**: the patch was attempted unconditionally, printing a "patch failed" warning on driver versions that no longer use the old VMA locking API. It is now applied only when `VMA_LOCK_OFFSET` is actually present in the source.

### Removed
- Dead constants `DRACUT_CONF_DIR` and `DRACUT_SOPLOS_CONF` in `core/installer.py`: defined but never referenced anywhere in the project.

## [1.0.1-7] - 2026-07-26

### Added
- **Core count selector**: the "Compile kernel" tab now has a spin button ("Cores to use for compilation") next to the cleanup checkbox, defaulting to all logical cores. Available for both regular profiles and Stock/developer mode — not gated behind either. Threaded through `full_install()` → `installer.build()`; `make -j{n}` uses the chosen value instead of always auto-detecting.
- **Soplos Kernels tab: profile/version filters**: two dropdowns ("Profile" and "Version") above the kernel list, populated dynamically from the packages actually present in the repo (so a newly published flavor like Zen shows up on its own, nothing hardcoded). Filtering by profile, by march level (V1–V4), or both.

### Fixed
- Changing a kernel-list filter left the "Install"/"Remove" buttons blank until something else (like clicking Refresh) triggered a full re-render — `_rebuild_kernels_list()` recreates buttons without a label, and only `_refresh_soplos_kernels_tab()` actually sets it. Filter changes now trigger both.
- The filter row was visually stuck to the top of the kernel list with no clear boundary — moved into its own card (same visual pattern as the repository status and kernel list cards) instead of a single-pixel in-card separator that wasn't noticeable on the dark theme.

## [1.0.1-6] - 2026-07-26

### Fixed
- **BORE/Zen patch source selection**: a patch source (e.g. firelzrd's BORE, zen-kernel's official Zen release) could download successfully and still fail to apply against the current kernel point release — the failure only surfaced during the actual `patch` apply step, by which point it was too late to fall back to another source. Downloaded BORE/Zen candidates are now verified with a `patch --dry-run` against the extracted kernel tree before being accepted; if a source downloads fine but doesn't apply, the next source in the chain is tried automatically instead of aborting the build.
- **Zen's alternate scheduler never actually built**: selecting the "zen" patch applied the full patchset and the build succeeded, but the kernel silently ran mainline CFS/EEVDF instead of BMQ/PDS — `CONFIG_SCHED_ALT` (unlike BORE's `CONFIG_SCHED_BORE`) defaults to `n` in Kconfig, so it needed to be forced on explicitly. `configure()` now enables `CONFIG_SCHED_ALT` and `CONFIG_SCHED_PDS` (the patch's own default scheduler choice) whenever "zen" is selected. Verified on real hardware: `CONFIG_SCHED_ALT=y`/`CONFIG_SCHED_PDS=y` in the running kernel's config, and Project C-specific sysctls (`kernel.yield_type`) present while CFS-only sysctls (`sched_cfs_bandwidth_slice_us`, `sched_util_clamp_*`, etc.) are gone, confirming PDS is genuinely active — not just compiled in.

### Added
- **BORE**: new third fallback source, [SoplosLinux/bore-soplos](https://github.com/SoplosLinux/bore-soplos), used only when neither firelzrd nor CachyOS have a working patch for the requested kernel version yet.
- **Zen**: new fallback source, [SoplosLinux/zen-soplos](https://github.com/SoplosLinux/zen-soplos), used when zen-kernel/zen-kernel hasn't published a matching release yet.

## [1.0.1-5] - 2026-07-22

### Changed
- **"Which kernel is right for my hardware?" popup**: now also shows the detected CPU model, GPU, and total RAM alongside the supported x86-64 architecture level, giving users a fuller picture of their hardware before picking a kernel package.

## [1.0.1-4] - 2026-07-20

### Changed
- **"Which kernel is right for my hardware?" button**: no longer opens the wiki page. It now detects the highest x86-64 architecture level (v1–v4) the CPU actually supports and shows it directly, so users know which kernel package variant to pick from the list without leaving the app.

## [1.0.1-3] - 2026-07-20

### Fixed
- **X3D VCache selection could leave an incompatible patch checked**: selecting X3D force-enables BORE, but since that happened while patch-toggle signals were blocked, BORE's own "uncheck Zen (incompatible)" logic never ran — Zen could stay checked alongside BORE+X3D if it was already active, sending a broken patch combination to the build. Now X3D's auto-select also clears whatever is incompatible with BORE.

## [1.0.1-2] - 2026-07-18

### Fixed
- **X3D VCache patch download**: now uses a per-kernel-version URL (6.x/7.0/7.1) instead of a single stale link that no longer existed in the source repository.
- **Base kernel configuration**: now fetched fresh from Debian sid on every build instead of copying the config of a previously installed kernel — avoids configuration drift accumulating across builds and missing support for recently-added hardware.
- **Build failure from inherited module signing key path**: the base config's `MODULE_SIG_KEY` could point to a path that only exists inside Debian's own build system, breaking `dpkg-buildpackage` at the certs stage. Now reset to the kernel's own default path when no custom Secure Boot key is set.
- **Patch tooltips always in English**: the patch descriptions (BORE, PREEMPT_RT, Zen, NTSYNC, X3D VCache) shown on hover in the Patches selector were never passed through the translation system. Now properly localized; added missing translations for the NTSYNC and X3D VCache descriptions in all 8 languages.

### Added
- **Handheld gaming EC drivers**: `ASUS_ARMOURY` (ROG Ally/Ally X) and `OXP_EC` (OneXPlayer/AYANEO) are now forced as modules in every build.
- **March level guardrail**: v1/v2 CPU architecture levels are now disabled automatically when the X3D patch is selected, since X3D hardware requires at least x86-64-v3.

## [1.0.1-1] - 2026-07-16

### Fixed
- **Soplos Kernels tab**: Package filter regex now accepts march-level suffixes (`v1`–`v4`) so packages like `linux-soplos-bore-v3` are listed correctly.
- **Soplos Kernels tab**: Display name now shows the march level separately — `linux-soplos-v3` → "Stock V3", `linux-soplos-bore-v3` → "BORE V3".

## [1.0.1] - 2026-07-16

### Added
- **x86-64 march level selector** (Stock mode): Build kernels targeting v1 (Generic), v2 (SSE4.2+), v3 (AVX2+) or v4 (AVX-512) microarchitecture levels via `CONFIG_GENERIC_CPU{2,3,4}`.
- **X3D VCache scheduler patch** (Stock mode only): Original Soplos patch that detects asymmetric L3 cache topology on AMD Ryzen X3D dual-CCD processors and steers tasks to the VCache CCD using a load-balanced hook in `select_task_rq_fair()`. Auto-selects BORE + NTSYNC; kernel named `soplos-x3d-vN`.
- **Auto-generated kernel name** in Stock mode: Name field is read-only and computed from the selected patch set and march level.
- **Wiki info button** in Soplos Kernels tab: Opens the CPU Compatibility guide on soplos.org to help users choose the right kernel for their hardware.

## [1.0.0-4] - 2026-06-02

### Fixed
- **NVIDIA patch in Soplos Kernels tab**: The NVIDIA VMA compatibility patch was only applied when compiling kernels from source. Now also applied before `apt install` and `apt install --only-upgrade` in the Soplos Kernels repository tab, preventing DKMS build failures on NVIDIA systems when installing or updating pre-built kernels.
- **NVIDIA VMA patch fuzz**: Added `--fuzz=5` to the patch command so the same patch applies correctly to driver versions with minor line offset differences (e.g. 580 vs 590).

## [1.0.0-3] - 2026-06-02

### Fixed
- **Spurious Update button after kernel update**: After updating a Soplos kernel, the old vmlinuz was still present in `/boot` before reboot. The vmlinuz version fallback was comparing it against the repo candidate and showing the Update button incorrectly. The fallback now only activates when the metapackage is not registered in apt (`Installed: (none)`), so if apt knows the package is up to date, it is trusted and the vmlinuz is not checked.

## [1.0.0-2] - 2026-06-02

### Fixed
- **Soplos Kernels Update button**: `apt-cache show` returns multiple stanzas when more than one version of a package is available (candidate first, installed second). The code was processing all stanzas and the last `Version:` field overwrote the first, resulting in the old version being stored. Now stops at the first blank line after reading the first stanza, so the candidate version is always used.
- **Stale package list after action**: After installing, updating or removing a Soplos kernel, the tab was refreshed using cached apt data. Replaced `_refresh_soplos_kernels_tab()` with `_fetch_soplos_packages()` in `_on_soplos_kernel_action_done` so the list is fully re-fetched from apt after every action.
- **Locale-dependent apt-cache output**: `apt-cache policy` and `apt-cache show` output field names in the system language (e.g. `Instalados:` / `Candidato:` in Spanish) instead of English. The code was looking for `Installed:` and `Candidate:` and never matching them, causing `updates[pkg]` to always be `False` and the Update button to never appear. Fixed by forcing `LC_ALL=C` on all apt-cache subprocess calls.

## [1.0.0-1] - 2026-06-02

### ✨ Added
- **Remove repository button**: New "Remove repository" button in the Soplos Kernels tab — removes `/etc/apt/sources.list.d/soplos-kernels.sources` and `/usr/share/keyrings/soplos-kernels.gpg`, then runs `apt-get update`. Already installed kernels are not affected. UI updates instantly.

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
