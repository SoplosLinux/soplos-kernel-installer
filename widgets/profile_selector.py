"""
Profile selector widget.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from core.profiles import KernelProfile, ProfileType, get_all_profiles, get_profile
from core.i18n_manager import _


class ProfileCard(Gtk.RadioButton):

    def __init__(self, profile: KernelProfile, group=None):
        super().__init__(group=group)
        self.profile = profile
        self.set_mode(False)
        self.get_style_context().add_class('profile-card')

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        icon = Gtk.Image.new_from_icon_name(profile.icon, Gtk.IconSize.DIALOG)
        icon.set_pixel_size(48)
        box.pack_start(icon, False, False, 0)

        name_label = Gtk.Label(label=_(profile.name))
        name_label.get_style_context().add_class('profile-name')
        name_label.set_halign(Gtk.Align.CENTER)
        box.pack_start(name_label, False, False, 0)

        self.set_tooltip_text(_(profile.description))
        self.add(box)
        self.show_all()


class ProfileSelector(Gtk.Box):

    __gsignals__ = {
        'profile-changed': (GObject.SignalFlags.RUN_FIRST, None, (object,))
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        self._selected_profile: KernelProfile = None
        self._cards = {}

        header = Gtk.Label(label=_("Select kernel profile"))
        header.get_style_context().add_class('section-header')
        header.set_halign(Gtk.Align.START)
        self.pack_start(header, False, False, 0)

        cards_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cards_box.set_halign(Gtk.Align.FILL)
        cards_box.set_homogeneous(True)

        first_card = None
        public_profiles = [p for p in get_all_profiles() if p.id != ProfileType.STOCK]
        for profile in public_profiles:
            card = ProfileCard(profile, group=first_card)
            if first_card is None:
                first_card = card
                card.set_active(True)
                self._selected_profile = profile
            card.connect('toggled', self._on_card_toggled)
            self._cards[profile.id] = card
            cards_box.pack_start(card, True, True, 0)

        # Stock profile — hidden by default, revealed with Ctrl+Shift+D
        stock_profile = get_profile(ProfileType.STOCK)
        stock_card = ProfileCard(stock_profile, group=first_card)
        stock_card.connect('toggled', self._on_card_toggled)
        stock_card.set_no_show_all(True)
        stock_card.hide()
        self._cards[ProfileType.STOCK] = stock_card
        cards_box.pack_start(stock_card, True, True, 0)

        self.pack_start(cards_box, False, False, 0)
        self.show_all()

    def _on_card_toggled(self, card: ProfileCard) -> None:
        if card.get_active():
            self._selected_profile = card.profile
            self.emit('profile-changed', card.profile)

    def get_selected_profile(self) -> KernelProfile:
        return self._selected_profile

    def toggle_stock_profile(self) -> None:
        card = self._cards.get(ProfileType.STOCK)
        if not card:
            return
        if card.get_visible():
            # Hide and revert to first public profile
            card.hide()
            first = next(
                (c for pid, c in self._cards.items() if pid != ProfileType.STOCK),
                None
            )
            if first:
                first.set_active(True)
        else:
            card.show()
            card.set_active(True)
