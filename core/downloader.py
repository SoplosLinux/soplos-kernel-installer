"""
Downloader module for fetching kernel sources and patches.

Kernel sources: cdn.kernel.org / git.kernel.org
Patches:
  - BORE:       github.com/firelzrd/bore-scheduler
  - PREEMPT_RT: www.kernel.org/pub/linux/kernel/projects/rt
  - Zen:        github.com/zen-kernel/zen-kernel (releases)
  - NTSYNC:     config option only (mainlined in 6.14+), no patch file
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from typing import List, Optional, Callable, Dict
from .common_types import KernelVersion, PatchInfo
from utils.system import ensure_directory, run_command_with_callback

KERNEL_CDN_URL = "https://cdn.kernel.org/pub/linux/kernel"
KERNEL_ORG_URL = "https://www.kernel.org/"

BORE_GITHUB_TREE = "https://github.com/firelzrd/bore-scheduler/tree/main/patches/{tree}/linux-{major_minor}-bore"
BORE_RAW_BASE = "https://raw.githubusercontent.com/firelzrd/bore-scheduler/main/patches/{tree}/linux-{major_minor}-bore/{filename}"
CACHY_RAW_BASE = "https://raw.githubusercontent.com/CachyOS/kernel-patches/master/{major_minor}/{subdir}/{filename}"
RT_BASE_URL = "https://www.kernel.org/pub/linux/kernel/projects/rt/{major_minor}/"
ZEN_RELEASES_WEB = "https://github.com/zen-kernel/zen-kernel/releases"


class KernelDownloader:
    """Handles fetching available versions and downloading kernel sources + patches."""

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

    # ------------------------------------------------------------------
    # Version listing
    # ------------------------------------------------------------------

    def fetch_available_versions(self) -> List[KernelVersion]:
        """Fetch available kernel versions from kernel.org."""
        versions = []
        try:
            req = urllib.request.Request(
                KERNEL_ORG_URL,
                headers={'User-Agent': 'Mozilla/5.0 SoplosKernelInstaller/1.0'}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode('utf-8')

            row_pattern = re.compile(
                r'(<tr[^>]*>.*?</tr>)',
                re.IGNORECASE | re.DOTALL
            )
            cell_pattern = re.compile(
                r'<td[^>]*>\s*(\w+):?</td>\s*<td[^>]*>\s*<strong>\s*'
                r'([0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-rc\d+)?)',
                re.IGNORECASE | re.DOTALL
            )

            seen = set()
            first_stable = True

            for row_match in row_pattern.finditer(html):
                row_html = row_match.group(1)
                cell_match = cell_pattern.search(row_html)
                if not cell_match:
                    continue

                kernel_type = cell_match.group(1).lower()
                version = cell_match.group(2)
                if version in seen:
                    continue
                seen.add(version)

                is_eol = 'eolkernel' in row_html
                major = version.split('.')[0]

                if '-rc' in version:
                    url = f"https://git.kernel.org/torvalds/t/linux-{version}.tar.gz"
                    versions.append(KernelVersion(
                        version=version, url=url,
                        channel="rc", is_rc=True
                    ))
                elif kernel_type == 'stable':
                    url = f"{KERNEL_CDN_URL}/v{major}.x/linux-{version}.tar.xz"
                    is_latest = first_stable and not is_eol
                    if not is_eol:
                        first_stable = False
                    versions.append(KernelVersion(
                        version=version, url=url,
                        channel="stable", is_latest=is_latest, is_eol=is_eol
                    ))
                elif kernel_type == 'mainline':
                    url = f"{KERNEL_CDN_URL}/v{major}.x/linux-{version}.tar.xz"
                    versions.append(KernelVersion(
                        version=version, url=url,
                        channel="mainline", is_mainline=True
                    ))
                elif kernel_type == 'longterm':
                    url = f"{KERNEL_CDN_URL}/v{major}.x/linux-{version}.tar.xz"
                    versions.append(KernelVersion(
                        version=version, url=url,
                        channel="lts", is_longterm=True
                    ))

            def _ver_key(v):
                m = re.match(r'(\d+)\.(\d+)(?:\.(\d+))?(?:-rc(\d+))?', v.version)
                if m:
                    major = int(m.group(1) or 0)
                    minor = int(m.group(2) or 0)
                    patch = int(m.group(3) or 0)
                    rc    = int(m.group(4)) if m.group(4) else 999
                    return (-major, -minor, -patch, -rc)
                return (0, 0, 0, 0)

            versions.sort(key=_ver_key)

        except Exception as e:
            print(f"Error fetching kernel versions: {e}", file=sys.stderr)

        return versions

    # ------------------------------------------------------------------
    # Kernel source download
    # ------------------------------------------------------------------

    def reextract(self, version: str) -> bool:
        """Re-extract kernel sources from cached tarball without re-downloading."""
        import shutil
        source_dir = os.path.join(self._build_dir, f"linux-{version}")

        for ext in ("tar.gz", "tar.xz"):
            tarball = os.path.join(self._build_dir, f"linux-{version}.{ext}")
            if os.path.exists(tarball):
                self._report_progress("Re-extracting sources from cached tarball...", 5)
                patches_dir = os.path.join(self._build_dir, "patches")
                for path in (source_dir, patches_dir):
                    try:
                        shutil.rmtree(path)
                    except Exception:
                        pass

                def tar_callback(line: str) -> None:
                    if line.strip():
                        self._report_progress(line.strip()[:80], -1)

                exit_code = run_command_with_callback(
                    f'tar -xvf "{tarball}"',
                    cwd=self._build_dir,
                    line_callback=tar_callback,
                    stop_check=self._is_cancelled
                )
                if exit_code == 0 and os.path.exists(os.path.join(source_dir, "Makefile")):
                    self._report_progress("Re-extraction complete.", 15)
                    return True
                self._report_progress("Error re-extracting sources.", -1)
                return False

        self._report_progress("Error: Cached tarball not found. Download the kernel first.", -1)
        return False

    def download(self, version: str, skip_download: bool = False) -> bool:
        """Download and extract kernel sources."""
        if skip_download:
            source_dir = os.path.join(self._build_dir, f"linux-{version}")
            if os.path.isdir(source_dir):
                self._report_progress("Using existing sources...", 100)
                return True
            self._report_progress("Error: Source directory not found.", -1)
            return False

        self._report_progress(f"Preparing download for Linux {version}...", 0)

        if not ensure_directory(self._build_dir):
            self._report_progress("Error: Could not create build directory", -1)
            return False

        major = version.split('.')[0]

        if '-rc' in version:
            url = f"https://git.kernel.org/torvalds/t/linux-{version}.tar.gz"
            extension = "tar.gz"
        else:
            url = f"{KERNEL_CDN_URL}/v{major}.x/linux-{version}.tar.xz"
            extension = "tar.xz"

        tarball = os.path.join(self._build_dir, f"linux-{version}.{extension}")
        source_dir = os.path.join(self._build_dir, f"linux-{version}")
        patches_dir = os.path.join(self._build_dir, "patches")

        # Clean tarball, source dir, and patches when starting fresh
        import shutil
        for path in [tarball, source_dir, patches_dir]:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except Exception:
                pass

        self._report_progress(f"Downloading linux-{version}.{extension}...", 7)

        def wget_callback(line: str) -> None:
            match = re.search(r'(\d+)%', line)
            if match:
                percent = 7 + int(int(match.group(1)) * 0.08)
                self._report_progress(line.strip(), percent)

        exit_code = run_command_with_callback(
            f'wget --progress=dot -O "{tarball}" "{url}" 2>&1',
            cwd=self._build_dir,
            line_callback=wget_callback,
            stop_check=self._is_cancelled
        )

        if self._is_cancelled() or exit_code != 0:
            return False

        self._report_progress("Download complete. Extracting...", 15)

        def tar_callback(line: str) -> None:
            if line.strip():
                self._report_progress(line.strip()[:80], -1)

        exit_code = run_command_with_callback(
            f'tar -xvf "{tarball}"',
            cwd=self._build_dir,
            line_callback=tar_callback,
            stop_check=self._is_cancelled
        )

        if self._is_cancelled() or exit_code != 0:
            return False

        if not os.path.exists(os.path.join(source_dir, "Makefile")):
            self._report_progress("Error: Extraction failed", -1)
            return False

        self._report_progress("Extraction complete.", 25)
        return True

    # ------------------------------------------------------------------
    # Patch download
    # ------------------------------------------------------------------

    def download_patches(self, version: str, patch_ids: List[str],
                         patches_dir: str) -> Dict[str, str]:
        """
        Download requested patches for the given kernel version.
        NTSYNC is skipped here (config-only, handled by installer).

        Returns a dict: {patch_id: [local_paths]} for successfully downloaded patches.
        """
        ensure_directory(patches_dir)
        downloaded: Dict[str, str] = {}

        m = re.match(r'(\d+\.\d+)', version)
        major_minor = m.group(1) if m else version

        for patch_id in patch_ids:
            if self._is_cancelled():
                break

            if patch_id == "ntsync":
                # Config-only, no file to download.
                # Warn if the kernel doesn't support it.
                m_v = re.match(r'(\d+)\.(\d+)', version)
                if m_v and (int(m_v.group(1)), int(m_v.group(2))) < (6, 14):
                    self._report_progress(
                        f"⚠ NTSYNC requires kernel 6.14+ — kernel {version} does not support it. "
                        f"Skipping.", -1
                    )
                continue
            elif patch_id == "rt" and self._rt_is_builtin(version):
                # PREEMPT_RT is mainlined since 6.12 — no patch file needed.
                # On Intel GPU systems, apply the CachyOS rt-i915 fix.
                self._report_progress(
                    f"PREEMPT_RT is built into kernel {version} — no patch needed.", -1
                )
                from .nvidia import has_intel_gpu
                if has_intel_gpu():
                    rt_i915 = self._download_rt_i915_cachy(major_minor, patches_dir)
                    if rt_i915:
                        downloaded["rt"] = rt_i915
                continue
            elif patch_id == "bore":
                paths = self._download_bore(version, major_minor, patches_dir)
            elif patch_id == "rt":
                paths = self._download_rt(version, major_minor, patches_dir)
            elif patch_id == "zen":
                paths = self._download_zen(version, major_minor, patches_dir)
            else:
                print(f"Unknown patch id: {patch_id}", file=sys.stderr)
                continue

            if paths:
                downloaded[patch_id] = paths
                self._report_progress(f"Patch {patch_id} ready.", -1)
            else:
                self._report_progress(
                    f"⚠ Patch '{patch_id}' not available for kernel {version} — compiling without it.",
                    -1
                )
                print(f"Warning: Could not download patch '{patch_id}'", file=sys.stderr)

        return downloaded

    @staticmethod
    def _rt_is_builtin(version: str) -> bool:
        """PREEMPT_RT is mainlined since 6.12."""
        m = re.match(r'(\d+)\.(\d+)', version)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            return (major, minor) >= (6, 12)
        return False

    def _download_file(self, url: str, dest: str) -> bool:
        """Download a single file with wget."""
        exit_code = run_command_with_callback(
            f'wget -q -O "{dest}" "{url}" 2>&1',
            stop_check=self._is_cancelled
        )
        return exit_code == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0

    def _github_api_get(self, url: str) -> Optional[list]:
        """Fetch JSON from GitHub API. Returns parsed JSON or None."""
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'SoplosKernelInstaller/1.0',
                    'Accept': 'application/vnd.github+json',
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            print(f"GitHub API error ({url}): {e}", file=sys.stderr)
            return None

    def _download_bore(self, version: str, major_minor: str,
                       patches_dir: str) -> Optional[List[str]]:
        """
        Download BORE scheduler patches.
        Tries: firelzrd/bore-scheduler (stable → legacy) → CachyOS/kernel-patches fallback.
        """
        self._report_progress(f"Downloading BORE patch for {version}...", -1)

        # --- Source 1: firelzrd/bore-scheduler (stable, then legacy) ---
        for tree in ("stable", "legacy"):
            web_url = BORE_GITHUB_TREE.format(tree=tree, major_minor=major_minor)
            try:
                req = urllib.request.Request(web_url, headers={'User-Agent': 'SoplosInstaller/1.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    html = resp.read().decode('utf-8')
            except Exception:
                continue

            filenames = set(re.findall(r'title="([^"]+\.patch)"', html))
            filenames.update(re.findall(r'href="[^"]+linux-[^"]+-bore/([^"]+\.patch)"', html))

            if not filenames:
                continue

            local_paths = []
            for filename in sorted(filenames):
                raw_url = BORE_RAW_BASE.format(tree=tree, major_minor=major_minor, filename=filename)
                dest = os.path.join(patches_dir, f"bore-{filename}")
                if self._download_file(raw_url, dest):
                    local_paths.append(dest)
                else:
                    self._report_progress(f"Error downloading BORE file: {filename}", -1)
                    return None

            if local_paths:
                return local_paths

        # --- Source 2: CachyOS/kernel-patches fallback ---
        self._report_progress(
            f"BORE not found in firelzrd repo — trying CachyOS fallback for {major_minor}...", -1
        )
        cachy_paths = self._download_bore_cachy(major_minor, patches_dir)
        if cachy_paths:
            return cachy_paths

        print(f"No BORE patch available for {major_minor}", file=sys.stderr)
        return None

    def _download_bore_cachy(self, major_minor: str, patches_dir: str) -> Optional[List[str]]:
        """
        Download BORE patch from CachyOS/kernel-patches.
        Structure: {major_minor}/sched/0001-bore.patch
        """
        filename = "0001-bore.patch"
        raw_url = CACHY_RAW_BASE.format(
            major_minor=major_minor, subdir="sched", filename=filename
        )
        dest = os.path.join(patches_dir, f"bore-cachy-{major_minor}.patch")
        if self._download_file(raw_url, dest):
            self._report_progress(f"CachyOS BORE patch downloaded for {major_minor}.", -1)
            return [dest]

        print(f"CachyOS: no bore patch for {major_minor}", file=sys.stderr)
        return None

    def _download_rt_i915_cachy(self, major_minor: str, patches_dir: str) -> Optional[List[str]]:
        """
        Download the CachyOS rt-i915 fix patch (misc/0001-rt-i915.patch).
        Fixes DRM/i915 compatibility issues with PREEMPT_RT on hybrid Intel+NVIDIA systems.
        """
        filename = "0001-rt-i915.patch"
        raw_url = CACHY_RAW_BASE.format(
            major_minor=major_minor, subdir="misc", filename=filename
        )
        dest = os.path.join(patches_dir, f"rt-i915-cachy-{major_minor}.patch")
        if self._download_file(raw_url, dest):
            self._report_progress(f"CachyOS rt-i915 patch downloaded for {major_minor}.", -1)
            return [dest]

        # Not available for this version — not critical, skip silently
        print(f"CachyOS: no rt-i915 patch for {major_minor}", file=sys.stderr)
        return None

    def _download_rt(self, version: str, major_minor: str,
                     patches_dir: str) -> Optional[List[str]]:
        """
        Download PREEMPT_RT patch from kernel.org/rt.
        Returns list with one local path or None if not available.
        """
        self._report_progress(f"Downloading PREEMPT_RT patch for {version}...", -1)

        rt_index_url = RT_BASE_URL.format(major_minor=major_minor)

        try:
            req = urllib.request.Request(
                rt_index_url,
                headers={'User-Agent': 'SoplosKernelInstaller/1.0'}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                index_html = resp.read().decode('utf-8')
        except Exception as e:
            print(f"RT index fetch error for {major_minor}: {e}", file=sys.stderr)
            return None

        # RT patches use major.minor only (e.g. patch-6.9-rt5, patch-7.0-rc1-rt1)
        pattern = re.compile(
            rf'patch-{re.escape(major_minor)}[^"]*-rt(\d+)\.patch\.xz'
        )
        matches = pattern.findall(index_html)
        if not matches:
            print(f"No RT patch found for {major_minor}", file=sys.stderr)
            return None

        latest_rt = max(matches, key=int)
        # Find the full filename from the index
        full_pattern = re.compile(
            rf'(patch-{re.escape(major_minor)}[^"]*-rt{re.escape(latest_rt)}\.patch\.xz)'
        )
        full_match = full_pattern.search(index_html)
        if not full_match:
            return None
        patch_filename = full_match.group(1)
        xz_dest = os.path.join(patches_dir, patch_filename)
        dest = os.path.join(patches_dir, f"rt-{version}.patch")

        if not self._download_file(rt_index_url + patch_filename, xz_dest):
            return None

        from utils.system import run_command
        result = run_command(f'xz -d "{xz_dest}"')
        uncompressed = xz_dest.replace('.xz', '')
        if result.returncode == 0 and os.path.exists(uncompressed):
            import shutil
            shutil.move(uncompressed, dest)
            return [dest]

        return None

    def _download_zen(self, version: str, major_minor: str,
                      patches_dir: str) -> Optional[List[str]]:
        """
        Download Zen kernel patch via GitHub API with pagination.
        RC kernels are skipped — Zen only patches stable releases.
        """
        if '-rc' in version:
            print(f"Zen: no patch available for RC kernel {version}", file=sys.stderr)
            self._report_progress(
                f"Zen patch not available for RC kernel {version} — skipping.", -1
            )
            return None

        self._report_progress(f"Downloading Zen patch for {version}...", -1)

        target_prefix = f"v{version}-zen"
        asset_url = None
        asset_name = None
        page = 1

        while not asset_url:
            if self._is_cancelled():
                return None
            api_url = (
                f"https://api.github.com/repos/zen-kernel/zen-kernel/releases"
                f"?per_page=100&page={page}"
            )
            releases = self._github_api_get(api_url)
            if not releases:
                self._report_progress(
                    "⚠ Could not reach GitHub API for Zen patch (rate limit or network error).", -1
                )
                break

            for release in releases:
                tag = release.get("tag_name", "")
                if not tag.startswith(target_prefix):
                    continue
                for asset in release.get("assets", []):
                    name = asset.get("name", "")
                    if name.endswith(".patch.zst"):
                        asset_url = asset.get("browser_download_url")
                        asset_name = name
                        break
                if asset_url:
                    break

            if len(releases) < 100:
                # Last page reached without a match
                break
            page += 1

        if not asset_url:
            self._report_progress(
                f"⚠ Zen patch not found for kernel {version} "
                f"(no release matching {target_prefix} in zen-kernel/zen-kernel).", -1
            )
            print(f"No Zen release matching {target_prefix} found", file=sys.stderr)
            return None

        zst_dest = os.path.join(patches_dir, asset_name)
        dest = os.path.join(patches_dir, f"zen-{version}.patch")

        if not self._download_file(asset_url, zst_dest):
            return None

        from utils.system import run_command
        result = run_command(f'zstd -d "{zst_dest}" -o "{dest}"')
        if result.returncode == 0 and os.path.exists(dest):
            return [dest]

        return None
