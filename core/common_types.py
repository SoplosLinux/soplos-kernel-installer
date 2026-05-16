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


@dataclass
class PatchInfo:
    """Describes a kernel patch."""
    id: str
    name: str
    description: str
    source_url: str
    is_config_only: bool = False   # True = only a config option, no patch file (e.g. NTSYNC on 6.14+)
    enabled: bool = False
