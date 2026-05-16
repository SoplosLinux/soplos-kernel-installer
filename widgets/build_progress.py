"""
Build progress widget — shows compilation progress and system stats.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, GObject

from utils.system import (
    get_load_average, get_cpu_count, get_memory_info,
    get_disk_info, get_cpu_temp, get_thread_count, get_physical_core_count
)
from core.i18n_manager import _


class BuildProgress(Gtk.Box):

    __gsignals__ = {
        'build-cancelled': (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    MAX_LOG_LINES = 5000

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        self._is_building = False
        self._load_timer_id = None
        self._clock_timer_id = None
        self._log_timer_id = None
        self._log_file_handle = None
        self._start_time = 0
        self._cpu_count = get_cpu_count()          # logical threads (for load %)
        self._physical_cores = get_physical_core_count()
        self._thread_count = get_thread_count()

        # Paned: log left, stats right
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)

        # === Left: Log view ===
        log_frame = Gtk.Frame()
        log_frame.set_shadow_type(Gtk.ShadowType.IN)

        self._log_scroll = Gtk.ScrolledWindow()
        self._log_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._log_scroll.set_min_content_height(300)

        adj = self._log_scroll.get_vadjustment()
        adj.connect("changed", self._on_vadj_changed)

        self._log_view = Gtk.TextView()
        self._log_view.set_editable(False)
        self._log_view.set_cursor_visible(False)
        self._log_view.set_monospace(True)
        self._log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._log_buffer = self._log_view.get_buffer()

        self._log_scroll.add(self._log_view)
        log_frame.add(self._log_scroll)
        paned.pack1(log_frame, resize=True, shrink=False)

        # === Right: Stats panel ===
        stats_scroll = Gtk.ScrolledWindow()
        stats_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        stats_scroll.set_size_request(200, -1)

        stats_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        stats_box.set_margin_start(12)
        stats_box.set_margin_end(8)
        stats_box.set_margin_top(8)
        stats_box.set_margin_bottom(8)

        # === CPU LOAD ===
        cpu_header = Gtk.Label(label=_("CPU LOAD"))
        cpu_header.get_style_context().add_class('section-header')
        cpu_header.set_halign(Gtk.Align.START)
        stats_box.pack_start(cpu_header, False, False, 0)

        load_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._load_bar = Gtk.LevelBar()
        self._load_bar.set_min_value(0)
        self._load_bar.set_max_value(100)
        self._load_bar.add_offset_value("low", 35)
        self._load_bar.add_offset_value("high", 70)
        self._load_bar.add_offset_value("full", 100)
        self._load_bar.set_hexpand(True)
        load_box.pack_start(self._load_bar, True, True, 0)

        self._load_label = Gtk.Label(label="0%")
        self._load_label.set_width_chars(5)
        self._load_label.get_style_context().add_class('dim-label')
        load_box.pack_start(self._load_label, False, False, 0)
        stats_box.pack_start(load_box, False, False, 0)

        # Load averages grid (1m / 5m / 15m)
        avg_grid = Gtk.Grid()
        avg_grid.set_column_spacing(8)
        avg_grid.set_row_spacing(4)
        avg_grid.set_margin_top(4)

        self._load_1m_label = Gtk.Label(label="1m:")
        self._load_1m_label.set_halign(Gtk.Align.START)
        avg_grid.attach(self._load_1m_label, 0, 0, 1, 1)
        self._load_1m_bar = Gtk.LevelBar()
        self._load_1m_bar.set_min_value(0)
        self._load_1m_bar.set_max_value(100)
        self._load_1m_bar.set_hexpand(True)
        avg_grid.attach(self._load_1m_bar, 1, 0, 1, 1)
        self._load_1m_val = Gtk.Label(label="0.00")
        self._load_1m_val.set_width_chars(5)
        avg_grid.attach(self._load_1m_val, 2, 0, 1, 1)

        self._load_5m_label = Gtk.Label(label="5m:")
        self._load_5m_label.set_halign(Gtk.Align.START)
        avg_grid.attach(self._load_5m_label, 0, 1, 1, 1)
        self._load_5m_bar = Gtk.LevelBar()
        self._load_5m_bar.set_min_value(0)
        self._load_5m_bar.set_max_value(100)
        self._load_5m_bar.set_hexpand(True)
        avg_grid.attach(self._load_5m_bar, 1, 1, 1, 1)
        self._load_5m_val = Gtk.Label(label="0.00")
        self._load_5m_val.set_width_chars(5)
        avg_grid.attach(self._load_5m_val, 2, 1, 1, 1)

        self._load_15m_label = Gtk.Label(label="15m:")
        self._load_15m_label.set_halign(Gtk.Align.START)
        avg_grid.attach(self._load_15m_label, 0, 2, 1, 1)
        self._load_15m_bar = Gtk.LevelBar()
        self._load_15m_bar.set_min_value(0)
        self._load_15m_bar.set_max_value(100)
        self._load_15m_bar.set_hexpand(True)
        avg_grid.attach(self._load_15m_bar, 1, 2, 1, 1)
        self._load_15m_val = Gtk.Label(label="0.00")
        self._load_15m_val.set_width_chars(5)
        avg_grid.attach(self._load_15m_val, 2, 2, 1, 1)

        stats_box.pack_start(avg_grid, False, False, 0)
        stats_box.pack_start(Gtk.Separator(), False, False, 4)

        # === MEMORY ===
        mem_header = Gtk.Label(label=_("MEMORY"))
        mem_header.get_style_context().add_class('section-header')
        mem_header.set_halign(Gtk.Align.START)
        stats_box.pack_start(mem_header, False, False, 0)

        mem_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._mem_bar = Gtk.LevelBar()
        self._mem_bar.set_min_value(0)
        self._mem_bar.set_max_value(100)
        self._mem_bar.add_offset_value("low", 50)
        self._mem_bar.add_offset_value("high", 80)
        self._mem_bar.add_offset_value("full", 100)
        self._mem_bar.set_hexpand(True)
        mem_box.pack_start(self._mem_bar, True, True, 0)

        self._mem_percent = Gtk.Label(label="0%")
        self._mem_percent.set_width_chars(5)
        mem_box.pack_start(self._mem_percent, False, False, 0)
        stats_box.pack_start(mem_box, False, False, 0)

        self._mem_detail = Gtk.Label(label="0.0 / 0.0 GB")
        self._mem_detail.set_halign(Gtk.Align.START)
        self._mem_detail.get_style_context().add_class('dim-label')
        stats_box.pack_start(self._mem_detail, False, False, 0)
        stats_box.pack_start(Gtk.Separator(), False, False, 4)

        # === DISK ===
        disk_header = Gtk.Label(label=_("DISK (Build)"))
        disk_header.get_style_context().add_class('section-header')
        disk_header.set_halign(Gtk.Align.START)
        stats_box.pack_start(disk_header, False, False, 0)

        disk_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._disk_bar = Gtk.LevelBar()
        self._disk_bar.set_min_value(0)
        self._disk_bar.set_max_value(100)
        self._disk_bar.add_offset_value("low", 60)
        self._disk_bar.add_offset_value("high", 85)
        self._disk_bar.add_offset_value("full", 100)
        self._disk_bar.set_hexpand(True)
        disk_box.pack_start(self._disk_bar, True, True, 0)

        self._disk_percent = Gtk.Label(label="0%")
        self._disk_percent.set_width_chars(5)
        disk_box.pack_start(self._disk_percent, False, False, 0)
        stats_box.pack_start(disk_box, False, False, 0)

        self._disk_detail = Gtk.Label(label=_("Free:") + " 0.0 GB")
        self._disk_detail.set_halign(Gtk.Align.START)
        self._disk_detail.get_style_context().add_class('dim-label')
        stats_box.pack_start(self._disk_detail, False, False, 0)
        stats_box.pack_start(Gtk.Separator(), False, False, 4)

        # === CPU TEMP ===
        temp_header = Gtk.Label(label=_("CPU TEMP"))
        temp_header.get_style_context().add_class('section-header')
        temp_header.set_halign(Gtk.Align.START)
        stats_box.pack_start(temp_header, False, False, 0)

        temp_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._temp_bar = Gtk.LevelBar()
        self._temp_bar.set_min_value(0)
        self._temp_bar.set_max_value(100)
        self._temp_bar.add_offset_value("low", 50)
        self._temp_bar.add_offset_value("high", 75)
        self._temp_bar.add_offset_value("full", 95)
        self._temp_bar.set_hexpand(True)
        temp_box.pack_start(self._temp_bar, True, True, 0)

        self._temp_label = Gtk.Label(label="--°C")
        self._temp_label.set_width_chars(5)
        temp_box.pack_start(self._temp_label, False, False, 0)
        stats_box.pack_start(temp_box, False, False, 0)
        stats_box.pack_start(Gtk.Separator(), False, False, 4)

        # === CPU INFO (cores / threads) ===
        cpu_info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        cores_label = Gtk.Label(label=_("Cores:") + f" {self._physical_cores}")
        cores_label.set_halign(Gtk.Align.START)
        cpu_info_box.pack_start(cores_label, False, False, 0)
        threads_label = Gtk.Label(label=_("Threads:") + f" {self._thread_count}")
        threads_label.set_halign(Gtk.Align.START)
        cpu_info_box.pack_start(threads_label, False, False, 0)
        stats_box.pack_start(cpu_info_box, False, False, 0)

        stats_box.pack_start(Gtk.Box(), True, True, 0)

        stats_scroll.add(stats_box)
        paned.pack2(stats_scroll, resize=False, shrink=False)

        self.pack_start(paned, True, True, 0)

        # === Bottom: elapsed time ===
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        bottom_box.set_margin_top(4)
        bottom_box.set_margin_end(15)
        bottom_box.set_hexpand(True)

        self._time_label = Gtk.Label(label="")
        self._time_label.set_halign(Gtk.Align.END)
        self._time_label.get_style_context().add_class('dim-label')
        bottom_box.pack_end(self._time_label, True, True, 0)

        self.pack_start(bottom_box, False, False, 0)
        self.show_all()

    # ------------------------------------------------------------------
    # Build lifecycle
    # ------------------------------------------------------------------

    def start_build(self) -> None:
        self._is_building = True
        self._log_buffer.set_text("")
        self._start_time = GLib.get_monotonic_time()

        self._clock_timer_id = GLib.timeout_add(1000, self._update_clock)
        self._update_clock()

        self._load_timer_id = GLib.timeout_add(2000, self._update_stats)
        self._update_stats()

    def stop_build(self) -> None:
        self._is_building = False
        if self._load_timer_id:
            GLib.source_remove(self._load_timer_id)
            self._load_timer_id = None
        if self._clock_timer_id:
            GLib.source_remove(self._clock_timer_id)
            self._clock_timer_id = None

    def set_complete(self, success: bool, cancelled: bool = False) -> None:
        self.stop_build()
        self.stop_monitoring()
        current = self._time_label.get_text()
        if cancelled:
            self._time_label.set_text(current + " (" + _("Cancelled") + ")")
        elif not success:
            self._time_label.set_text(current + " (" + _("Failed") + ")")

    def update_progress(self, message: str, percent: int) -> None:
        """Called from main window — progress is shown in the footer revealer there."""
        pass

    # ------------------------------------------------------------------
    # Log file monitoring
    # ------------------------------------------------------------------

    def monitor_log_file(self, path: str) -> None:
        if self._log_timer_id:
            return
        try:
            self._log_file_handle = open(path, 'r', errors='replace')
            self._log_timer_id = GLib.timeout_add(100, self._check_log_file)
        except Exception as e:
            self.append_log(_("Error opening log file: {}").format(e))

    def _check_log_file(self) -> bool:
        try:
            if not self._log_file_handle:
                return False

            lines = []
            for _ in range(1000):
                line = self._log_file_handle.readline()
                if not line:
                    break
                lines.append(line.rstrip())

            if lines:
                text = "\n".join(lines)
                self._do_append_log(text)
                self.scroll_to_bottom()

            return True
        except Exception:
            return True

    def stop_monitoring(self) -> None:
        if self._log_timer_id:
            GLib.source_remove(self._log_timer_id)
            self._log_timer_id = None
        if self._log_file_handle:
            try:
                self._log_file_handle.close()
            except Exception:
                pass
            self._log_file_handle = None

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def append_log(self, text: str) -> None:
        GLib.idle_add(self._do_append_log, text)

    def _do_append_log(self, text: str) -> None:
        self._log_buffer.insert(self._log_buffer.get_end_iter(), text + "\n")
        line_count = self._log_buffer.get_line_count()
        if line_count > self.MAX_LOG_LINES:
            start_iter = self._log_buffer.get_start_iter()
            delete_to = self._log_buffer.get_iter_at_line(line_count - self.MAX_LOG_LINES)
            self._log_buffer.delete(start_iter, delete_to)

    def scroll_to_bottom(self) -> None:
        adj = self._log_scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def _on_vadj_changed(self, adj) -> None:
        if self._is_building:
            adj.set_value(adj.get_upper() - adj.get_page_size())

    # ------------------------------------------------------------------
    # Stats timers
    # ------------------------------------------------------------------

    def _update_clock(self) -> bool:
        if not self._is_building:
            return False
        elapsed = (GLib.get_monotonic_time() - self._start_time) / 1_000_000
        h = int(elapsed) // 3600
        m = (int(elapsed) % 3600) // 60
        s = int(elapsed) % 60
        self._time_label.set_text(_("Time:") + f" {h:02d}:{m:02d}:{s:02d}")
        return True

    def _update_stats(self) -> bool:
        if not self._is_building:
            return False

        # CPU load
        load1, load5, load15 = get_load_average()
        usage = min((load1 / self._cpu_count) * 100, 100)
        self._load_bar.set_value(usage)
        self._load_label.set_text(f"{usage:.1f}%")

        load1_pct = min((load1 / self._cpu_count) * 100, 100)
        load5_pct = min((load5 / self._cpu_count) * 100, 100)
        load15_pct = min((load15 / self._cpu_count) * 100, 100)

        self._load_1m_bar.set_value(load1_pct)
        self._load_1m_val.set_text(f"{load1:.2f}")
        self._load_5m_bar.set_value(load5_pct)
        self._load_5m_val.set_text(f"{load5:.2f}")
        self._load_15m_bar.set_value(load15_pct)
        self._load_15m_val.set_text(f"{load15:.2f}")

        # Memory
        mem_used, mem_total, mem_pct = get_memory_info()
        self._mem_bar.set_value(mem_pct)
        self._mem_percent.set_text(f"{mem_pct:.0f}%")
        self._mem_detail.set_text(f"{mem_used:.1f} / {mem_total:.1f} GB")

        # Disk
        disk_free, disk_total, disk_pct = get_disk_info()
        self._disk_bar.set_value(disk_pct)
        self._disk_percent.set_text(f"{disk_pct:.0f}%")
        self._disk_detail.set_text(_("Free:") + f" {disk_free:.1f} GB")

        # Temperature
        temp = get_cpu_temp()
        if temp > 0:
            self._temp_bar.set_value(min(temp, 100))
            self._temp_label.set_text(f"{temp:.0f}°C")
        else:
            self._temp_bar.set_value(0)
            self._temp_label.set_text("--°C")

        return True
