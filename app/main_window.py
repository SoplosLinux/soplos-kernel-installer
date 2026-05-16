"""
Main window for Soplos Kernel Installer.
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf

import threading
import os
import re
import shlex
import glob
import shutil
import subprocess
import tempfile

from widgets.profile_selector import ProfileSelector
from widgets.version_picker import VersionPicker
from widgets.patch_selector import PatchSelector
from widgets.build_progress import BuildProgress
from widgets.history_view import HistoryView
from core.nvidia import has_nvidia_gpu
from core.i18n_manager import _
from core.profiles import ProfileType
from config.constants import APP_VERSION as VERSION
from utils.system import reboot_system, get_build_directory


class SoplosKernelInstallerWindow(Gtk.ApplicationWindow):

    def __init__(self, application: Gtk.Application):
        super().__init__(application=application)

        self.set_title(_("Soplos Kernel Installer"))
        self.set_default_size(760, 740)
        self.set_size_request(760, -1)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("org.soplos.kernel-installer")

        self._kernel_manager = application._kernel_manager
        self._building = False
        self._pulse_timer_id = None
        self._progress_indeterminate = False
        self._inhibit_cookie = 0
        self._last_secure_boot = False
        self._current_build_profile = None
        self._current_build_version = ""
        self._current_build_custom_name = ""

        self.get_style_context().add_class('soplos-window')

        self._create_header_bar()
        self._create_content()
        self._setup_shortcuts()
        GLib.idle_add(self._load_initial_data)

    # ------------------------------------------------------------------
    # Header bar
    # ------------------------------------------------------------------

    def _detect_desktop(self) -> str:
        for var in ('XDG_CURRENT_DESKTOP', 'DESKTOP_SESSION', 'XDG_SESSION_DESKTOP'):
            value = os.environ.get(var, '').lower()
            if 'xfce' in value:
                return 'xfce'
            if 'kde' in value or 'plasma' in value:
                return 'kde'
            if 'gnome' in value:
                return 'gnome'
        return 'unknown'

    def _create_header_bar(self) -> None:
        desktop = self._detect_desktop()

        if desktop in ('xfce', 'kde'):
            self._use_csd = False
            return

        self._use_csd = True
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title(_("Soplos Kernel Installer"))
        header.set_decoration_layout("menu:minimize,maximize,close")
        header.get_style_context().add_class('titlebar')
        self.set_titlebar(header)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def _create_content(self) -> None:
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self._stack.set_vhomogeneous(True)

        # ── Config page ───────────────────────────────────────────────
        config_scroll = Gtk.ScrolledWindow()
        config_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        config_box.set_margin_start(12)
        config_box.set_margin_end(12)
        config_box.set_margin_top(8)
        config_box.set_margin_bottom(8)

        # Profile selector — soplos-card
        profile_frame = Gtk.Frame()
        profile_frame.get_style_context().add_class('soplos-card')
        self._profile_selector = ProfileSelector()
        self._profile_selector.connect('profile-changed', self._on_profile_changed)
        profile_frame.add(self._profile_selector)
        config_box.pack_start(profile_frame, False, False, 0)

        # ── Fila 2: Version picker (izq) + Nombre de kernel (der) ────
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        version_frame = Gtk.Frame()
        version_frame.get_style_context().add_class('soplos-card')
        self._version_picker = VersionPicker(self._kernel_manager)
        self._version_picker.connect('loading-started', self._on_version_loading_started)
        self._version_picker.connect('loading-finished', self._on_version_loading_finished)
        self._version_picker.connect('version-changed', self._on_version_changed)
        version_frame.add(self._version_picker)
        row2.pack_start(version_frame, True, True, 0)

        name_frame = Gtk.Frame()
        name_frame.get_style_context().add_class('soplos-card')
        name_frame.set_size_request(200, -1)
        name_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        name_label = Gtk.Label(label=_("Kernel name (suffix)"))
        name_label.set_halign(Gtk.Align.START)
        name_inner.pack_start(name_label, False, False, 0)

        self._kernel_name_entry = Gtk.Entry()
        self._kernel_name_entry.set_text("soplos")
        self._kernel_name_entry.set_placeholder_text(_("e.g.: soplos"))
        self._kernel_name_entry.set_tooltip_text(
            _("Combined with profile: 6.x.x-soplos-gaming")
        )
        self._kernel_name_entry.connect('changed', self._on_kernel_name_changed)
        name_inner.pack_start(self._kernel_name_entry, False, False, 0)

        self._name_hint_label = Gtk.Label()
        self._name_hint_label.get_style_context().add_class('dim-label')
        self._name_hint_label.set_halign(Gtk.Align.START)
        name_inner.pack_start(self._name_hint_label, False, False, 0)

        name_frame.add(name_inner)
        row2.pack_start(name_frame, False, False, 0)

        config_box.pack_start(row2, False, False, 0)

        # ── Fila 2b: Patch selector ───────────────────────────────────
        patch_frame = Gtk.Frame()
        patch_frame.get_style_context().add_class('soplos-card')
        self._patch_selector = PatchSelector()
        patch_frame.add(self._patch_selector)
        config_box.pack_start(patch_frame, False, False, 0)

        # ── Fila 3: Opciones (izq) + Info sistema + Secure Boot (der) ─
        row3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        # Opciones izquierda
        options_frame = Gtk.Frame()
        options_frame.get_style_context().add_class('soplos-card')
        options_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self._cleanup_check = Gtk.CheckButton(
            label=_("Clean build directory after installation")
        )
        self._cleanup_check.set_active(True)
        options_inner.pack_start(self._cleanup_check, False, False, 0)

        options_frame.add(options_inner)
        row3.pack_start(options_frame, True, True, 0)

        # Info sistema + Secure Boot derecha
        right_frame = Gtk.Frame()
        right_frame.get_style_context().add_class('soplos-card')
        right_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Sistema info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for attr, label_text in [
            ('_distro_value', _("Distribution:")),
            ('_kernel_value', _("Current kernel:")),
            ('_initramfs_value', _("Initramfs:")),
        ]:
            row_info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            lbl = Gtk.Label(label=label_text)
            lbl.get_style_context().add_class('dim-label')
            lbl.set_halign(Gtk.Align.START)
            row_info.pack_start(lbl, False, False, 0)
            val = Gtk.Label(label="...")
            val.set_halign(Gtk.Align.START)
            val.set_ellipsize(3)  # PANGO_ELLIPSIZE_END
            setattr(self, attr, val)
            row_info.pack_start(val, True, True, 0)
            info_box.pack_start(row_info, False, False, 0)
        right_inner.pack_start(info_box, False, False, 0)

        right_inner.pack_start(Gtk.Separator(), False, False, 2)

        # Secure Boot
        sb_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._secure_boot_check = Gtk.CheckButton(
            label=_("Secure Boot (MOK)")
        )
        if self._kernel_manager.is_secure_boot_active():
            self._secure_boot_check.set_active(True)
        sb_box.pack_start(self._secure_boot_check, True, True, 0)

        self._manage_keys_btn = Gtk.Button(label=_("⚙ MOK Keys"))
        self._manage_keys_btn.set_tooltip_text(_("Manage Machine Owner Keys"))
        self._manage_keys_btn.connect('clicked', self._on_manage_keys_clicked)
        sb_box.pack_start(self._manage_keys_btn, False, False, 0)
        right_inner.pack_start(sb_box, False, False, 0)

        right_frame.add(right_inner)
        row3.pack_start(right_frame, True, True, 0)

        config_box.pack_start(row3, False, False, 0)

        # Build control buttons (shown only while building)
        self._build_ctrl_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._build_ctrl_box.set_homogeneous(True)

        self._details_btn = Gtk.Button(label=_("Details"))
        self._details_btn.connect('clicked', self._on_details_clicked)
        self._build_ctrl_box.pack_start(self._details_btn, True, True, 0)

        self._main_cancel_btn = Gtk.Button(label=_("Cancel"))
        self._main_cancel_btn.get_style_context().add_class('destructive-action')
        self._main_cancel_btn.connect('clicked', self._on_cancel_clicked)
        self._build_ctrl_box.pack_start(self._main_cancel_btn, True, True, 0)

        config_box.pack_start(self._build_ctrl_box, False, False, 0)
        self._build_ctrl_box.hide()

        # Install button
        self._install_btn = Gtk.Button(label=_("Download and install kernel"))
        self._install_btn.get_style_context().add_class('suggested-action')
        self._install_btn.connect('clicked', self._on_install_clicked)
        config_box.pack_start(self._install_btn, False, False, 2)

        # Installed kernels history — soplos-card
        history_frame = Gtk.Frame()
        history_frame.get_style_context().add_class('soplos-card')
        self._history_view = HistoryView(self._kernel_manager)
        self._history_view.connect('remove-kernel', self._on_remove_kernel)
        history_frame.add(self._history_view)
        config_box.pack_start(history_frame, True, True, 0)

        config_scroll.add(config_box)
        self._stack.add_named(config_scroll, "config")

        # ── Build page ────────────────────────────────────────────────
        build_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        build_box.set_margin_start(15)
        build_box.set_margin_end(15)
        build_box.set_margin_top(12)
        build_box.set_margin_bottom(12)

        self._build_progress = BuildProgress()
        build_box.pack_start(self._build_progress, True, True, 0)

        build_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        build_btn_box.set_homogeneous(True)

        self._back_btn = Gtk.Button(label=_("← Back"))
        self._back_btn.connect('clicked', self._on_back_clicked)
        self._back_btn.set_sensitive(False)
        build_btn_box.pack_start(self._back_btn, True, True, 0)

        self._cancel_btn = Gtk.Button(label=_("Cancel"))
        self._cancel_btn.get_style_context().add_class('destructive-action')
        self._cancel_btn.connect('clicked', self._on_cancel_clicked)
        self._cancel_btn.set_sensitive(False)
        build_btn_box.pack_start(self._cancel_btn, True, True, 0)

        self._done_btn = Gtk.Button(label=_("Done"))
        self._done_btn.get_style_context().add_class('suggested-action')
        self._done_btn.connect('clicked', self._on_done_clicked)
        self._done_btn.set_no_show_all(True)
        build_btn_box.pack_start(self._done_btn, True, True, 0)

        build_box.pack_start(build_btn_box, False, False, 0)
        self._stack.add_named(build_box, "build")

        # ── Notebook (tabs) ───────────────────────────────────────────
        self._notebook = Gtk.Notebook()
        self._notebook.append_page(self._stack, Gtk.Label(label=_("Build Kernel")))
        self._notebook.append_page(self._create_soplos_kernels_page(), Gtk.Label(label=_("Soplos Kernels")))

        main_box.pack_start(self._notebook, True, True, 0)

        # Progress revealer (encima del footer)
        self._progress_revealer = Gtk.Revealer()
        self._progress_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)

        rev_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        rev_box.set_margin_start(15)
        rev_box.set_margin_end(15)
        rev_box.set_margin_bottom(10)

        self._dep_progress = Gtk.ProgressBar()
        self._dep_progress.get_style_context().add_class('soplos-progress-bar')
        self._dep_progress.set_show_text(True)
        rev_box.pack_start(self._dep_progress, False, False, 0)

        self._dep_label = Gtk.Label()
        self._dep_label.get_style_context().add_class('soplos-status-label')
        rev_box.pack_start(self._dep_label, False, False, 0)

        self._progress_revealer.add(rev_box)
        self._progress_revealer.set_reveal_child(False)

        # Footer
        footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        footer_box.get_style_context().add_class('soplos-footer')
        footer_box.set_margin_start(15)
        footer_box.set_margin_end(15)
        footer_box.set_margin_top(5)
        footer_box.set_margin_bottom(5)

        desktop = self._detect_desktop().upper()
        xdg_type = os.environ.get('XDG_SESSION_TYPE', '').upper()
        footer_text = f"{desktop} · {xdg_type}" if xdg_type else desktop
        self._footer_left = Gtk.Label(label=footer_text)
        self._footer_left.get_style_context().add_class('dim-label')
        self._footer_left.set_halign(Gtk.Align.START)
        footer_box.pack_start(self._footer_left, False, False, 0)

        footer_right = Gtk.Label(label=f"v{VERSION}")
        footer_right.get_style_context().add_class('dim-label')
        footer_right.set_halign(Gtk.Align.END)
        footer_box.pack_end(footer_right, False, False, 0)

        main_box.pack_end(footer_box, False, False, 0)
        main_box.pack_end(self._progress_revealer, False, False, 0)

        self.add(main_box)
        self.show_all()

        self._build_ctrl_box.hide()
        self._progress_revealer.set_reveal_child(False)

    # ------------------------------------------------------------------
    # Soplos Kernels tab
    # ------------------------------------------------------------------

    _SOPLOS_KERNELS_REPO_FILE = "/etc/apt/sources.list.d/soplos-kernels.sources"
    _SOPLOS_KERNELS_REPO_URL  = "https://raw.githubusercontent.com/SoplosLinux/soplos-kernels/main/"
    _SOPLOS_KERNELS_GPG_URL   = "https://raw.githubusercontent.com/SoplosLinux/soplos-kernels/main/public.key"
    _SOPLOS_KERNELS_GPG_FILE  = "/usr/share/keyrings/soplos-kernels.gpg"


    def _create_soplos_kernels_page(self) -> Gtk.Widget:
        self._soplos_packages = []
        self._kernel_action_btns = {}
        self._kernel_update_btns = {}
        self._soplos_updates = {}
        self._soplos_versions = {}

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)

        # Repo status card
        repo_frame = Gtk.Frame()
        repo_frame.get_style_context().add_class('soplos-card')
        repo_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        repo_header = Gtk.Label(label=_("Soplos Kernels Repository"))
        repo_header.get_style_context().add_class('section-header')
        repo_header.set_halign(Gtk.Align.START)
        repo_inner.pack_start(repo_header, False, False, 0)

        repo_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._repo_status_label = Gtk.Label()
        self._repo_status_label.set_halign(Gtk.Align.START)
        repo_row.pack_start(self._repo_status_label, True, True, 0)

        self._refresh_repo_btn = Gtk.Button(label=_("Refresh"))
        self._refresh_repo_btn.connect('clicked', self._on_refresh_soplos_repo_clicked)
        repo_row.pack_start(self._refresh_repo_btn, False, False, 0)

        self._add_repo_btn = Gtk.Button(label=_("Add repository"))
        self._add_repo_btn.get_style_context().add_class('suggested-action')
        self._add_repo_btn.connect('clicked', self._on_add_soplos_repo_clicked)
        repo_row.pack_start(self._add_repo_btn, False, False, 0)

        repo_inner.pack_start(repo_row, False, False, 0)
        repo_frame.add(repo_inner)
        box.pack_start(repo_frame, False, False, 0)

        # Kernels list card
        kernels_frame = Gtk.Frame()
        kernels_frame.get_style_context().add_class('soplos-card')
        kernels_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        kernels_header = Gtk.Label(label=_("Available kernels"))
        kernels_header.get_style_context().add_class('section-header')
        kernels_header.set_halign(Gtk.Align.START)
        kernels_inner.pack_start(kernels_header, False, False, 0)

        self._kernels_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        kernels_inner.pack_start(self._kernels_rows, False, False, 0)

        kernels_frame.add(kernels_inner)
        box.pack_start(kernels_frame, False, False, 0)

        scroll.add(box)
        return scroll

    @staticmethod
    def _soplos_pkg_display_name(pkg: str) -> str:
        suffix = pkg[len('linux-soplos'):]
        if not suffix:
            return _("Stock")
        suffix = suffix.lstrip('-')
        return suffix.upper() if len(suffix) <= 5 else suffix.replace('-', ' ').title()

    def _fetch_soplos_packages(self) -> None:
        def fetch():
            packages = []
            updates = {}
            versions = {}
            try:
                names = subprocess.run(
                    ['apt-cache', 'pkgnames', 'linux-soplos'],
                    capture_output=True, text=True
                )
                for pkg in sorted(names.stdout.splitlines()):
                    pkg = pkg.strip()
                    if not re.match(r'^linux-soplos(-[a-z]+)*$', pkg):
                        continue
                    show = subprocess.run(
                        ['apt-cache', 'show', pkg],
                        capture_output=True, text=True
                    )
                    desc = ""
                    suffix = ""
                    pkg_version = ""
                    for sline in show.stdout.splitlines():
                        if sline.startswith('Description:'):
                            desc = sline[len('Description:'):].strip()
                        elif sline.startswith('Version:'):
                            pkg_version = sline[len('Version:'):].strip()
                        elif sline.startswith('Depends:'):
                            for dep in sline[len('Depends:'):].split(','):
                                dep = dep.strip().split()[0]
                                if dep.startswith('linux-image-'):
                                    idx = dep.find('-soplos')
                                    if idx >= 0:
                                        suffix = dep[idx:]
                                    break
                    if not desc:
                        continue

                    policy = subprocess.run(
                        ['apt-cache', 'policy', pkg],
                        capture_output=True, text=True
                    )
                    installed_ver = ""
                    candidate_ver = ""
                    for pline in policy.stdout.splitlines():
                        pline = pline.strip()
                        if pline.startswith('Installed:'):
                            v = pline.split(':', 1)[1].strip()
                            if v != '(none)':
                                installed_ver = v
                        elif pline.startswith('Candidate:'):
                            v = pline.split(':', 1)[1].strip()
                            if v != '(none)':
                                candidate_ver = v
                    updates[pkg] = bool(installed_ver and candidate_ver and installed_ver != candidate_ver)
                    versions[pkg] = pkg_version

                    name = self._soplos_pkg_display_name(pkg)
                    packages.append((pkg, name, desc, suffix))
                packages.sort(key=lambda x: (0 if x[0] == 'linux-soplos' else 1, x[0]))
            except Exception:
                pass
            GLib.idle_add(self._on_soplos_packages_fetched, packages, updates, versions)

        threading.Thread(target=fetch, daemon=True).start()

    def _on_soplos_packages_fetched(self, packages, updates, versions) -> None:
        self._soplos_packages = packages
        self._soplos_updates = updates
        self._soplos_versions = versions
        self._rebuild_kernels_list()
        self._refresh_soplos_kernels_tab()

    def _rebuild_kernels_list(self) -> None:
        for child in self._kernels_rows.get_children():
            self._kernels_rows.remove(child)
        self._kernel_action_btns = {}
        self._kernel_update_btns = {}

        if not self._soplos_packages:
            lbl = Gtk.Label(label=_("No kernels available in repository"))
            lbl.get_style_context().add_class('dim-label')
            lbl.set_margin_top(8)
            lbl.set_margin_bottom(8)
            self._kernels_rows.pack_start(lbl, False, False, 0)
            self._kernels_rows.show_all()
            return

        first = True
        for pkg, name, desc, _suffix in self._soplos_packages:
            if not first:
                self._kernels_rows.pack_start(Gtk.Separator(), False, False, 0)
            first = False

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.set_margin_top(4)
            row.set_margin_bottom(4)

            info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            ver = self._soplos_versions.get(pkg, "")
            ver_str = f" <small>{ver}</small>" if ver else ""
            name_lbl = Gtk.Label(label=f"<b>{name}</b>{ver_str}")
            name_lbl.set_use_markup(True)
            name_lbl.set_halign(Gtk.Align.START)
            desc_lbl = Gtk.Label(label=desc)
            desc_lbl.get_style_context().add_class('dim-label')
            desc_lbl.set_halign(Gtk.Align.START)
            info.pack_start(name_lbl, False, False, 0)
            info.pack_start(desc_lbl, False, False, 0)
            row.pack_start(info, True, True, 0)

            upd_btn = Gtk.Button(label=_("Update"))
            upd_btn.get_style_context().add_class('suggested-action')
            upd_btn.connect('clicked', self._on_soplos_kernel_update, pkg)
            upd_btn.set_no_show_all(True)
            row.pack_start(upd_btn, False, False, 0)
            self._kernel_update_btns[pkg] = upd_btn

            btn = Gtk.Button()
            btn.connect('clicked', self._on_soplos_kernel_action, pkg)
            row.pack_start(btn, False, False, 0)
            self._kernel_action_btns[pkg] = btn

            self._kernels_rows.pack_start(row, False, False, 0)

        self._kernels_rows.show_all()

    def _refresh_soplos_kernels_tab(self) -> None:
        repo_installed = os.path.exists(self._SOPLOS_KERNELS_REPO_FILE)
        if repo_installed:
            self._repo_status_label.set_markup(_("Status: <b>Repository installed</b>"))
            self._add_repo_btn.hide()
            self._refresh_repo_btn.show()
        else:
            self._repo_status_label.set_markup(_("Status: Repository not configured"))
            self._add_repo_btn.show()
            self._refresh_repo_btn.hide()

        for pkg, _name, _desc, pattern in self._soplos_packages:
            btn = self._kernel_action_btns.get(pkg)
            if not btn:
                continue
            installed = self._is_soplos_kernel_installed(pkg, pattern)
            if installed:
                btn.set_label(_("Remove"))
                btn.get_style_context().remove_class('suggested-action')
                btn.get_style_context().add_class('destructive-action')
                btn.set_sensitive(True)
            else:
                btn.set_label(_("Install"))
                btn.get_style_context().remove_class('destructive-action')
                btn.get_style_context().add_class('suggested-action')
                btn.set_sensitive(repo_installed)

            upd_btn = self._kernel_update_btns.get(pkg)
            if upd_btn:
                if installed and self._soplos_updates.get(pkg, False):
                    upd_btn.show()
                else:
                    upd_btn.hide()

    def _is_soplos_kernel_installed(self, package: str, suffix: str = "") -> bool:
        if not suffix:
            return False
        return bool(glob.glob(f"/boot/vmlinuz-*{suffix}"))

    def _on_refresh_soplos_repo_clicked(self, btn) -> None:
        btn.set_sensitive(False)
        self._show_sk_progress(_("Updating repository..."))

        def run():
            from utils.system import run_privileged
            run_privileged("apt-get update -qq")
            GLib.idle_add(self._on_refresh_done, btn)

        threading.Thread(target=run, daemon=True).start()

    def _on_refresh_done(self, btn) -> None:
        self._hide_sk_progress()
        btn.set_sensitive(True)
        self._fetch_soplos_packages()

    def _on_add_soplos_repo_clicked(self, btn) -> None:
        cmd = (
            f'wget -qO- "{self._SOPLOS_KERNELS_GPG_URL}" | gpg --dearmor -o "{self._SOPLOS_KERNELS_GPG_FILE}" && '
            f'mkdir -p /etc/apt/sources.list.d && '
            f'printf "Types: deb\\nURIs: {self._SOPLOS_KERNELS_REPO_URL}\\nSuites: stable\\nComponents: main\\nSigned-By: {self._SOPLOS_KERNELS_GPG_FILE}\\n" '
            f'> "{self._SOPLOS_KERNELS_REPO_FILE}" && '
            f'apt-get update -qq'
        )
        btn.set_sensitive(False)
        btn.set_label(_("Adding..."))
        self._show_sk_progress(_("Adding Soplos Kernels repository..."))

        def run():
            from utils.system import run_privileged
            result = run_privileged(cmd)
            GLib.idle_add(self._on_repo_add_done, result.returncode == 0)

        threading.Thread(target=run, daemon=True).start()

    def _on_repo_add_done(self, success: bool) -> None:
        self._hide_sk_progress()
        if success:
            self._fetch_soplos_packages()
        else:
            self._add_repo_btn.set_sensitive(True)
            self._add_repo_btn.set_label(_("Add repository"))
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=_("Error adding repository")
            )
            dialog.run()
            dialog.destroy()

    def _on_soplos_kernel_update(self, btn, package: str) -> None:
        suffix = next((s for pkg, _n, _d, s in self._soplos_packages if pkg == package), "")
        btn.set_sensitive(False)
        self._show_sk_progress(_("Updating {pkg}...").format(pkg=package))

        def run():
            from utils.system import run_privileged
            ret = run_privileged(f"apt install -y --only-upgrade {package}").returncode
            if ret == 0 and suffix:
                # Purge old kernel image/headers (all but newest, skipping running kernel)
                cleanup = (
                    f"RUNNING=$(uname -r) && "
                    f"dpkg -l 'linux-image-*{suffix}' 2>/dev/null | awk '/^ii/{{print $2}}' | sort -V | head -n -1 | "
                    f"grep -v \"$RUNNING\" | xargs -r apt purge -y 2>/dev/null || true"
                )
                run_privileged(cleanup)
            GLib.idle_add(self._on_soplos_kernel_action_done, ret == 0)

        threading.Thread(target=run, daemon=True).start()

    def _on_soplos_kernel_action(self, btn, package: str) -> None:
        pattern = next((p for pkg, _n, _d, p in self._soplos_packages if pkg == package), "")
        installed = self._is_soplos_kernel_installed(package, pattern)
        action_label = _("Installing") if not installed else _("Removing")

        if not installed:
            cmd = f"apt install -y {package}"
        else:
            suffix = next((s for pkg, _n, _d, s in self._soplos_packages if pkg == package), "")
            extra_pkgs = []
            try:
                dpkg_out = subprocess.run(['dpkg', '-l'], capture_output=True, text=True).stdout
                for line in dpkg_out.splitlines():
                    if len(line) < 2 or line[1] != 'i':
                        continue
                    p = line.split()[1].split(':')[0]
                    if suffix and (p.startswith('linux-image-') or p.startswith('linux-headers-')) and p.endswith(suffix):
                        extra_pkgs.append(p)
            except Exception:
                pass
            all_pkgs = " ".join([package] + extra_pkgs)
            cmd = f"apt remove -y {all_pkgs} && apt autoremove --purge -y"

        for b in self._kernel_action_btns.values():
            b.set_sensitive(False)
        self._show_sk_progress(f"{action_label} {package}...")

        def run():
            from utils.system import run_privileged_with_callback

            progress_state = {"frac": 0.0}
            def on_line(line: str) -> None:
                if line.strip():
                    clean_line = line.strip()
                    GLib.idle_add(self._dep_label.set_text, clean_line[:100])
                    import re
                    
                    new_frac = progress_state["frac"]
                    m = re.search(r'(\d+)\s*%', clean_line)
                    if m:
                        try:
                            val = min(max(int(m.group(1)) / 100.0, 0.0), 1.0)
                            if "Leyendo la base" in clean_line:
                                new_frac = max(new_frac, val * 0.3)
                            else:
                                new_frac = max(new_frac, val)
                        except ValueError:
                            pass
                    elif "Desempaquetando" in clean_line or "Unpacking" in clean_line:
                        new_frac = max(new_frac, 0.4)
                    elif "dracut" in clean_line.lower() or "initramfs" in clean_line.lower():
                        new_frac = max(new_frac, 0.8)
                    elif "grub" in clean_line.lower() or "GRUB" in clean_line:
                        new_frac = max(new_frac, 0.9)
                    elif "Configurando" in clean_line or "Setting up" in clean_line:
                        if "linux-soplos" in clean_line and progress_state["frac"] >= 0.9:
                            new_frac = max(new_frac, 0.95)
                        else:
                            new_frac = max(new_frac, 0.6)
                            
                    if new_frac > progress_state["frac"]:
                        progress_state["frac"] = new_frac
                        GLib.idle_add(self._dep_progress.set_fraction, new_frac)
                        GLib.idle_add(self._dep_progress.set_show_text, True)
                        GLib.idle_add(self._dep_progress.set_text, f"{int(new_frac * 100)}%")

            ret = run_privileged_with_callback(cmd, line_callback=on_line)
            GLib.idle_add(self._on_soplos_kernel_action_done, ret == 0)

        threading.Thread(target=run, daemon=True).start()

    def _on_soplos_kernel_action_done(self, success: bool) -> None:
        self._hide_sk_progress()
        self._refresh_soplos_kernels_tab()
        self._history_view.refresh()
        if not success:
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=_("Operation failed")
            )
            dialog.run()
            dialog.destroy()

    def _show_sk_progress(self, message: str) -> None:
        self._dep_label.set_text(message)
        self._dep_progress.set_text("")
        self._dep_progress.set_fraction(0.0)
        self._progress_revealer.set_reveal_child(True)

    def _hide_sk_progress(self) -> None:
        self._stop_pulse()
        self._progress_revealer.set_reveal_child(False)

    # ------------------------------------------------------------------
    # Initial load
    # ------------------------------------------------------------------

    def _load_initial_data(self) -> bool:
        def fetch_info():
            try:
                distro = self._kernel_manager.get_system_label()
                kernel = self._kernel_manager.get_current_kernel()
                initramfs = "dracut"
            except Exception:
                distro = "Soplos Linux"
                kernel = "Unknown"
                initramfs = "dracut"
            GLib.idle_add(self._apply_system_info, distro, kernel, initramfs)

        threading.Thread(target=fetch_info, daemon=True).start()
        self._version_picker.refresh_versions()
        self._history_view.refresh()
        self._fetch_soplos_packages()
        self._notebook.connect('switch-page', lambda nb, pg, n: self._fetch_soplos_packages() if n == 1 else None)
        return False

    def _apply_system_info(self, distro: str, kernel: str, initramfs: str) -> bool:
        self._distro_value.set_text(distro)
        self._kernel_value.set_text(kernel)
        self._initramfs_value.set_text(initramfs)
        self._update_name_hint()
        return False

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_profile_changed(self, selector, profile) -> None:
        if profile and profile.id == ProfileType.STOCK:
            self._patch_selector.clear_all()
        elif profile:
            self._patch_selector.apply_profile_suggestions(profile)
        self._kernel_name_entry.set_sensitive(True)
        self._update_name_hint()

    def _activate_stock_profile(self) -> None:
        self._profile_selector.toggle_stock_profile()

    def _on_version_changed(self, picker, version: str) -> None:
        self._update_name_hint()
        self._patch_selector.update_for_version(version)

    def _on_version_loading_started(self, picker) -> None:
        self._install_btn.set_sensitive(False)

    def _on_version_loading_finished(self, picker) -> None:
        if not self._building:
            self._install_btn.set_sensitive(True)
        # Apply initial patch suggestions now that versions are loaded
        version = self._version_picker.get_selected_version()
        if version:
            self._patch_selector.update_for_version(version)
        profile = self._profile_selector.get_selected_profile()
        if profile:
            self._patch_selector.apply_profile_suggestions(profile)

    def _on_kernel_name_changed(self, entry) -> None:
        self._update_name_hint()

    def _update_name_hint(self) -> None:
        version = self._version_picker.get_selected_version() or "6.x.x"
        name = self._kernel_name_entry.get_text().strip() or "soplos"
        profile = self._profile_selector.get_selected_profile()
        suffix = profile.suffix if profile else "gaming"
        if suffix:
            result = f"{version}-{name}-{suffix}"
        else:
            result = f"{version}-{name}"
        self._name_hint_label.set_text(_("Result: {}").format(result))

    def _on_manage_keys_clicked(self, btn) -> None:
        self._show_mok_dialog()

    def _show_mok_dialog(self) -> None:
        keys_exist = self._kernel_manager.sb_keys_exist()

        dialog = Gtk.Dialog(
            title=_("Secure Boot Key Management"),
            transient_for=self,
            modal=True
        )
        dialog.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        dialog.set_default_size(500, -1)

        content = dialog.get_content_area()
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_spacing(15)

        header = Gtk.Label()
        header.set_markup("<b>" + _("Secure Boot Setup Wizard") + "</b>")
        header.set_halign(Gtk.Align.START)
        content.pack_start(header, False, False, 0)

        intro = Gtk.Label(label=_("Follow these steps to enable Secure Boot support for your custom kernels."))
        intro.set_line_wrap(True)
        intro.set_halign(Gtk.Align.START)
        content.pack_start(intro, False, False, 0)

        # --- STEP 1: Generate Keys ---
        step1_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        step1_icon = "✅" if keys_exist else "➡️"
        step1_title = Gtk.Label()
        step1_title.set_markup(f"<b>{step1_icon} " + _("Step 1: Generate MOK Keys") + "</b>")
        step1_title.set_halign(Gtk.Align.START)
        step1_box.pack_start(step1_title, False, False, 0)

        if not keys_exist:
            step1_desc = Gtk.Label(label=_("Create a key pair to sign your custom kernels."))
            step1_desc.set_halign(Gtk.Align.START)
            step1_desc.set_margin_start(30)
            step1_box.pack_start(step1_desc, False, False, 0)

            def _on_gen(btn):
                if self._kernel_manager.sb_generate_keys():
                    dialog.response(Gtk.ResponseType.OK)
                else:
                    err = Gtk.MessageDialog(
                        transient_for=dialog, message_type=Gtk.MessageType.ERROR,
                        buttons=Gtk.ButtonsType.OK, text=_("Failed to generate keys.")
                    )
                    err.run()
                    err.destroy()

            gen_btn = Gtk.Button(label=_("Generate MOK Keys"))
            gen_btn.get_style_context().add_class('suggested-action')
            gen_btn.set_margin_start(30)
            gen_btn.set_halign(Gtk.Align.START)
            gen_btn.connect('clicked', _on_gen)
            step1_box.pack_start(gen_btn, False, False, 0)
        else:
            step1_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            step1_row.set_margin_start(30)

            step1_done = Gtk.Label(label=_("Keys already generated."))
            step1_done.set_halign(Gtk.Align.START)
            step1_row.pack_start(step1_done, True, True, 0)

            def _on_delete_keys(btn):
                enrolled = self._kernel_manager.sb_is_enrolled()
                confirm = Gtk.MessageDialog(
                    transient_for=dialog,
                    message_type=Gtk.MessageType.WARNING,
                    buttons=Gtk.ButtonsType.YES_NO,
                    text=_("Delete MOK keys?")
                )
                if enrolled:
                    confirm.format_secondary_text(
                        _("The key is currently enrolled in BIOS.\n\n"
                          "It will be queued for unenrollment on next reboot.\n"
                          "You will need to enter a password to confirm.")
                    )
                else:
                    confirm.format_secondary_text(
                        _("This will delete your local key files.")
                    )
                if confirm.run() != Gtk.ResponseType.YES:
                    confirm.destroy()
                    return
                confirm.destroy()

                if enrolled:
                    self._do_delete_mok(dialog)
                else:
                    if self._kernel_manager.sb_delete_keys():
                        dialog.response(Gtk.ResponseType.OK)

            delete_btn = Gtk.Button(label=_("Delete Keys"))
            delete_btn.get_style_context().add_class('destructive-action')
            delete_btn.connect('clicked', _on_delete_keys)
            step1_row.pack_start(delete_btn, False, False, 0)

            step1_box.pack_start(step1_row, False, False, 0)

        keys_path = str(self._kernel_manager._secure_boot.config_dir)
        path_label = Gtk.Label(label=keys_path)
        path_label.get_style_context().add_class('dim-label')
        path_label.set_halign(Gtk.Align.START)
        path_label.set_margin_start(30)
        path_label.set_selectable(True)
        step1_box.pack_start(path_label, False, False, 0)

        content.pack_start(step1_box, False, False, 0)

        # --- STEP 2: Enable Signing ---
        step2_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        step2_icon = "✔️" if keys_exist else "⬜"
        step2_title = Gtk.Label()
        step2_title.set_markup(f"<b>{step2_icon} " + _("Step 2: Enable Kernel Signing") + "</b>")
        step2_title.set_halign(Gtk.Align.START)
        step2_box.pack_start(step2_title, False, False, 0)

        step2_instructions = Gtk.Label()
        step2_instructions.set_markup(
            _("You already have your local keys. Now you can:\n"
              "1. Close this window\n"
              "2. Check 'Sign Kernel for Secure Boot (MOK)'\n"
              "3. <b>Start the Installation</b>")
        )
        step2_instructions.set_halign(Gtk.Align.START)
        step2_instructions.set_margin_start(30)
        step2_instructions.set_line_wrap(True)
        step2_box.pack_start(step2_instructions, False, False, 0)

        content.pack_start(step2_box, False, False, 0)

        # --- STEP 3: Enroll Key in BIOS ---
        step3_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        step3_icon = "⏳" if keys_exist else "⬜"
        step3_title = Gtk.Label()
        step3_title.set_markup(f"<b>{step3_icon} " + _("Step 3: Enroll Key in BIOS (Required to Boot)") + "</b>")
        step3_title.set_halign(Gtk.Align.START)
        step3_box.pack_start(step3_title, False, False, 0)

        step3_instructions = Gtk.Label()
        step3_instructions.set_markup(
            _("This step is only needed once. It is recommended to do it <b>after</b> installing your first kernel:\n"
              "1. Click 'Enroll Key' (enter a password)\n"
              "2. <b>Restart</b> and select 'Enroll MOK' in the blue menu.")
        )
        step3_instructions.set_halign(Gtk.Align.START)
        step3_instructions.set_margin_start(30)
        step3_instructions.set_line_wrap(True)
        step3_box.pack_start(step3_instructions, False, False, 0)

        if keys_exist:
            def _on_run_enroll(btn):
                self._prompt_and_enroll_mok(dialog)

            enroll_btn = Gtk.Button(label=_("Enroll Key in BIOS"))
            enroll_btn.get_style_context().add_class('suggested-action')
            enroll_btn.set_margin_start(30)
            enroll_btn.set_halign(Gtk.Align.START)
            enroll_btn.connect('clicked', _on_run_enroll)
            step3_box.pack_start(enroll_btn, False, False, 0)

        content.pack_start(step3_box, False, False, 0)

        # --- DKMS MOK Key (nvidia/virtualbox etc.) ---
        dkms_mok_pub = "/var/lib/dkms/mok.pub"
        dkms_dir = "/var/lib/dkms"
        # Show section if mok.pub exists OR if any DKMS modules are installed
        has_dkms_modules = os.path.isdir(dkms_dir) and any(
            os.path.isdir(os.path.join(dkms_dir, d))
            for d in os.listdir(dkms_dir)
            if not d.startswith("mok")
        )
        if has_dkms_modules:
            dkms_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            dkms_title = Gtk.Label()

            if not os.path.exists(dkms_mok_pub):
                # DKMS modules exist but the signing key is missing entirely
                dkms_title.set_markup("<b>⚠️ " + _("DKMS Key (NVIDIA / VirtualBox drivers)") + "</b>")
                dkms_title.set_halign(Gtk.Align.START)
                dkms_box.pack_start(dkms_title, False, False, 0)

                dkms_desc = Gtk.Label()
                dkms_desc.set_markup(
                    _("DKMS modules are installed but the signing key is <b>missing</b>.\n"
                      "Reinstall your NVIDIA or VirtualBox drivers from soplos-welcome to regenerate it.")
                )
                dkms_desc.set_halign(Gtk.Align.START)
                dkms_desc.set_margin_start(30)
                dkms_desc.set_line_wrap(True)
                dkms_box.pack_start(dkms_desc, False, False, 0)
            else:
                dkms_enrolled = self._kernel_manager._secure_boot.dkms_key_enrolled()
                dkms_icon = "✅" if dkms_enrolled else "⬜"
                dkms_title.set_markup(f"<b>{dkms_icon} " + _("DKMS Key (NVIDIA / VirtualBox drivers)") + "</b>")
                dkms_title.set_halign(Gtk.Align.START)
                dkms_box.pack_start(dkms_title, False, False, 0)

                dkms_desc = Gtk.Label()
                if dkms_enrolled:
                    dkms_desc.set_text(
                        _("The DKMS signing key is enrolled. Each time a new kernel is installed, "
                          "DKMS automatically rebuilds and signs the NVIDIA modules — "
                          "they will load correctly with Secure Boot active.")
                    )
                else:
                    dkms_desc.set_markup(
                        _("Each time a new kernel is installed, DKMS automatically rebuilds "
                          "your NVIDIA modules for that kernel. With Secure Boot active, "
                          "those modules must be signed with this key to load.\n\n"
                          "The DKMS signing key is <b>not enrolled</b>. Without it, NVIDIA and "
                          "other DKMS drivers will fail to load.\n"
                          "Enroll it now alongside your kernel key.")
                    )
                dkms_desc.set_halign(Gtk.Align.START)
                dkms_desc.set_margin_start(30)
                dkms_desc.set_line_wrap(True)
                dkms_box.pack_start(dkms_desc, False, False, 0)

                if not dkms_enrolled:
                    def _on_enroll_dkms(btn):
                        self._prompt_and_enroll_mok(dialog, der_path=dkms_mok_pub)

                    dkms_btn = Gtk.Button(label=_("Enroll DKMS Key in BIOS"))
                    dkms_btn.get_style_context().add_class('suggested-action')
                    dkms_btn.set_margin_start(30)
                    dkms_btn.set_halign(Gtk.Align.START)
                    dkms_btn.connect('clicked', _on_enroll_dkms)
                    dkms_box.pack_start(dkms_btn, False, False, 0)

            content.pack_start(dkms_box, False, False, 0)

        # --- STEP 4: Enable Secure Boot ---
        step4_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        step4_title = Gtk.Label()
        step4_title.set_markup("<b>⬜ " + _("Step 4: Enable Secure Boot") + "</b>")
        step4_title.set_halign(Gtk.Align.START)
        step4_box.pack_start(step4_title, False, False, 0)

        step4_desc = Gtk.Label(label=_("After installing the signed kernel, enable Secure Boot in your BIOS/UEFI settings."))
        step4_desc.set_halign(Gtk.Align.START)
        step4_desc.set_margin_start(30)
        step4_desc.set_line_wrap(True)
        step4_box.pack_start(step4_desc, False, False, 0)

        content.pack_start(step4_box, False, False, 0)

        # --- Reset MOK Database ---
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        content.pack_start(sep, False, False, 0)

        reset_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        reset_title = Gtk.Label()
        reset_title.set_markup("<b>⚠️ " + _("Reset MOK Database") + "</b>")
        reset_title.set_halign(Gtk.Align.START)
        reset_box.pack_start(reset_title, False, False, 0)

        reset_desc = Gtk.Label(label=_("Removes ALL enrolled MOK keys from BIOS. Useful to clean up stale keys."))
        reset_desc.set_halign(Gtk.Align.START)
        reset_desc.set_margin_start(30)
        reset_desc.set_line_wrap(True)
        reset_box.pack_start(reset_desc, False, False, 0)

        def _on_reset_mok(btn):
            self._do_reset_mok(dialog)

        reset_btn = Gtk.Button(label=_("Reset MOK Database"))
        reset_btn.get_style_context().add_class('destructive-action')
        reset_btn.set_margin_start(30)
        reset_btn.set_halign(Gtk.Align.START)
        reset_btn.connect('clicked', _on_reset_mok)
        reset_box.pack_start(reset_btn, False, False, 0)

        content.pack_start(reset_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()
        dialog.destroy()

        # Reopen to reflect new state after generate or delete
        if response == Gtk.ResponseType.OK:
            self._show_mok_dialog()

    def _prompt_and_enroll_mok(self, parent, der_path=None) -> None:
        """Diálogo de contraseña + enroll MOK via script temporal."""
        if der_path is None:
            der_path = self._kernel_manager._secure_boot.der_key

        while True:
            pwd_dialog = Gtk.Dialog(
                title=_("Create MOK Password"),
                transient_for=parent, modal=True
            )
            pwd_dialog.add_buttons(
                _("Cancel"), Gtk.ResponseType.CANCEL,
                _("Enroll"),  Gtk.ResponseType.OK
            )
            pwd_dialog.set_default_size(400, -1)

            content = pwd_dialog.get_content_area()
            content.set_margin_start(20)
            content.set_margin_end(20)
            content.set_margin_top(20)
            content.set_margin_bottom(20)
            content.set_spacing(10)

            info_label = Gtk.Label()
            info_label.set_markup(
                "<b>" + _("Create a password for MOK enrollment") + "</b>\n\n" +
                _("You will need this password during the next reboot.") + "\n" +
                "<i>" + _("Minimum 8 characters") + "</i>"
            )
            info_label.set_halign(Gtk.Align.START)
            content.pack_start(info_label, False, False, 0)

            entry1 = Gtk.Entry()
            entry1.set_visibility(False)
            entry1.set_placeholder_text(_("Enter password (min 8 characters)"))
            content.pack_start(entry1, False, False, 0)

            entry2 = Gtk.Entry()
            entry2.set_visibility(False)
            entry2.set_placeholder_text(_("Confirm password"))
            content.pack_start(entry2, False, False, 0)

            pwd_dialog.show_all()
            response = pwd_dialog.run()

            if response != Gtk.ResponseType.OK:
                pwd_dialog.destroy()
                break

            pwd1 = entry1.get_text()
            pwd2 = entry2.get_text()
            pwd_dialog.destroy()

            if pwd1 != pwd2:
                self._show_error(_("Passwords do not match."))
                continue
            if len(pwd1) < 8:
                self._show_error(_("Password must be at least 8 characters."))
                continue

            self._do_enroll_mok(pwd1, der_path, parent)
            break

    def _do_enroll_mok(self, password: str, der_path, parent) -> None:
        """Ejecuta el enroll via script temporal con pkexec."""

        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.sh', delete=False
            ) as f:
                script_path = f.name
                f.write("#!/bin/bash\n")
                f.write(f'printf \'%s\\n%s\\n\' {shlex.quote(password)} {shlex.quote(password)} | mokutil --import {shlex.quote(str(der_path))}\n')
                f.write("exit $?\n")

            os.chmod(script_path, 0o700)
            proc = subprocess.run(
                ['pkexec', 'bash', script_path],
                capture_output=True, timeout=30
            )
        except Exception as e:
            self._show_error(_("Error during MOK enrollment: {}").format(e))
            return
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

        if proc.returncode == 0:
            d = Gtk.MessageDialog(
                transient_for=parent, modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=_("Key enrollment scheduled!")
            )
            d.format_secondary_text(
                _("Your MOK key has been queued for enrollment.\n"
                  "It will take effect on the next system restart.")
            )
            d.run()
            d.destroy()
            self._ask_reboot()
        else:
            err = proc.stderr.decode(errors='replace') if proc.stderr else _("Unknown error")
            self._show_error(_("MOK enrollment failed:\n{}").format(err))

    def _do_delete_mok(self, parent) -> None:
        """Queues MOK key unenrollment via mokutil --delete, then deletes local files."""

        der_path = self._kernel_manager._secure_boot.der_key

        # Ask password for mokutil --delete confirmation on next reboot
        pwd_dialog = Gtk.Dialog(
            title=_("Unenroll MOK Key"),
            transient_for=parent, modal=True
        )
        pwd_dialog.add_buttons(
            _("Cancel"), Gtk.ResponseType.CANCEL,
            _("Unenroll"), Gtk.ResponseType.OK
        )
        pwd_dialog.set_default_size(400, -1)

        content = pwd_dialog.get_content_area()
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_spacing(10)

        info_label = Gtk.Label()
        info_label.set_markup(
            "<b>" + _("Set a password to confirm unenrollment") + "</b>\n\n" +
            _("You will need this password on the next reboot to confirm\n"
              "removal of the key from the BIOS.") + "\n" +
            "<i>" + _("Minimum 8 characters") + "</i>"
        )
        info_label.set_halign(Gtk.Align.START)
        content.pack_start(info_label, False, False, 0)

        entry1 = Gtk.Entry()
        entry1.set_visibility(False)
        entry1.set_placeholder_text(_("Enter password (min 8 characters)"))
        content.pack_start(entry1, False, False, 0)

        entry2 = Gtk.Entry()
        entry2.set_visibility(False)
        entry2.set_placeholder_text(_("Confirm password"))
        content.pack_start(entry2, False, False, 0)

        pwd_dialog.show_all()
        response = pwd_dialog.run()
        pwd1 = entry1.get_text()
        pwd2 = entry2.get_text()
        pwd_dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return
        if pwd1 != pwd2:
            self._show_error(_("Passwords do not match."))
            return
        if len(pwd1) < 8:
            self._show_error(_("Password must be at least 8 characters."))
            return

        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.sh', delete=False
            ) as f:
                script_path = f.name
                f.write("#!/bin/bash\n")
                f.write(f'printf \'%s\\n%s\\n\' {shlex.quote(pwd1)} {shlex.quote(pwd1)} | mokutil --delete {shlex.quote(str(der_path))}\n')
                f.write("exit $?\n")

            os.chmod(script_path, 0o700)
            proc = subprocess.run(
                ['pkexec', 'bash', script_path],
                capture_output=True, timeout=30
            )
        except Exception as e:
            self._show_error(_("Error during MOK unenrollment: {}").format(e))
            return
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

        if proc.returncode == 0:
            self._kernel_manager.sb_delete_keys()
            d = Gtk.MessageDialog(
                transient_for=parent, modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=_("Key unenrollment scheduled!")
            )
            d.format_secondary_text(
                _("The MOK key has been queued for removal from BIOS.\n"
                  "It will take effect on the next system restart.")
            )
            d.run()
            d.destroy()
            if isinstance(parent, Gtk.Dialog):
                parent.response(Gtk.ResponseType.OK)
            self._ask_reboot()
        else:
            err = proc.stderr.decode(errors='replace') if proc.stderr else _("Unknown error")
            self._show_error(_("MOK unenrollment failed:\n{}").format(err))

    def _do_reset_mok(self, parent) -> None:
        """Queues a full MOK database reset via mokutil --reset."""

        confirm = Gtk.MessageDialog(
            transient_for=parent,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Reset MOK database?")
        )
        confirm.format_secondary_text(
            _("This will remove ALL enrolled MOK keys from BIOS on next reboot.\n\n"
              "You will need to re-enroll your key after the reset.")
        )
        if confirm.run() != Gtk.ResponseType.YES:
            confirm.destroy()
            return
        confirm.destroy()

        pwd_dialog = Gtk.Dialog(
            title=_("Confirm MOK Reset"),
            transient_for=parent, modal=True
        )
        pwd_dialog.add_buttons(
            _("Cancel"), Gtk.ResponseType.CANCEL,
            _("Reset"), Gtk.ResponseType.OK
        )
        pwd_dialog.set_default_size(400, -1)

        content = pwd_dialog.get_content_area()
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_spacing(10)

        info_label = Gtk.Label()
        info_label.set_markup(
            "<b>" + _("Set a password to confirm the reset") + "</b>\n\n" +
            _("You will need this password on the next reboot to confirm\n"
              "removal of all MOK keys from BIOS.") + "\n" +
            "<i>" + _("Minimum 8 characters") + "</i>"
        )
        info_label.set_halign(Gtk.Align.START)
        content.pack_start(info_label, False, False, 0)

        entry1 = Gtk.Entry()
        entry1.set_visibility(False)
        entry1.set_placeholder_text(_("Enter password (min 8 characters)"))
        content.pack_start(entry1, False, False, 0)

        entry2 = Gtk.Entry()
        entry2.set_visibility(False)
        entry2.set_placeholder_text(_("Confirm password"))
        content.pack_start(entry2, False, False, 0)

        pwd_dialog.show_all()
        response = pwd_dialog.run()
        pwd1 = entry1.get_text()
        pwd2 = entry2.get_text()
        pwd_dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return
        if pwd1 != pwd2:
            self._show_error(_("Passwords do not match."))
            return
        if len(pwd1) < 8:
            self._show_error(_("Password must be at least 8 characters."))
            return

        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.sh', delete=False
            ) as f:
                script_path = f.name
                f.write("#!/bin/bash\n")
                f.write(f'printf \'%s\\n%s\\n\' {shlex.quote(pwd1)} {shlex.quote(pwd1)} | mokutil --reset\n')
                f.write("exit $?\n")

            os.chmod(script_path, 0o700)
            proc = subprocess.run(
                ['pkexec', 'bash', script_path],
                capture_output=True, timeout=30
            )
        except Exception as e:
            self._show_error(_("Error during MOK reset: {}").format(e))
            return
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

        if proc.returncode == 0:
            d = Gtk.MessageDialog(
                transient_for=parent, modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=_("MOK reset scheduled!")
            )
            d.format_secondary_text(
                _("All MOK keys will be removed from BIOS on the next reboot.\n"
                  "Confirm with your password in the blue MOK manager screen.")
            )
            d.run()
            d.destroy()
            self._ask_reboot()
        else:
            err = proc.stderr.decode(errors='replace') if proc.stderr else _("Unknown error")
            self._show_error(_("MOK reset failed:\n{}").format(err))

    # ------------------------------------------------------------------
    # Install
    # ------------------------------------------------------------------

    def _on_install_clicked(self, btn) -> None:
        self._install_btn.set_sensitive(False)

        version = self._version_picker.get_selected_version()
        if not version:
            self._show_error(_("Select a kernel version first."))
            self._install_btn.set_sensitive(True)
            return

        profile = self._profile_selector.get_selected_profile()
        if not profile:
            self._show_error(_("Select a kernel profile first."))
            self._install_btn.set_sensitive(True)
            return

        custom_name = self._kernel_name_entry.get_text().strip() or "soplos"
        if not re.match(r'^[a-zA-Z0-9._-]+$', custom_name):
            self._show_error(
                _("Invalid kernel name '{}'. Only letters, numbers, dots, hyphens and underscores are allowed.").format(custom_name)
            )
            self._install_btn.set_sensitive(True)
            return
        patch_ids = self._patch_selector.get_selected_patch_ids()
        secure_boot = self._secure_boot_check.get_active()

        build_dir = os.path.join(get_build_directory(), f"linux-{version}")
        reuse_source = False
        if os.path.isdir(build_dir):
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text=_("Existing build found")
            )
            dialog.format_secondary_text(
                _("A build directory for kernel %(version)s already exists.\n\n"
                  "• Start Fresh: re-download sources and patches.\n"
                  "• Reuse Sources: skip download, apply selected patches and recompile.") % {'version': version}
            )
            dialog.add_buttons(
                _("Cancel"),       Gtk.ResponseType.CANCEL,
                _("Start Fresh"),  Gtk.ResponseType.NO,
                _("Reuse Sources"), Gtk.ResponseType.YES,
            )
            dialog.get_widget_for_response(Gtk.ResponseType.YES).get_style_context().add_class('suggested-action')
            response = dialog.run()
            dialog.destroy()
            if response == Gtk.ResponseType.CANCEL:
                self._install_btn.set_sensitive(True)
                return
            reuse_source = (response == Gtk.ResponseType.YES)

        if secure_boot and not self._kernel_manager.sb_keys_exist():
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text=_("Secure Boot signing enabled but no MOK keys found.")
            )
            dialog.format_secondary_text(
                _("Generate MOK keys now? (Required for Secure Boot signing)")
            )
            resp = dialog.run()
            dialog.destroy()
            if resp == Gtk.ResponseType.YES:
                if not self._kernel_manager.sb_generate_keys():
                    self._show_error(_("Failed to generate MOK keys."))
                    self._install_btn.set_sensitive(True)
                    return
            else:
                secure_boot = False

        self._current_build_profile = profile
        self._current_build_version = version
        self._current_build_custom_name = custom_name

        self._building = True
        self._install_btn.hide()
        self._build_ctrl_box.show_all()
        self._dep_progress.set_fraction(0.0)
        self._dep_label.set_text("")
        self._progress_revealer.set_reveal_child(True)
        self._build_progress.start_build()
        self._cancel_btn.set_sensitive(True)
        self._back_btn.set_sensitive(True)
        self._done_btn.hide()
        self._last_secure_boot = secure_boot
        self._start_pulse()
        self._inhibit_cookie = self.get_application().inhibit(
            self,
            Gtk.ApplicationInhibitFlags.SUSPEND | Gtk.ApplicationInhibitFlags.IDLE,
            _("Kernel compilation in progress")
        )

        def progress_cb(message: str, percent: int) -> None:
            GLib.idle_add(self._on_build_progress, message, percent)

        self._kernel_manager.set_progress_callback(progress_cb)

        is_stock = (profile.id == ProfileType.STOCK)

        def run_install():
            log_path = os.path.join(os.path.expanduser('~'), 'kernel_build', 'build.log')
            try:
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, 'w') as f:
                    f.write("")
            except Exception as e:
                print(f"Error creating log file: {e}")
            GLib.idle_add(self._build_progress.monitor_log_file, log_path)
            success = self._kernel_manager.full_install(
                version=version,
                profile=profile,
                custom_name=custom_name,
                patch_ids=patch_ids,
                secure_boot=secure_boot,
                reuse_source=reuse_source,
                build_only=is_stock,
            )
            GLib.idle_add(self._on_build_finished, success)

        threading.Thread(target=run_install, daemon=True).start()

    def _pulse_progress(self) -> bool:
        if self._progress_indeterminate and self._progress_revealer.get_reveal_child():
            self._dep_progress.pulse()
        return True

    def _start_pulse(self) -> None:
        self._progress_indeterminate = True
        if self._pulse_timer_id is None:
            self._pulse_timer_id = GLib.timeout_add(100, self._pulse_progress)

    def _stop_pulse(self) -> None:
        self._progress_indeterminate = False
        if self._pulse_timer_id is not None:
            GLib.source_remove(self._pulse_timer_id)
            self._pulse_timer_id = None

    def _on_build_progress(self, message: str, percent: int) -> bool:
        self._build_progress.update_progress(message, percent)
        try:
            self._progress_revealer.set_reveal_child(True)
            if message:
                self._dep_label.set_text(message)
            if percent >= 0:
                self._progress_indeterminate = False
                self._dep_progress.set_fraction(percent / 100.0)
                self._dep_progress.set_text(f"{percent}%")
            else:
                self._start_pulse()
        except Exception:
            pass
        return False

    def _on_build_finished(self, success: bool) -> bool:
        self._building = False
        self._stop_pulse()
        if self._inhibit_cookie:
            self.get_application().uninhibit(self._inhibit_cookie)
            self._inhibit_cookie = 0
        self._build_progress.set_complete(success)
        self._cancel_btn.set_sensitive(False)
        self._back_btn.set_sensitive(True)
        self._done_btn.show()
        self._build_ctrl_box.hide()
        self._install_btn.show()
        self._install_btn.set_sensitive(True)
        self._progress_revealer.set_reveal_child(False)

        if success:
            is_stock = (
                self._current_build_profile is not None
                and self._current_build_profile.id == ProfileType.STOCK
            )

            if is_stock:
                self._build_progress.append_log(_("\n✓ Kernel build complete!"))
                self._stock_post_build()
                if self._cleanup_check.get_active():
                    if not self._kernel_manager.cleanup_build_files():
                        self._show_error(_("Could not delete the build directory.\nCheck permissions or disk state."))
            else:
                self._build_progress.append_log(_("\n✓ Kernel installed successfully!"))
                self._history_view.refresh()

                if self._cleanup_check.get_active():
                    self._cleanup_after_install()

                is_efi = os.path.exists("/sys/firmware/efi")

                # Enroll kernel MOK key if needed
                if (self._last_secure_boot and is_efi and
                        self._kernel_manager.sb_keys_exist() and
                        not self._kernel_manager.sb_is_enrolled()):
                    self._prompt_and_enroll_mok(self)

                # If NVIDIA present and Secure Boot active, prompt to enroll DKMS key
                # so nvidia-uvm and CUDA/NVENC work correctly after reboot
                if (self._last_secure_boot and is_efi and has_nvidia_gpu()):
                    dkms_pub = "/var/lib/dkms/mok.pub"
                    if (os.path.exists(dkms_pub) and
                            not self._kernel_manager._secure_boot.dkms_key_enrolled()):
                        self._ask_enroll_dkms_mok_post_install(dkms_pub)
                        return False

                self._ask_reboot()
        else:
            self._build_progress.append_log(_("\n✗ Installation failed. Check the log above."))

        return False

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _on_back_clicked(self, btn) -> None:
        self._stack.set_visible_child_name("config")

    def _on_done_clicked(self, btn) -> None:
        self._stack.set_visible_child_name("config")
        self._install_btn.set_sensitive(True)

    def _on_cancel_clicked(self, btn) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=_("Cancel build?")
        )
        dialog.format_secondary_text(
            _("Do you want to keep the build folder?\n"
              "Keeping it allows reusing downloaded sources next time.")
        )
        dialog.add_button(_("Delete build folder"), Gtk.ResponseType.NO)
        dialog.add_button(_("Keep build folder"), Gtk.ResponseType.YES)
        dialog.add_button(_("Continue building"), Gtk.ResponseType.CANCEL)
        dialog.set_default_response(Gtk.ResponseType.YES)
        resp = dialog.run()
        dialog.destroy()

        if resp == Gtk.ResponseType.CANCEL:
            return

        cleanup = (resp == Gtk.ResponseType.NO)
        self._building = False
        self._kernel_manager.cancel(cleanup=cleanup)
        self._build_progress.set_complete(success=False, cancelled=True)
        self._build_progress.append_log(_("\n⚠ Installation cancelled."))
        self._cancel_btn.set_sensitive(False)
        self._back_btn.set_sensitive(True)
        self._done_btn.show()
        self._build_ctrl_box.hide()
        self._install_btn.show()
        self._install_btn.set_sensitive(True)
        self._progress_revealer.set_reveal_child(False)

    def _on_details_clicked(self, btn) -> None:
        self._stack.set_visible_child_name("build")

    # ------------------------------------------------------------------
    # Remove kernel
    # ------------------------------------------------------------------

    def _on_remove_kernel(self, history_view, kernel_release: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Remove kernel {}?").format(kernel_release)
        )
        dialog.format_secondary_text(
            _("This will remove the kernel and update GRUB.\n"
              "Make sure you have another kernel installed.")
        )
        resp = dialog.run()
        dialog.destroy()
        if resp != Gtk.ResponseType.YES:
            return

        if self._kernel_manager.remove_kernel(kernel_release):
            self._history_view.refresh()
            self._refresh_soplos_kernels_tab()
            # If no more MOK-signed kernels remain, offer to revoke the MOK enrollment
            if (self._kernel_manager.sb_keys_exist() and
                    not self._kernel_manager.sb_has_mok_signed_kernels()):
                mok_dialog = Gtk.MessageDialog(
                    transient_for=self, modal=True,
                    message_type=Gtk.MessageType.QUESTION,
                    buttons=Gtk.ButtonsType.YES_NO,
                    text=_("Revoke MOK key?")
                )
                mok_dialog.format_secondary_text(
                    _("No more Secure Boot signed kernels are installed.\n"
                      "Do you want to revoke the MOK key from the firmware?\n"
                      "You will need to confirm on next reboot.")
                )
                mok_resp = mok_dialog.run()
                mok_dialog.destroy()
                if mok_resp == Gtk.ResponseType.YES:
                    cmd = self._kernel_manager.sb_get_delete_mok_command()
                    if cmd:
                        import subprocess
                        subprocess.Popen(cmd, shell=True)
                    self._kernel_manager.sb_delete_keys()
        else:
            self._show_error(_("Failed to remove kernel."))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def refresh_versions(self) -> None:
        self._version_picker.refresh_versions()

    def _stock_post_build(self) -> None:
        version = self._current_build_version
        custom_name = self._current_build_custom_name
        pkg_name = f"linux-{custom_name}"

        build_dir = get_build_directory()

        # Prefer last_kernel_release set by full_install(build_only=True),
        # then fall back to reading kernel.release from the source tree
        kernel_release = self._kernel_manager._installer.last_kernel_release or ""
        if not kernel_release:
            release_file = os.path.join(build_dir, f"linux-{version}", "include", "config", "kernel.release")
            if os.path.exists(release_file):
                with open(release_file) as f:
                    kernel_release = f.read().strip()

        # Collect image + headers debs (exclude dbg and libc)
        # Filter by kernel_release when known; fall back to custom_name substring
        all_debs = glob.glob(os.path.join(build_dir, "*.deb"))
        debs = [
            f for f in all_debs
            if (
                "linux-image" in os.path.basename(f)
                or "linux-headers" in os.path.basename(f)
            )
            and (
                (kernel_release and f"-{kernel_release}" in os.path.basename(f))
                or (not kernel_release and custom_name in os.path.basename(f))
            )
            and "-dbg" not in os.path.basename(f)
        ]
        # Deduplicate
        debs = list(dict.fromkeys(debs))

        # Build metapackage .deb in a temp directory
        meta_deb_path = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                debian_dir = os.path.join(tmp, "DEBIAN")
                os.makedirs(debian_dir)
                display_name = self._soplos_pkg_display_name(pkg_name)
                short_desc = f"Soplos {display_name} kernel"
                control_content = (
                    f"Package: {pkg_name}\n"
                    f"Version: {version}\n"
                    f"Architecture: amd64\n"
                    f"Maintainer: Soplos Linux Team <info@soplos.org>\n"
                    f"Depends: linux-image-{kernel_release}, linux-headers-{kernel_release}\n"
                    f"Section: kernel\n"
                    f"Priority: optional\n"
                    f"Description: {short_desc}\n"
                    f" Installs the {kernel_release} kernel and its headers.\n"
                    f" When a new version is released, upgrading this package will\n"
                    f" automatically pull in the new kernel.\n"
                )
                with open(os.path.join(debian_dir, "control"), "w") as f:
                    f.write(control_content)
                meta_deb_path = os.path.join(build_dir, f"{pkg_name}_{version}_amd64.deb")
                result = subprocess.run(
                    ["dpkg-deb", "--root-owner-group", "--build", tmp, meta_deb_path],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    meta_deb_path = None
        except Exception as e:
            print(f"Error creating metapackage: {e}")
            meta_deb_path = None

        if meta_deb_path and os.path.exists(meta_deb_path):
            debs.append(meta_deb_path)

        if not debs:
            self._show_error(
                _("Build complete but no .deb packages were found.\n"
                  "Check the build log for details.")
            )
            return

        # Ask where to save all .deb files
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.NONE,
            text=_("Kernel build complete!")
        )
        pkg_list = "\n".join(f"  • {os.path.basename(d)}" for d in debs)
        dialog.format_secondary_text(
            _("The following packages are ready:\n\n%(pkgs)s\n\n"
              "Choose a folder to save them.")
            % {'pkgs': pkg_list}
        )
        dialog.add_button(_("Discard"), Gtk.ResponseType.NO)
        dialog.add_button(_("Save packages"), Gtk.ResponseType.YES)
        dialog.get_widget_for_response(Gtk.ResponseType.YES).get_style_context().add_class('suggested-action')
        resp = dialog.run()
        dialog.destroy()

        if resp != Gtk.ResponseType.YES:
            return

        chooser = Gtk.FileChooserDialog(
            title=_("Choose destination folder"),
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        chooser.add_button(_("Select"), Gtk.ResponseType.OK)
        chooser.set_current_folder(os.path.expanduser("~"))
        resp2 = chooser.run()
        dest_dir = chooser.get_filename()
        chooser.destroy()

        if resp2 != Gtk.ResponseType.OK or not dest_dir:
            return

        saved = 0
        for deb in debs:
            try:
                shutil.copy2(deb, dest_dir)
                saved += 1
            except Exception as e:
                print(f"Error copying {deb}: {e}")

        if saved:
            self._show_info(
                _("Saved {n} package(s) to:\n{path}").format(n=saved, path=dest_dir)
            )

    def _cleanup_after_install(self) -> None:
        build_dir = get_build_directory()
        debs = [
            f for f in glob.glob(os.path.join(build_dir, "**", "*.deb"), recursive=True)
            if "-dbg" not in os.path.basename(f)
        ]

        if debs:
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.NONE,
                text=_("Save .deb packages?")
            )
            dialog.format_secondary_text(
                _("The build directory contains %(n)d .deb package(s).\n"
                  "Do you want to save them before deleting the build directory?")
                % {'n': len(debs)}
            )
            dialog.add_button(_("Discard"), Gtk.ResponseType.NO)
            dialog.add_button(_("Save packages"), Gtk.ResponseType.YES)
            dialog.get_widget_for_response(Gtk.ResponseType.YES).get_style_context().add_class('suggested-action')
            resp = dialog.run()
            dialog.destroy()

            if resp == Gtk.ResponseType.YES:
                chooser = Gtk.FileChooserDialog(
                    title=_("Choose destination folder"),
                    transient_for=self,
                    action=Gtk.FileChooserAction.SELECT_FOLDER,
                )
                chooser.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
                chooser.add_button(_("Select"), Gtk.ResponseType.OK)
                chooser.set_current_folder(os.path.expanduser("~"))
                resp2 = chooser.run()
                dest_dir = chooser.get_filename()
                chooser.destroy()

                if resp2 == Gtk.ResponseType.OK and dest_dir:
                    saved = 0
                    for deb in debs:
                        try:
                            shutil.copy2(deb, dest_dir)
                            saved += 1
                        except Exception as e:
                            print(f"Error copying {deb}: {e}")

                    if saved:
                        self._show_info(
                            _("Saved {n} package(s) to:\n{path}").format(
                                n=saved, path=dest_dir
                            )
                        )

        if not self._kernel_manager.cleanup_build_files():
            self._show_error(_("Could not delete the build directory.\nCheck permissions or disk state."))

    def _ask_enroll_dkms_mok_post_install(self, dkms_pub: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Enroll DKMS signing key for NVIDIA?")
        )
        dialog.format_secondary_text(
            _("Installing the new kernel triggered an automatic rebuild of your NVIDIA modules (DKMS).\n\n"
              "These newly built modules must be signed to work with Secure Boot active. "
              "The DKMS signing key must be enrolled in the firmware so that "
              "NVIDIA modules (nvidia-uvm, NVENC, CUDA) load correctly.\n\n"
              "Without this step, NVENC and CUDA will not work after reboot.\n\n"
              "Do you want to enroll the DKMS key now?")
        )
        resp = dialog.run()
        dialog.destroy()
        if resp == Gtk.ResponseType.YES:
            self._prompt_and_enroll_mok(self, der_path=dkms_pub)
        else:
            self._ask_reboot()

    def _ask_reboot(self) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Installation complete!")
        )
        dialog.format_secondary_text(
            _("The kernel has been installed successfully.\n\n"
              "Do you want to reboot now to use the new kernel?")
        )
        resp = dialog.run()
        dialog.destroy()
        if resp == Gtk.ResponseType.YES:
            reboot_system()

    def _setup_shortcuts(self) -> None:
        accel = Gtk.AccelGroup()
        self.add_accel_group(accel)

        def bind(key, mask, cb):
            mod = getattr(Gdk.ModifierType, f'{mask}_MASK') if mask else 0
            keyval = Gdk.keyval_from_name(key)
            accel.connect(keyval, mod, Gtk.AccelFlags.VISIBLE, lambda *a: cb())

        bind('q', 'CONTROL', lambda: self.get_application().quit())
        bind('w', 'CONTROL', lambda: self.get_application().quit())
        bind('F5', None, self.refresh_versions)
        bind('F1', None, self._show_about)

        ctrl_shift = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        accel.connect(
            Gdk.keyval_from_name('d'),
            ctrl_shift,
            Gtk.AccelFlags.VISIBLE,
            lambda *a: self._activate_stock_profile()
        )

        self.connect('key-press-event', self._on_key_press)

    def _on_key_press(self, widget, event):
        keyval = event.keyval
        state = event.state

        if state & Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
                current_page = self._notebook.get_current_page()
                total_pages = self._notebook.get_n_pages()
                if state & Gdk.ModifierType.SHIFT_MASK:
                    self._notebook.set_current_page((current_page - 1) % total_pages)
                else:
                    self._notebook.set_current_page((current_page + 1) % total_pages)
                return True

        return False

    def _show_about(self) -> None:
        from pathlib import Path
        dialog = Gtk.AboutDialog()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_program_name(_("Soplos Kernel Installer"))
        dialog.set_version(VERSION)
        dialog.set_comments(
            _("Graphical interface for downloading, compiling and installing "
              "the Linux kernel with patches and optimized profiles on Soplos Linux.")
        )
        dialog.set_website("https://soplos.org")
        dialog.set_website_label("soplos.org")
        dialog.set_authors(["Sergi Perich <info@soploslinux.com>"])
        dialog.set_license_type(Gtk.License.GPL_3_0)
        icon_path = Path(__file__).parent.parent / 'assets' / 'icons' / '64x64' / 'org.soplos.kernel-installer.png'
        if icon_path.exists():
            dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_path), 48, 48, True))
        _about_css = Gtk.CssProvider()
        _about_css.load_from_data(b"""
            dialog, messagedialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            dialog .background, messagedialog .background {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            dialog > box, messagedialog > box {
                background-color: #2b2b2b;
            }
            dialog label, messagedialog label {
                color: #ffffff;
            }
            dialog button, messagedialog button {
                background-image: none;
                background-color: #333333;
                color: #ffffff;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                padding: 6px 14px;
                box-shadow: none;
            }
            dialog button:hover, messagedialog button:hover {
                background-color: #444444;
                border-color: #ff8800;
            }
            dialog stackswitcher button {
                border-radius: 100px;
                background-color: #2b2b2b;
                background-image: none;
                border: 1px solid #3c3c3c;
                font-weight: normal;
                padding: 4px 16px;
                box-shadow: none;
                color: #ffffff;
            }
            dialog stackswitcher button:hover {
                background-color: #444444;
                border-color: #ff8800;
            }
            dialog stackswitcher button:checked {
                background-color: #444444;
                color: #ffffff;
            }
            dialog scrolledwindow,
            dialog scrolledwindow viewport {
                background-color: #2b2b2b;
                border-radius: 0;
            }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), _about_css,
            Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        dialog.run()
        dialog.destroy()

    def _show_info(self, message: str) -> None:
        d = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text=message
        )
        d.run()
        d.destroy()

    def _show_error(self, message: str) -> None:
        d = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK, text=message
        )
        d.run()
        d.destroy()
