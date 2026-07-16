"""
Common data types for Soplos Kernel Installer.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class KernelVersion:
    """Represents a kernel version available for installation."""
    version: str
    url: str
    channel: str = "stable"        # stable | mainline | lts | rc
    is_latest: bool = False
    is_longterm: bool = False
    is_rc: bool = False
    is_mainline: bool = False
    is_eol: bool = False
    description: str = ""


@dataclass
class InstalledKernel:
    """Represents a kernel installed on the local system."""
    version: str
    profile: str
    patches: str
    installed_date: str
    is_current: bool = False
    secure_boot: bool = False


class MarchLevel:
    """x86-64 microarchitecture levels for kernel compilation."""
    V1 = "v1"   # Baseline x86-64 — all 64-bit CPUs (LATAM compatibility)
    V2 = "v2"   # SSE4.2+ — most CPUs since ~2009
    V3 = "v3"   # AVX2+ — modern CPUs since ~2013 (Haswell / Zen+)
    V4 = "v4"   # AVX-512 — latest generation CPUs
    ALL = [V1, V2, V3, V4]


@dataclass
class PatchInfo:
    """Describes a kernel patch."""
    id: str
    name: str
    description: str
    source_url: str
    is_config_only: bool = False   # True = only a config option, no patch file (e.g. NTSYNC on 6.14+)
    stock_only: bool = False        # True = only shown in Stock/developer mode (Ctrl+Shift+D)
    enabled: bool = False
