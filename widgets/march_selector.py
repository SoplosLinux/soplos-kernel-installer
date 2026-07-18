"""
March level selector widget — shown only in Stock (developer) mode.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from core.i18n_manager import _
from core.common_types import MarchLevel


class MarchSelector(Gtk.Box):

    __gsignals__ = {
        'march-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        header = Gtk.Label(label=_("CPU architecture level"))
        header.get_style_context().add_class('section-header')
        header.set_halign(Gtk.Align.START)
        self.pack_start(header, False, False, 0)

        desc = Gtk.Label(label=_("Optimizes the compiled kernel for the target CPU generation."))
        desc.get_style_context().add_class('dim-label')
        desc.set_halign(Gtk.Align.START)
        desc.set_line_wrap(True)
        self.pack_start(desc, False, False, 0)

        radios_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)

        _LEVELS = [
            (MarchLevel.V1, _("Generic (v1)"), _("All x86-64 CPUs — maximum compatibility (LATAM)")),
            (MarchLevel.V2, _("x86-64-v2"),   _("SSE4.2+ — most CPUs since ~2009")),
            (MarchLevel.V3, _("x86-64-v3"),   _("AVX2+ — modern hardware since ~2013 (Haswell / Zen+)")),
            (MarchLevel.V4, _("x86-64-v4"),   _("AVX-512 — latest generation CPUs")),
        ]

        self._radios: dict = {}
        first = None
        for level, label, tooltip in _LEVELS:
            radio = Gtk.RadioButton.new_with_label_from_widget(first, label)
            radio.set_tooltip_text(tooltip)
            radio.connect('toggled', self._on_toggled)
            if first is None:
                first = radio
            radios_box.pack_start(radio, False, False, 0)
            self._radios[level] = radio

        self.pack_start(radios_box, False, False, 0)
        self.show_all()

    def _on_toggled(self, radio: Gtk.RadioButton) -> None:
        if radio.get_active():
            self.emit('march-changed')

    def get_march_level(self) -> str:
        for level, radio in self._radios.items():
            if radio.get_active():
                return level
        return MarchLevel.V1

    def set_march_level(self, level: str) -> None:
        if level in self._radios:
            self._radios[level].set_active(True)

    def set_minimum_level(self, level: str) -> None:
        """Disable levels below `level` — e.g. X3D VCache CPUs are all
        Zen 3+ (x86-64-v3 or higher), so v1/v2 make no sense with it."""
        min_index = MarchLevel.ALL.index(level) if level in MarchLevel.ALL else 0
        for i, lvl in enumerate(MarchLevel.ALL):
            radio = self._radios.get(lvl)
            if radio:
                radio.set_sensitive(i >= min_index)
        current = self.get_march_level()
        if MarchLevel.ALL.index(current) < min_index:
            self.set_march_level(level)
