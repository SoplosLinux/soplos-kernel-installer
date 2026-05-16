"""
Secure Boot and MOK (Machine Owner Key) management for Soplos Linux.
"""

import os
import shutil
from pathlib import Path
from typing import Optional, List, Tuple
from utils.system import run_command, ensure_directory, run_privileged


class SecureBootManager:
    """Manages MOK keys and signing operations on Soplos Linux."""

    def __init__(self):
        self.config_dir = Path.home() / ".config" / "soplos-kernel-installer" / "keys"
        self.priv_key = self.config_dir / "MOK.priv"
        self.pem_key  = self.config_dir / "MOK.pem"
        self.der_key  = self.config_dir / "MOK.der"
        self.combined_key = self.config_dir / "MOK_combined.pem"

    def is_secure_boot_active(self) -> bool:
        if not shutil.which("mokutil"):
            return False
        res = run_command("mokutil --sb-state")
        return "SecureBoot enabled" in res.stdout

    def keys_exist(self) -> bool:
        return self.priv_key.exists() and self.der_key.exists()

    def generate_keys(self, name: str = "Soplos Kernel Key") -> bool:
        ensure_directory(str(self.config_dir))

        cmd = (
            f'openssl req -new -x509 -newkey rsa:2048 -keyout "{self.priv_key}" '
            f'-out "{self.pem_key}" -nodes -days 36500 -subj "/CN={name}/" '
            f'-addext "extendedKeyUsage=codeSigning" '
            f'-addext "basicConstraints=critical,CA:FALSE"'
        )
        if run_command(cmd).returncode != 0:
            # Fallback without addext
            cmd = (
                f'openssl req -new -x509 -newkey rsa:2048 -keyout "{self.priv_key}" '
                f'-out "{self.pem_key}" -nodes -days 36500 -subj "/CN={name}/"'
            )
            if run_command(cmd).returncode != 0:
                return False

        # PEM → DER for mokutil
        if run_command(
            f'openssl x509 -in "{self.pem_key}" -out "{self.der_key}" -outform DER'
        ).returncode != 0:
            return False

        # Combined key for kernel build (MODULE_SIG_KEY)
        try:
            self.combined_key.write_text(
                self.priv_key.read_text() + self.pem_key.read_text()
            )
        except Exception:
            return False

        return True

    def is_key_enrolled(self) -> bool:
        if not self.keys_exist() or not shutil.which("mokutil"):
            return False
        res = run_command(f'mokutil --test-key "{self.der_key}"')
        output = (res.stdout + res.stderr).lower()
        if "efi variables are not supported" in output:
            return False
        return "is already enrolled" in output

    def get_enroll_command(self) -> str:
        return f'pkexec mokutil --import "{self.der_key}"'

    DKMS_MOK_PUB = Path("/var/lib/dkms/mok.pub")

    def dkms_key_exists(self) -> bool:
        return self.DKMS_MOK_PUB.exists()

    def dkms_key_enrolled(self) -> bool:
        if not self.dkms_key_exists() or not shutil.which("mokutil"):
            return False
        res = run_command(f'mokutil --test-key "{self.DKMS_MOK_PUB}"')
        output = (res.stdout + res.stderr).lower()
        return "is already enrolled" in output

    def get_dkms_enroll_command(self) -> Optional[str]:
        """Return mokutil command to enroll the DKMS signing key, or None if not needed."""
        if not self.dkms_key_exists() or self.dkms_key_enrolled():
            return None
        return f'pkexec mokutil --import "{self.DKMS_MOK_PUB}"'

    def get_sign_command(self, file_path: str) -> Optional[str]:
        if not self.keys_exist():
            return None
        return (
            f'sbsign --key "{self.priv_key}" --cert "{self.pem_key}" '
            f'--output "{file_path}" "{file_path}"'
        )

    def sign_file(self, file_path: str) -> bool:
        """Sign a file (kernel image or EFI binary) with sbsign."""
        if not self.keys_exist() or not shutil.which("sbsign"):
            return False
        cmd = self.get_sign_command(file_path)
        return run_privileged(cmd).returncode == 0

    def get_key_paths(self) -> Tuple[str, str, str]:
        """Return (priv_key, pem_cert, combined_key)."""
        return str(self.priv_key), str(self.pem_key), str(self.combined_key)

    def delete_local_keys(self) -> bool:
        """Delete local key files. Note: does NOT revoke the key from UEFI MOK database.
        To fully remove an enrolled key, run: mokutil --delete <MOK.der>"""
        try:
            for p in [self.priv_key, self.pem_key, self.der_key, self.combined_key]:
                if p.exists():
                    p.unlink()
            return True
        except Exception:
            return False

    def get_delete_mok_command(self) -> Optional[str]:
        """Return the command to revoke the key from the UEFI MOK database."""
        if not self.der_key.exists():
            return None
        return f'pkexec mokutil --delete "{self.der_key}"'

    def get_signing_commands(self, kernel_release: str) -> List[str]:
        """
        Build list of shell commands to sign the kernel and GRUB EFI binaries.
        Returns empty list if keys or sbsign/sbverify are not available.
        """
        if not self.keys_exist():
            return []

        pem = str(self.pem_key)
        priv = str(self.priv_key)
        cmds = []

        # Sign kernel
        vmlinuz = f"/boot/vmlinuz-{kernel_release}"
        cmds.append(
            f'if [ -f "{vmlinuz}" ]; then '
            f'  if ! sbverify --cert "{pem}" "{vmlinuz}" 2>/dev/null; then '
            f'    echo "Signing {vmlinuz}..." && '
            f'    sbsign --key "{priv}" --cert "{pem}" '
            f'      --output "{vmlinuz}" "{vmlinuz}"; '
            f'  else echo "{vmlinuz} already signed."; fi; '
            f'fi'
        )

        # Sign GRUB EFI binary if present
        for grub_efi in [
            "/boot/efi/EFI/soplos/grubx64.efi",
            "/boot/efi/EFI/debian/grubx64.efi",
        ]:
            cmds.append(
                f'if [ -f "{grub_efi}" ]; then '
                f'  if ! sbverify --cert "{pem}" "{grub_efi}" 2>/dev/null; then '
                f'    echo "Signing {grub_efi}..." && '
                f'    sbsign --key "{priv}" --cert "{pem}" '
                f'      --output "{grub_efi}" "{grub_efi}"; '
                f'  fi; '
                f'fi'
            )

        return cmds
