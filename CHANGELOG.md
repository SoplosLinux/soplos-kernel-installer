# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/lang/en/).

## [1.0.3-6] - 2026-10-29

### Fixed

- The CPU temperature in the build panel could be a fixed board value instead of the CPU (16.8 C at full load on a Gigabyte board, 20 C on the Zyren). It took the first `coretemp`, `k10temp` or `acpitz` sensor in `/sys/class/hwmon`, whose order is not stable, and `acpitz` is often an ACPI stub. Sensors are now searched in a fixed order, `k10temp`, `coretemp`, `nct6775`, `it87` and `acpitz` last, and within a sensor the `Tctl` (AMD) or `Package`/`Core 0` (Intel) input is used, as Soplos Sys Cleaner already does.

## [1.0.3-5] - 2026-10-29

### Changed

- Every kernel must have Binder (Waydroid). A kernel whose Binder driver is dropped by `olddefconfig`, or whose `ANDROID_BINDER_DEVICES` lacks `hwbinder`/`vndbinder`, now stops the build instead of only showing a warning.
- The Binder driver is chosen from the kernel source: the C driver (`ANDROID_BINDER_IPC`) while `drivers/android/Kconfig` still has it, and the Rust driver (`ANDROID_BINDER_IPC_RUST`, with `RUST`) once mainline removes the C one. Kernels with the C driver keep building without Rust, as before. When `RUST` cannot be enabled, the error shows the output of `make rustavailable`.
- `MODVERSIONS` is always disabled. With it, Rust requires `GENDWARFKSYMS`, which requires debug info, and debug info multiplies the build time.
- The X3D VCache patch uses the dedicated x3d-soplos files for 6.12 and 7.2; `6.x` now covers 6.18 and `7.x` covers 7.3 and later (x3d-soplos 1.3.0, which fixes the CCD load counters).

### Added

- Build dependencies for the Rust Binder driver: `rustc`, `rust-src`, `bindgen` and `libclang-dev`.

## [1.0.3-4] - 2026-10-29

### Fixed

- A kernel could be built without a patch that was selected for it. When no source had a BORE, Zen or X3D patch for the kernel line (Linux 7.3), the build went on without it and the package still carried the patch name. A selected patch that cannot be downloaded now stops the build, and after the configuration step the build stops if `SCHED_BORE` (BORE, X3D) or `SCHED_ALT` (Zen) is not enabled.
- Kernels built without a Secure Boot key tainted the kernel (`8192`) on every module load. `SECURITY_LOCKDOWN_LSM` selects `MODULE_SIG`, so `olddefconfig` turned module signing back on after it was disabled. Lockdown is now disabled together with module signing when there is no key, and the build stops if `MODULE_SIG` is still enabled.
- `DRM_PANIC_SCREEN` is set to `user`. The QR code panic screen needs Rust, which Soplos kernels are built without.
- Removing a kernel no longer runs `apt autoremove --purge`, which could remove packages unrelated to the kernel.
- `apt install` and `apt remove` run with `LC_ALL=C`, so the progress is read from the English output in every interface language.
- Secure Boot signing now covers every `grubx64.efi` under `/boot/efi/EFI/`, not only the first one, for systems with more than one boot entry.
- The NVIDIA DKMS patches for VMA, `string.h` and dmem are tried with `--dry-run` first; when one does not apply the source tree is left untouched with a warning, instead of being half patched.
- Running as root no longer goes through `pkexec`, and a failed privileged command now kills its whole process group.
- Revoking the MOK key goes through the same delete routine as the rest of the MOK actions.

### Changed

- BORE is downloaded from Soplos' own bore-soplos first, then firelzrd and CachyOS, as Zen already did with zen-soplos.
- Stock builds always run with Secure Boot signing off.
- The dependency check at startup was removed; the check before each build (1.0.3-3) covers it.
- `debian/control`: added `pciutils` (`lspci` is used to detect the GPU).

### Removed

- Unused NVIDIA module signing code and `has_intel_gpu()` in `core/nvidia.py`.

## [1.0.3-3] - 2026-10-23

### Fixed

- A build could start without its dependencies. `full_install` ignored the result of the dependency check, so when the pkexec call failed or was cancelled the installer went on, and a missing `libelf-dev` only showed up deep in the compilation (`gelf.h: No such file or directory` while building objtool, Linux 7.3). It now stops with a message before downloading anything.
- `libelf-dev` was only reinstalled when it was missing, not when it was installed without `/usr/include/gelf.h`, as already done for `libssl-dev`. It is now.
- The dependency install was `apt-get update && apt-get install`, so an `apt-get update` that failed (an unreachable repository, no network) stopped the install of the missing packages. The update can now fail and the install still runs with the lists the system has.

## [1.0.3-2] - 2026-10-22

### Added

- NVIDIA DKMS patch for the Debian 550 driver on Linux 7.2+ (`NV_550_KERNEL72_COMPAT_PATCH`, Fix 6, same patch as `nvidia-patches/patches/nvidia-550-kernel7.2-compat.patch`): `linux/of_gpio.h` removed, `strncpy()` removed from `linux/string.h`, and `struct drm_atomic_state` renamed `struct drm_atomic_commit`.
- NVIDIA DKMS patch for the 590 open modules on Linux 7.2+ (`NV_590_KERNEL72_COMPAT_PATCH`, Fix 7, same patch as `nvidia-patches/patches/nvidia-590-kernel7.2-compat.patch`): the Fix 6 changes plus the `nvidia-uvm` changes NVIDIA 610 already has (`page_free` renamed `folio_free`, three-argument `zone_device_page_init()`), backported through two `conftest.sh` probes.
- Each patch is applied only when the source tree still has the text it fixes and `patch --dry-run` succeeds, so 580, 610 and already patched trees are left alone. Both build against `7.3.0-soplos-bore-ntsync-v4` and `7.2.11-soplos-bore-ntsync-v4`.

## [1.0.3-1] - 2026-10-21

### Fixed

- The NVIDIA DKMS patch for the `dmem_cgroup_register_region` change in Linux 7.3+ (`NV_DMEM_CGROUP_INIT_PATCH`) was never applied: its hunk header declared 7 old and 17 new lines while the body has 6 and 15, so `patch` rejected it as malformed and the installer only printed a warning. The header is corrected (`@@ -2818,6 +2818,15 @@`). Checked against the real NVIDIA 610.57.04 sources: it applies cleanly and the module builds against the Linux 7.3 headers, where the unpatched sources fail with `-Wint-conversion` at `os-interface.c:2820`.

## [1.0.3] - 2026-10-20

### Fixed

- Added NVIDIA DKMS compatibility patch for Linux 7.3+ kernels (`NV_DMEM_CGROUP_INIT_PATCH`). Fixes `-Wint-conversion` build error in `nvidia/os-interface.c` (`dmem_cgroup_register_region` API signature update introduced in kernel 7.3).

## [1.0.2-9] - 2026-10-04

### Added

- Support for Linux 7.2.9 Zen kernel patch (`0001-zen-7.2.9.patch`) in `_download_zen_soplos()`.

### Fixed

- Enhanced Zen patch downloader (`_download_zen_soplos()`) to check for exact kernel version patches (`0001-zen-{version}.patch`) before falling back to major_minor line patches (`0001-zen-{major_minor}.patch`).

## [1.0.2-8] - 2026-10-03

### Fixed

- Zen patch source priority was backwards: `_download_zen()` tried zen-kernel/zen-kernel's own upstream releases first and only fell back to `SoplosLinux/zen-soplos` if no matching release existed. Kernel 7.2.9 V3/V4 builds failed because the official zen-kernel release for that version carries its own `CONFIG_X86_64_VERSION` march mechanism in `arch/x86/Makefile`, which conflicts with Soplos' own x86-64 ISA-level patch applied afterward. `zen-soplos` is now tried first; zen-kernel/zen-kernel is only a fallback when zen-soplos has no patch for the line yet or it doesn't apply.

## [1.0.2-7] - 2026-09-20

### Fixed

- RT kernels shipped without the Intel graphics driver. Mainline declares `DRM_I915` as `depends on !PREEMPT_RT`, so `olddefconfig` dropped it silently on every RT build (7.0.3 through 7.2.6), and any machine with an Intel iGPU booted to a black screen with a blinking cursor. The only fix the installer knew, a third-party `rt-i915` patch, was downloaded only when the machine doing the build had an Intel GPU, which the build VM does not. RT builds now always apply Soplos' own patch from `SoplosLinux/rt-i915-soplos` (checked with a dry-run apply before it is accepted), and stop after `olddefconfig` if `DRM_I915` did not survive, instead of producing a kernel that cannot boot on Intel. The third-party download was removed.

### Notes

- The patch is compile-tested on 7.2.6 with and without PREEMPT_RT, but not boot-tested yet: see the rt-i915-soplos README before publishing an RT kernel built with it.
- There is only a 7.2 patch so far. An RT build of any other kernel line stops at the `DRM_I915` check until a patch for that line exists.

## [1.0.2-6] - 2026-09-14

### Fixed

- RC, LTS and EOL kernels shared the exact same Stock package name as the regular stable line (e.g. `linux-soplos-v1`), only the kernel version differing. That is unsafe two ways over: an RC build could silently replace a stable kernel on a plain `apt upgrade`, and LTS/EOL kernel versions compare as *lower* than the current stable in Debian version ordering, so reprepro refused to publish them at all ("as it has already <higher version>"). Stock builds (both the single-kernel flow and the batch release queue) now insert a channel marker into the package name — `linux-soplos-rc-v1`, `linux-soplos-lts-v1`, `linux-soplos-eol-v1` — based on the selected kernel's real channel from kernel.org, so each channel gets its own package identity instead of colliding with stable.

## [1.0.2-5] - 2026-09-10

### Fixed

- **`CONFIG_ANDROID_BINDER_IPC`** is a plain `bool` in Kconfig
  (`drivers/android/Kconfig`), not a tristate. The 1.0.2-4 attempt to enable
  it as a module (`--module`, i.e. `=m`) was an invalid value for a bool
  symbol, silently normalized back to `n` by `make olddefconfig` — every
  7.2.4 kernel already published with that build never actually had Waydroid
  support. Now enabled with `--enable` (the only valid form for this
  symbol), plus a post-`olddefconfig` check that warns instead of failing
  silently if it's ever dropped again for any other reason.

### Added

- Stock batch build (`core/batch.py`, `BatchBuilder.run()`) gained a
  `revision` counter: 0 (default) means a brand new kernel version that was
  never built before — no extra number anywhere in the resulting `.deb`
  files, unchanged from before. 1, 2, 3... mean this is the 1st, 2nd, 3rd
  recompile of the SAME kernel version with different patches/fixes, so
  `apt`/`reprepro` see the new build as a real upgrade instead of colliding
  on an identical package name+version with the previous one. The internal
  Debian revision (`KDEB_PKGVERSION`) is offset by one from what the user
  enters, since the very first build of any version already implicitly uses
  revision 1 — entering "1" for the first recompile is guaranteed to produce
  a genuinely new, working package on its own. New "Revision" spinner in the
  batch build page of the UI.

## [1.0.2-4] - 2026-09-09

### Added

- **`CONFIG_ANDROID_BINDER_IPC`** enabled as a module on every build, giving
  Waydroid support with no kernel patch needed. Built as `=m` on purpose:
  users who never use Waydroid never load the module, at no cost. Device
  names (`binder,hwbinder,vndbinder`) are left for whoever loads it
  (`modprobe` options), not fixed at compile time.

## [1.0.2-3] - 2026-08-28

### Added

- **`CONFIG_CGROUP_DMEM`** enabled unconditionally on every build (device/VRAM
  memory accounting cgroup, disabled by default in the Debian base config).
  It's a compile-time flag with nothing that uses it yet, but baking it in
  now avoids a forced recompile-and-republish cycle once
  `soplos-game-daemon` actually needs it. A dropped symbol after
  `olddefconfig` only warns, unlike the march level check, since nothing
  depends on it yet.

## [1.0.2-2] - 2026-08-18

### Added

- **March (x86-64 psABI) selector available for every profile**, not just
  Stock — Gaming, Audio/Video, Minimal/Office and Automatic builds can now
  pick V1-V4 too, instead of always building at the compiler default.
- **Kernel selection for the Stock batch build**: a "Select kernels..."
  dialog lists all 26 jobs of the release queue with checkboxes, instead
  of always building all-or-nothing.
- **Resume for the Stock batch build**: a checkbox skips any kernel whose
  metapackage `.deb` already exists in the destination folder, so a queue
  that failed partway through can continue from where it stopped instead
  of rebuilding everything from V1.

### Fixed

- **The march selector never appeared for the default profile at
  startup**: `ProfileSelector`'s first radio button is already
  `active=True` when the group is created, so its own `set_active(True)`
  call was a no-op and never emitted `toggled` — `profile-changed` (and
  everything that listens for it, march selector visibility included)
  only ever fired when the user switched profiles by hand, never for the
  profile shown on launch. Synced explicitly once after the window is
  built.
- **A V3/V4 build outside Stock mode looked identical to a V1 one**: the
  march selector applied to the build (see Added, above) but was never
  reflected in the kernel's name for non-Stock profiles, unlike Stock's
  own auto-generated name. The march level is now appended to the name
  (and its live preview) whenever it isn't the default v1.
- **The batch "Build all 26 kernels" button kept its label after
  narrowing the selection**: it always said "26" regardless of how many
  kernels were actually checked in the selection dialog. Now reads
  "Build N selected kernels" and only says "all 26" when every job is
  selected.

## [1.0.2-1] - 2026-08-17

### Fixed

- **NVIDIA DKMS build failure on kernel 7.2+**: `nvidia/os-interface.c`
  calls `strncpy()` without including `<linux/string.h>`, relying on some
  other kernel header (reached transitively) to provide the declaration.
  That transitive include disappeared starting with kernel 7.2, and GCC
  treats an implicit function declaration as a hard error, so DKMS builds
  failed outright (`implicit declaration of function 'strncpy'`). Added a
  new embedded compatibility patch in `core/nvidia_dkms_patch.py`
  (`NV_STRING_H_PATCH`) that adds the missing include, applied
  automatically alongside the existing VMA-locking fix — same mechanism,
  same idempotency guard, unrelated issue (different file, different API,
  different kernel boundary). Mirrored in the standalone `nvidia-patches`
  repo as Fix 4 (`patches/nvidia-string-h-kernel7.2.patch`).

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
