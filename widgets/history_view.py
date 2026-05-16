"""
History view widget — lists installed kernels.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, Pango

from core.kernel import KernelManager
from core.common_types import InstalledKernel
from core.i18n_manager import _
from typing import List


class HistoryView(Gtk.Box):

    __gsignals__ = {
        'remove-kernel': (GObject.SignalFlags.RUN_FIRST, None, (str,))
    }

    def __init__(self, kernel_manager: KernelManager = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        self._kernel_manager = kernel_manager or KernelManager()

        expander = Gtk.Expander(label=_("Installed kernels"))
        expander.set_expanded(True)

        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.get_style_context().add_class('history-list')

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_propagate_natural_height(True)
        scroll.add(self._list_box)

        expander.add(scroll)
        self.pack_start(expander, True, True, 0)
        self.show_all()

    def refresh(self) -> None:
        for child in self._list_box.get_children():
            self._list_box.remove(child)

        history = self._kernel_manager.get_installation_history()

        if not history:
            empty = Gtk.Label(label=_("No kernels installed yet"))
            empty.get_style_context().add_class('dim-label')
            empty.set_margin_top(8)
            empty.set_margin_bottom(8)
            self._list_box.add(empty)
        else:
            for kernel in history:
                self._list_box.add(self._make_row(kernel))

        self._list_box.show_all()

    def _make_row(self, kernel: InstalledKernel) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(4)
        box.set_margin_bottom(4)
        box.set_margin_start(8)
        box.set_margin_end(8)

        icon = Gtk.Image.new_from_icon_name('object-select-symbolic',
                                             Gtk.IconSize.SMALL_TOOLBAR)
        if kernel.is_current:
            icon.set_tooltip_text(_("Current kernel"))
        else:
            icon.set_opacity(0)
        box.pack_start(icon, False, False, 0)

        version_label = Gtk.Label(label=kernel.version)
        version_label.set_halign(Gtk.Align.START)
        if kernel.is_current:
            version_label.get_style_context().add_class('current-kernel')
        box.pack_start(version_label, True, True, 0)

        # Profile badge — ancho fijo para que todas las filas alineen igual
        profile_label = Gtk.Label(label=kernel.profile)
        profile_label.get_style_context().add_class('profile-badge')
        profile_label.set_width_chars(12)
        profile_label.set_xalign(0.5)
        box.pack_start(profile_label, False, False, 0)

        # Patches — columna siempre presente para mantener alineación
        has_patches = bool(kernel.patches and kernel.patches != "none")
        patches_label = Gtk.Label(label=kernel.patches if has_patches else "")
        patches_label.get_style_context().add_class('dim-label')
        patches_label.set_width_chars(14)
        patches_label.set_xalign(0.0)
        if has_patches:
            patches_label.set_tooltip_text(_("Applied patches: {}").format(kernel.patches))
        box.pack_start(patches_label, False, False, 0)

        # Date — ancho fijo (YYYY-MM-DD siempre 10 chars)
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(kernel.installed_date)
            date_label = Gtk.Label(label=dt.strftime("%Y-%m-%d"))
            date_label.get_style_context().add_class('dim-label')
            date_label.set_width_chars(10)
            date_label.set_xalign(1.0)
            box.pack_start(date_label, False, False, 0)
        except Exception:
            pass

        # Remove icon — placeholder keeps row height/alignment uniform
        trash_icon = Gtk.Image.new_from_icon_name('user-trash-symbolic',
                                                   Gtk.IconSize.MENU)
        ev = Gtk.EventBox()
        ev.add(trash_icon)
        if kernel.is_current:
            ev.set_opacity(0)
        else:
            trash_icon.set_tooltip_text(_("Remove this kernel"))
            ev.connect('button-press-event',
                       lambda _, _e, v=kernel.version: self.emit('remove-kernel', v))
        box.pack_end(ev, False, False, 0)

        row.add(box)
        return row
