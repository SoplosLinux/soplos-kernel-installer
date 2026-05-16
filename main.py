#!/usr/bin/env python3
"""
Soplos Kernel Installer - Launcher
Copyright (C) 2026 Sergi Perich <info@soploslinux.com>
"""

import sys
import os
import signal
import atexit
import shutil
import argparse


def cleanup_pycache():
    try:
        curr_file = globals().get('__file__') or sys.argv[0]
        base_dir = os.path.dirname(os.path.abspath(curr_file))
        for root, dirs, _ in os.walk(base_dir):
            if "__pycache__" in dirs:
                try:
                    shutil.rmtree(os.path.join(root, "__pycache__"))
                except Exception:
                    pass
    except Exception:
        pass

atexit.register(cleanup_pycache)


def signal_handler(sig, frame):
    cleanup_pycache()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import GLib, Gdk, Gtk

GLib.set_prgname('org.soplos.kernel-installer')
GLib.set_application_name('Soplos Kernel Installer')
if hasattr(Gdk, 'set_program_class'):
    Gdk.set_program_class('org.soplos.kernel-installer')
Gtk.Window.set_default_icon_name('org.soplos.kernel-installer')

from app import SoplosKernelInstallerApp


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Soplos Kernel Installer")
    parser.add_argument("--force", action="store_true",
                        help="Force a new instance")
    args, unknown = parser.parse_known_args()

    try:
        application = SoplosKernelInstallerApp(force_new=args.force)
        status = application.run([sys.argv[0]] + unknown)
        sys.exit(status)
    except Exception as e:
        print(f"CRITICAL ERROR: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
