"""
Version picker widget — dropdown with version list.
"""

import gi
import re
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, GObject

from core.kernel import KernelManager
from core.common_types import KernelVersion
from core.i18n_manager import _
from typing import List, Optional


def _ver_key(v: KernelVersion):
    m = re.match(r'(\d+)\.(\d+)(?:\.(\d+))?(?:-rc(\d+))?', v.version)
    if m:
        major = int(m.group(1) or 0)
        minor = int(m.group(2) or 0)
        patch = int(m.group(3) or 0)
        rc    = int(m.group(4)) if m.group(4) else 999
        return (-major, -minor, -patch, -rc)
    return (0, 0, 0, 0)


class VersionPicker(Gtk.Box):

    __gsignals__ = {
        'version-changed':   (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        'versions-loaded':   (GObject.SignalFlags.RUN_FIRST, None, ()),
        'loading-started':   (GObject.SignalFlags.RUN_FIRST, None, ()),
        'loading-finished':  (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, kernel_manager: KernelManager = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self._kernel_manager = kernel_manager or KernelManager()
        self._all_versions: List[KernelVersion] = []
        self._selected_version: Optional[str] = None

        # Header
        header = Gtk.Label(label=_("Kernel version"))
        header.get_style_context().add_class('section-header')
        header.set_halign(Gtk.Align.START)
        self.pack_start(header, False, False, 0)

        # Version row
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self._combo = Gtk.ComboBoxText()
        self._combo.set_hexpand(True)
        self._combo.connect('changed', self._on_combo_changed)
        row.pack_start(self._combo, True, True, 0)

        refresh_btn = Gtk.Button()
        refresh_btn.set_image(
            Gtk.Image.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        )
        refresh_btn.set_tooltip_text(_("Refresh versions"))
        refresh_btn.connect('clicked', lambda _: self.refresh_versions())
        row.pack_start(refresh_btn, False, False, 0)
        self.pack_start(row, False, False, 0)

        # Info label
        self._info_label = Gtk.Label()
        self._info_label.get_style_context().add_class('dim-label')
        self._info_label.set_halign(Gtk.Align.START)
        self.pack_start(self._info_label, False, False, 0)

        self.show_all()

    def _on_combo_changed(self, combo: Gtk.ComboBoxText) -> None:
        active_text = combo.get_active_text()
        if active_text:
            self._selected_version = active_text.split()[0]
            self.emit('version-changed', self._selected_version)
            self._update_info()

    def _update_info(self) -> None:
        if not self._selected_version:
            self._info_label.set_text("")
            return
        for v in self._all_versions:
            if v.version == self._selected_version:
                if v.is_rc:
                    self._info_label.set_markup(
                        _("<span foreground='orange'>⚠ Experimental RC version</span>")
                    )
                elif v.is_latest:
                    self._info_label.set_markup(_("<b>✓ Latest stable version</b>"))
                elif v.is_mainline:
                    self._info_label.set_text(_("Mainline kernel (not yet stable)"))
                elif v.is_longterm:
                    self._info_label.set_text(_("Long-term support (LTS)"))
                elif v.is_eol:
                    self._info_label.set_markup(
                        _("<span foreground='red'>✗ End-of-Life — no longer receives security updates</span>")
                    )
                else:
                    self._info_label.set_text(_("Stable version"))
                return

    def _populate_combo(self) -> None:
        self._combo.remove_all()
        sorted_versions = sorted(self._all_versions, key=_ver_key)
        for v in sorted_versions:
            suffix = ""
            if v.is_latest:
                suffix = f" ({_('latest')})"
            elif v.is_mainline:
                suffix = f" ({_('mainline')})"
            elif v.is_longterm:
                suffix = " (LTS)"
            elif v.is_rc:
                suffix = " (RC)"
            elif v.is_eol:
                suffix = " (EOL)"
            self._combo.append_text(f"{v.version}{suffix}")

        if self._combo.get_model() and len(self._combo.get_model()) > 0:
            self._combo.set_active(0)

    def refresh_versions(self) -> None:
        self.emit('loading-started')
        self._info_label.set_text(_("Loading..."))
        self._combo.remove_all()

        import threading

        def fetch():
            try:
                versions = self._kernel_manager.get_all_versions()
            except Exception:
                versions = []
            GLib.idle_add(self._on_versions_loaded, versions)

        threading.Thread(target=fetch, daemon=True).start()

    def _on_versions_loaded(self, versions: List[KernelVersion]) -> bool:
        self._all_versions = versions
        self._populate_combo()
        self._info_label.set_text("")
        self.emit('versions-loaded')
        self.emit('loading-finished')
        return False

    def get_selected_version(self) -> Optional[str]:
        return self._selected_version

    def get_selected_version_info(self) -> Optional[KernelVersion]:
        for v in self._all_versions:
            if v.version == self._selected_version:
                return v
        return None
