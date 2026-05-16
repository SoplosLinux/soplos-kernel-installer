"""
Kernel configuration profiles for Soplos Kernel Installer.
"""

import os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List


def _(s):
    return s


class ProfileType(Enum):
    GAMING = auto()
    AUDIO_VIDEO = auto()
    MINIMAL = auto()
    HARDWARE_OPTIMIZED = auto()
    STOCK = auto()
    CUSTOM = auto()


@dataclass
class KernelProfile:
    id: ProfileType
    name: str
    suffix: str
    description: str
    icon: str
    config_options: Dict[str, str] = field(default_factory=dict)
    modules_to_disable: List[str] = field(default_factory=list)

    def get_config_commands(self) -> List[str]:
        """Return scripts/config commands to apply this profile's options.
        Run each command with cwd=source_dir so ./scripts/config is found."""
        cmds = []
        for key, value in self.config_options.items():
            opt = key.removeprefix("CONFIG_")
            if value == 'y':
                cmds.append(f'./scripts/config --enable {opt}')
            elif value == 'n':
                cmds.append(f'./scripts/config --disable {opt}')
            elif value == 'm':
                cmds.append(f'./scripts/config --module {opt}')
            else:
                raw = value.strip('"').strip("'")
                cmds.append(f'./scripts/config --set-val {opt} {raw}')

        for module in self.modules_to_disable:
            cmds.append(f'./scripts/config --disable {module}')

        return cmds

    @staticmethod
    def detect_hardware_optimizations() -> Dict[str, str]:
        options = {
            'CONFIG_HZ_1000': 'y',
            'CONFIG_HZ': '1000',
        }
        try:
            from utils.system import run_command
            lspci_out = run_command("lspci").stdout.lower()

            # Parse line by line — GPU keywords must appear on a display/VGA/3D line
            gpu_keywords = ('vga', 'display', '3d controller', '3d')
            gpu_lines = [l for l in lspci_out.splitlines()
                         if any(k in l for k in gpu_keywords)]
            all_lines = lspci_out.splitlines()

            # GPU detection — only match on GPU lines
            for line in gpu_lines:
                if 'nvidia' in line:
                    options['CONFIG_FB_NVIDIA'] = 'y'
                if 'amd' in line or 'ati' in line:
                    options['CONFIG_DRM_AMDGPU'] = 'y'
                if 'intel' in line:
                    options['CONFIG_DRM_I915'] = 'y'
                # VMs
                if 'vmware' in line or 'vmsvga' in line:
                    options['CONFIG_DRM_VMWGFX'] = 'y'
                if 'virtualbox' in line or 'vbox' in line:
                    options['CONFIG_DRM_VBOXVIDEO'] = 'y'
                if 'qxl' in line:
                    options['CONFIG_DRM_QXL'] = 'y'
                if 'virtio' in line:
                    options['CONFIG_DRM_VIRTIO_GPU'] = 'y'

            # VM paravirtual drivers — check all lines, not just GPU lines
            if any('virtio' in l or 'qemu' in l or 'red hat' in l for l in all_lines):
                options['CONFIG_VIRTIO'] = 'y'
                options['CONFIG_VIRTIO_PCI'] = 'y'
                options['CONFIG_VIRTIO_BLK'] = 'y'
                options['CONFIG_VIRTIO_NET'] = 'y'
            if any('vmware' in l for l in all_lines):
                options['CONFIG_VMXNET3'] = 'y'
                options['CONFIG_VMCI'] = 'y'
            if any('virtualbox' in l or 'vbox' in l for l in all_lines):
                options['CONFIG_VBOXGUEST'] = 'y'

        except Exception:
            pass
        return options


KERNEL_PROFILES = {
    ProfileType.GAMING: KernelProfile(
        id=ProfileType.GAMING,
        name=_("Gaming"),
        suffix="gaming",
        description=_(
            "Optimized for games with low input latency, "
            "high CPU performance and better GPU management."
        ),
        icon="input-gaming",
        config_options={
            'CONFIG_HZ_1000': 'y',
            'CONFIG_HZ_300': 'n',
            'CONFIG_HZ_250': 'n',
            'CONFIG_HZ_100': 'n',
            'CONFIG_HZ': '1000',
            'CONFIG_CPU_FREQ_GOV_PERFORMANCE': 'y',
            'CONFIG_CPU_FREQ_DEFAULT_GOV_PERFORMANCE': 'y',
            'CONFIG_TRANSPARENT_HUGEPAGE': 'y',
            'CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS': 'y',
            'CONFIG_DEBUG_INFO': 'n',
            'CONFIG_DEBUG_KERNEL': 'n',
            'CONFIG_FTRACE': 'n',
            'CONFIG_FUTEX': 'y',
            'CONFIG_FUTEX_PI': 'y',
        }
    ),

    ProfileType.AUDIO_VIDEO: KernelProfile(
        id=ProfileType.AUDIO_VIDEO,
        name=_("Audio / Video"),
        suffix="lowlatency",
        description=_(
            "Low-latency kernel for audio and video production. "
            "Optimized for DAWs, video editing and professional streaming."
        ),
        icon="audio-card",
        config_options={
            'CONFIG_HZ_1000': 'y',
            'CONFIG_HZ_300': 'n',
            'CONFIG_HZ_250': 'n',
            'CONFIG_HZ_100': 'n',
            'CONFIG_HZ': '1000',
            'CONFIG_CPU_FREQ_GOV_PERFORMANCE': 'y',
            'CONFIG_CPU_FREQ_DEFAULT_GOV_PERFORMANCE': 'y',
            'CONFIG_TRANSPARENT_HUGEPAGE': 'y',
            'CONFIG_TRANSPARENT_HUGEPAGE_ALWAYS': 'n',
            'CONFIG_TRANSPARENT_HUGEPAGE_MADVISE': 'y',
            'CONFIG_FUTEX': 'y',
            'CONFIG_FUTEX_PI': 'y',
            'CONFIG_DEBUG_INFO': 'n',
            'CONFIG_DEBUG_KERNEL': 'n',
            'CONFIG_FTRACE': 'n',
        }
    ),

    ProfileType.MINIMAL: KernelProfile(
        id=ProfileType.MINIMAL,
        name=_("Minimal / Office"),
        suffix="minimal",
        description=_(
            "Lightweight kernel for office work and general use. "
            "Low resource consumption, ideal for older hardware."
        ),
        icon="applications-office",
        config_options={
            'CONFIG_HZ_250': 'y',
            'CONFIG_HZ': '250',
            'CONFIG_CPU_FREQ_GOV_POWERSAVE': 'y',
            'CONFIG_CPU_IDLE': 'y',
            'CONFIG_DEBUG_INFO': 'n',
            'CONFIG_DEBUG_KERNEL': 'n',
            'CONFIG_FTRACE': 'n',
            'CONFIG_NVME_CORE': 'y',
            'CONFIG_BLK_DEV_NVME': 'y',
            'CONFIG_SATA_AHCI': 'y',
        },
        modules_to_disable=['JOYSTICK', 'GAMEPORT', 'REISERFS_FS', 'HAMRADIO']
    ),

    ProfileType.HARDWARE_OPTIMIZED: KernelProfile(
        id=ProfileType.HARDWARE_OPTIMIZED,
        name=_("Automatic"),
        suffix="optimized",
        description=_(
            "Auto-detects your hardware to enable specific drivers "
            "and optimizations for maximum performance on your machine."
        ),
        icon="computer",
        config_options={},  # populated at install time via detect_hardware_optimizations()
    ),

    ProfileType.STOCK: KernelProfile(
        id=ProfileType.STOCK,
        name=_("Soplos Stock"),
        suffix="",
        description=_(
            "Generic Soplos kernel. Vanilla config with no profile modifications. "
            "Compatible with all Soplos distributions."
        ),
        icon="system-run",
        config_options={
            'CONFIG_DEBUG_INFO': 'n',
            'CONFIG_DEBUG_KERNEL': 'n',
        },
    ),
}


def get_profile(profile_type: ProfileType) -> KernelProfile:
    return KERNEL_PROFILES.get(profile_type)


def get_all_profiles() -> List[KernelProfile]:
    return list(KERNEL_PROFILES.values())


# Suggested patches per profile (informational only — user chooses)
PROFILE_PATCH_SUGGESTIONS: Dict[ProfileType, List[str]] = {
    ProfileType.GAMING:             ["bore", "ntsync"],
    ProfileType.AUDIO_VIDEO:        ["rt"],
    ProfileType.MINIMAL:            [],
    ProfileType.HARDWARE_OPTIMIZED: ["bore"],
    ProfileType.CUSTOM:             [],
}


def get_patch_suggestions_for_profile(profile: KernelProfile) -> List[str]:
    """Returns suggested patches for the profile. User must confirm selection."""
    return list(PROFILE_PATCH_SUGGESTIONS.get(profile.id, []))
