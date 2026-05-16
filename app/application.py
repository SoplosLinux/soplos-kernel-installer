"""
GTK Application class for Soplos Kernel Installer.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib

from pathlib import Path

from .main_window import SoplosKernelInstallerWindow
from core.kernel import KernelManager
from core.i18n_manager import _

from config.constants import APP_VERSION as VERSION


class SoplosKernelInstallerApp(Gtk.Application):

    APP_ID = "org.soplos.kernel-installer"

    def __init__(self, force_new: bool = False):
        flags = Gio.ApplicationFlags.FLAGS_NONE
        if force_new:
            flags |= Gio.ApplicationFlags.NON_UNIQUE
        super().__init__(application_id=self.APP_ID, flags=flags)

        self._window = None
        self._kernel_manager = KernelManager()

    def do_activate(self) -> None:
        if not self._window:
            self._window = SoplosKernelInstallerWindow(self)
            self._window.connect('key-press-event', self._on_key_press)
            GLib.idle_add(self._check_headers_threaded)
        self._window.present()

    def _check_headers_threaded(self) -> bool:
        import threading
        def run_check():
            self._kernel_manager.check_and_install_dependencies()
        threading.Thread(target=run_check, daemon=True).start()
        return False

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self._load_css()
        self._setup_actions()
        self._setup_accelerators()

    def _on_key_press(self, widget, event) -> bool:
        keyval = event.keyval
        state = event.state & Gtk.accelerator_get_default_mod_mask()

        if state == Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_q, Gdk.KEY_Q, Gdk.KEY_w, Gdk.KEY_W):
                self.quit()
                return True

        if keyval == Gdk.KEY_F5:
            if self._window:
                self._window.refresh_versions()
            return True

        return False

    def _setup_accelerators(self) -> None:
        self.set_accels_for_action("app.quit", ["<Control>q", "<Control>w"])
        self.set_accels_for_action("app.refresh", ["F5"])

    def _load_css(self) -> None:
        css_provider = Gtk.CssProvider()
        base_dir = Path(__file__).parent.parent / "assets" / "themes"
        system_dir = Path("/usr/share/soplos-kernel-installer/themes")

        # Detect dark/light preference
        prefer_dark = False
        settings = Gtk.Settings.get_default()
        if settings:
            try:
                prefer_dark = settings.get_property('gtk-application-prefer-dark-theme')
            except Exception:
                pass
            if not prefer_dark:
                try:
                    theme_name = settings.get_property('gtk-theme-name') or ''
                    prefer_dark = 'dark' in theme_name.lower()
                except Exception:
                    pass
        if not prefer_dark:
            import subprocess
            try:
                result = subprocess.run(
                    ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
                    capture_output=True, text=True, timeout=2
                )
                prefer_dark = 'dark' in result.stdout.lower()
            except Exception:
                pass

        theme_file = "dark.css" if prefer_dark else "light.css"

        loaded = False
        for data_dir in (base_dir, system_dir):
            theme_path = data_dir / theme_file
            base_path = data_dir / "base.css"
            if theme_path.exists() and base_path.exists():
                try:
                    combined = (theme_path.read_text(encoding='utf-8') + '\n' +
                                base_path.read_text(encoding='utf-8'))
                    css_provider.load_from_data(combined.encode('utf-8'))
                    loaded = True
                    break
                except Exception:
                    continue

        if not loaded:
            css_provider.load_from_data(self._get_default_css().encode())

        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(
            screen, css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _get_default_css(self) -> str:
        return '''
.profile-card {
    padding: 12px;
    border-radius: 10px;
    border: 2px solid alpha(@theme_fg_color, 0.1);
    background: alpha(@theme_bg_color, 0.5);
    transition: all 200ms ease;
    min-width: 130px;
}
.profile-card:hover {
    border-color: alpha(@theme_selected_bg_color, 0.5);
    background: alpha(@theme_selected_bg_color, 0.1);
}
.profile-card:checked {
    border-color: @theme_selected_bg_color;
    background: alpha(@theme_selected_bg_color, 0.15);
    box-shadow: 0 0 0 3px alpha(@theme_selected_bg_color, 0.2);
}
.profile-name { font-weight: bold; font-size: 1.0em; }
.profile-badge {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.85em;
    background: alpha(@theme_selected_bg_color, 0.2);
}
.section-header { font-weight: bold; font-size: 1.0em; opacity: 0.9; }
.history-list row { border-radius: 6px; margin: 2px 0; }
.current-kernel { font-weight: bold; }
.dim-label { opacity: 0.7; font-size: 0.9em; }
.soplos-footer { border-top: 1px solid alpha(@theme_fg_color, 0.1); }
progressbar progress { border-radius: 4px; }
progressbar trough { border-radius: 4px; }
'''

    def _setup_actions(self) -> None:
        for name, handler in [
            ("quit", self._on_quit),
            ("refresh", self._on_refresh),
            ("about", self._on_about),
            ("cleanup", self._on_cleanup),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def _on_quit(self, action, param) -> None:
        self.quit()

    def _on_refresh(self, action, param) -> None:
        if self._window:
            self._window.refresh_versions()

    def _on_about(self, action, param) -> None:
        about = Gtk.AboutDialog(transient_for=self._window, modal=True)
        about.set_program_name(_("Soplos Kernel Installer"))
        about.set_version(VERSION)
        about.set_comments(
            _("Graphical interface for downloading, compiling and installing "
              "the Linux kernel with patches and optimized profiles on Soplos Linux.")
        )
        about.set_authors(["Sergi Perich <info@soploslinux.com>"])
        about.set_copyright("© 2026 Sergi Perich")
        about.set_license_type(Gtk.License.GPL_3_0)
        about.set_website("https://github.com/SoplosLinux/soplos-kernel-installer")
        about.set_website_label("GitHub")
        about.set_logo_icon_name("org.soplos.kernel-installer")
        about.run()
        about.destroy()

    def _on_cleanup(self, action, param) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self._window, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Clean build files?")
        )
        dialog.format_secondary_text(
            _("All temporary files in ~/kernel_build will be deleted.\n"
              "This will free up disk space.")
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            if self._kernel_manager.cleanup_build_files():
                self._show_info(_("Build files deleted."))
            else:
                self._show_error(_("Error cleaning files."))

    def _show_info(self, message: str) -> None:
        d = Gtk.MessageDialog(transient_for=self._window, modal=True,
                              message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK, text=message)
        d.run()
        d.destroy()

    def _show_error(self, message: str) -> None:
        d = Gtk.MessageDialog(transient_for=self._window, modal=True,
                              message_type=Gtk.MessageType.ERROR,
                              buttons=Gtk.ButtonsType.OK, text=message)
        d.run()
        d.destroy()
