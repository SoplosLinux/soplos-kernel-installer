"""
Patch selector widget — checkboxes for available kernel patches.

Rules:
  - BORE and Zen are mutually exclusive (both modify the scheduler)
  - RT and Zen are mutually exclusive (Zen replaces CFS with BMQ; RT patches CFS)
  - RT and NTSYNC are independent
  - BORE and RT are compatible
  - NTSYNC is only shown/enabled for kernel >= 6.14 (mainlined)
"""

import re
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from core.kernel import AVAILABLE_PATCHES
from core.profiles import KernelProfile, get_patch_suggestions_for_profile
from core.i18n_manager import _
from typing import List, Optional

# Pairs of mutually incompatible patches
_INCOMPATIBLE_PAIRS = [
    {"bore", "zen"},   # Both replace the scheduler
    {"rt", "zen"},     # RT patches CFS; Zen replaces it entirely with BMQ
]


def _get_incompatible_with(patch_id: str) -> set:
    """Return all patch ids incompatible with the given one."""
    result = set()
    for pair in _INCOMPATIBLE_PAIRS:
        if patch_id in pair:
            result.update(pair - {patch_id})
    return result


def _kernel_ge_614(version: str) -> bool:
    m = re.match(r'(\d+)\.(\d+)', version)
    if m:
        return (int(m.group(1)), int(m.group(2))) >= (6, 14)
    return False


class PatchSelector(Gtk.Box):

    __gsignals__ = {
        'patches-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self._current_version: Optional[str] = None
        self._blocking_signal = False

        header = Gtk.Label(label=_("Patches"))
        header.get_style_context().add_class('section-header')
        header.set_halign(Gtk.Align.START)
        self.pack_start(header, False, False, 0)

        # {patch_id: (checkbutton, row_box)}
        self._checks: dict = {}

        checks_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        for patch in AVAILABLE_PATCHES:
            check = Gtk.CheckButton(label=patch.name)
            check.set_active(False)
            check.set_tooltip_text(patch.description)
            check.connect('toggled', self._on_toggled, patch.id)
            checks_row.pack_start(check, False, False, 0)
            self._checks[patch.id] = (check, checks_row)

        self.pack_start(checks_row, False, False, 0)

        self.show_all()

    def _on_toggled(self, check: Gtk.CheckButton, patch_id: str) -> None:
        if self._blocking_signal:
            return

        if check.get_active():
            incompatible = _get_incompatible_with(patch_id)
            if incompatible:
                self._blocking_signal = True
                for other_id in incompatible:
                    if other_id in self._checks:
                        self._checks[other_id][0].set_active(False)
                self._blocking_signal = False

        self.emit('patches-changed')

    def update_for_version(self, version: str) -> None:
        """Show/enable NTSYNC only for kernel >= 6.14."""
        self._current_version = version
        if "ntsync" not in self._checks:
            return

        check, row = self._checks["ntsync"]
        supported = _kernel_ge_614(version)
        check.set_sensitive(supported)
        if not supported:
            self._blocking_signal = True
            check.set_active(False)
            self._blocking_signal = False

        # Update tooltip
        ntsync_patch = next((p for p in AVAILABLE_PATCHES if p.id == "ntsync"), None)
        base_desc = ntsync_patch.description if ntsync_patch else ""
        if not supported:
            check.set_tooltip_text(
                _("NTSYNC requires kernel 6.14 or newer")
            )
        else:
            check.set_tooltip_text(base_desc)

    def clear_all(self) -> None:
        """Deselect all patches."""
        self._blocking_signal = True
        for check, _row in self._checks.values():
            check.set_active(False)
        self._blocking_signal = False
        self.emit('patches-changed')

    def apply_profile_suggestions(self, profile: KernelProfile) -> None:
        """Pre-select patches suggested for this profile."""
        suggested = get_patch_suggestions_for_profile(profile)

        self._blocking_signal = True
        for patch_id, (check, _row) in self._checks.items():
            if not check.get_sensitive():
                continue
            check.set_active(patch_id in suggested)
        self._blocking_signal = False

        # Re-apply mutual exclusion: resolve any incompatible pairs left active
        for pair in _INCOMPATIBLE_PAIRS:
            active_in_pair = [
                pid for pid in pair
                if pid in self._checks and self._checks[pid][0].get_active()
            ]
            if len(active_in_pair) > 1:
                for pid in active_in_pair[1:]:
                    self._checks[pid][0].set_active(False)

        self.emit('patches-changed')

    def get_selected_patch_ids(self) -> List[str]:
        return [
            pid for pid, (check, _row) in self._checks.items()
            if check.get_active()
        ]
