from setuptools import setup, find_packages
from pathlib import Path

setup(
    name="soplos-kernel-installer",
    version="1.0.0",
    description="Soplos Linux Kernel Installer with patches and optimized profiles",
    author="Sergi Perich",
    author_email="info@soploslinux.com",
    url="https://github.com/SoplosLinux/soplos-kernel-installer",
    license="GPL-3.0",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.9",
    install_requires=[
        "PyGObject>=3.42",
    ],
    data_files=[
        ("share/applications", ["debian/org.soplos.kernel-installer.desktop"]),
        ("share/metainfo", ["debian/org.soplos.kernel-installer.metainfo.xml"]),
        ("share/soplos-kernel-installer/themes", ["assets/themes/base.css", "assets/themes/dark.css", "assets/themes/light.css"]),
        ("share/icons/hicolor/48x48/apps", ["assets/icons/48x48/org.soplos.kernel-installer.png"]),
        ("share/icons/hicolor/64x64/apps", ["assets/icons/64x64/org.soplos.kernel-installer.png"]),
        ("share/icons/hicolor/128x128/apps", ["assets/icons/128x128/org.soplos.kernel-installer.png"]),
        ("share/man/man1", ["docs/soplos-kernel-installer.1"]),
        # Locales
        ("share/locale/de/LC_MESSAGES", ["locale/de/LC_MESSAGES/soplos-kernel-installer.mo"]),
        ("share/locale/en/LC_MESSAGES", ["locale/en/LC_MESSAGES/soplos-kernel-installer.mo"]),
        ("share/locale/es/LC_MESSAGES", ["locale/es/LC_MESSAGES/soplos-kernel-installer.mo"]),
        ("share/locale/fr/LC_MESSAGES", ["locale/fr/LC_MESSAGES/soplos-kernel-installer.mo"]),
        ("share/locale/it/LC_MESSAGES", ["locale/it/LC_MESSAGES/soplos-kernel-installer.mo"]),
        ("share/locale/pt/LC_MESSAGES", ["locale/pt/LC_MESSAGES/soplos-kernel-installer.mo"]),
        ("share/locale/ro/LC_MESSAGES", ["locale/ro/LC_MESSAGES/soplos-kernel-installer.mo"]),
        ("share/locale/ru/LC_MESSAGES", ["locale/ru/LC_MESSAGES/soplos-kernel-installer.mo"]),
    ],
    scripts=["debian/soplos-kernel-installer"],
)
