"""
System command execution utilities for Soplos Kernel Installer.
"""

import subprocess
import shlex
import os
import shutil
import signal
import sys
from dataclasses import dataclass
from typing import Optional, Callable


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def get_cpu_count() -> int:
    """Returns number of logical processors (threads) — used for make -j."""
    return os.cpu_count() or 1


def get_physical_core_count() -> int:
    """Returns number of physical CPU cores (not hyperthreading threads)."""
    try:
        cores: set = set()
        physical_id = "0"
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('physical id'):
                    physical_id = line.split(':', 1)[1].strip()
                elif line.startswith('core id'):
                    core_id = line.split(':', 1)[1].strip()
                    cores.add((physical_id, core_id))
        return len(cores) if cores else os.cpu_count() or 1
    except Exception:
        return os.cpu_count() or 1


def get_thread_count() -> int:
    """Returns number of logical processors (hardware threads)."""
    return os.cpu_count() or 1


def get_home_directory() -> str:
    return os.path.expanduser('~')


def get_build_directory() -> str:
    return os.path.join(get_home_directory(), 'kernel_build')


def ensure_directory(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


def run_command(command: str, cwd: Optional[str] = None) -> CommandResult:
    try:
        process = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=cwd
        )
        stdout, stderr = process.communicate()
        return CommandResult(process.returncode, stdout.strip(), stderr.strip())
    except Exception as e:
        return CommandResult(1, "", str(e))


def run_command_with_callback(cmd: str, cwd: Optional[str] = None,
                               line_callback: Optional[Callable[[str], None]] = None,
                               stop_check: Optional[Callable[[], bool]] = None) -> int:
    log_path = os.path.join(get_build_directory(), 'build.log')
    ensure_directory(os.path.dirname(log_path))

    process = subprocess.Popen(
        cmd, shell=True, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
        preexec_fn=os.setsid if os.name != 'nt' else None
    )

    try:
        with open(log_path, 'a') as log_file:
            log_file.write(f"\n--- Running: {cmd} ---\n")
            log_file.flush()

            for line in iter(process.stdout.readline, ''):
                if stop_check and stop_check():
                    if os.name != 'nt':
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    else:
                        process.terminate()
                    log_file.write("\n!!! CANCELLED !!!\n")
                    return -1

                line = line.rstrip('\n')
                print(line, file=sys.stderr, flush=True)
                log_file.write(line + '\n')
                log_file.flush()

                if line_callback:
                    line_callback(line)

        process.wait()
        return process.returncode
    except Exception as e:
        print(f"Error running command: {e}", file=sys.stderr)
        return 1


def run_privileged(command: str) -> CommandResult:
    if os.geteuid() == 0:
        return run_command(command)
    if shutil.which("pkexec"):
        return run_command(f"pkexec /bin/sh -c {shlex.quote(command)}")
    return run_command(f"sudo /bin/sh -c {shlex.quote(command)}")


def run_privileged_with_callback(cmd: str,
                                  line_callback: Optional[Callable[[str], None]] = None,
                                  stop_check: Optional[Callable[[], bool]] = None) -> int:
    if shutil.which('pkexec'):
        full_cmd = f"pkexec /bin/sh -c {shlex.quote(cmd)}"
    else:
        full_cmd = f"sudo /bin/sh -c {shlex.quote(cmd)}"
    return run_command_with_callback(full_cmd, line_callback=line_callback,
                                     stop_check=stop_check)


def reboot_system() -> bool:
    import subprocess
    cmd = ['systemctl', 'reboot'] if shutil.which('systemctl') else ['reboot']
    result = subprocess.run(cmd, check=False)
    return result.returncode == 0


def get_load_average() -> tuple:
    try:
        with open('/proc/loadavg', 'r') as f:
            parts = f.read().split()
            return (float(parts[0]), float(parts[1]), float(parts[2]))
    except Exception:
        return (0.0, 0.0, 0.0)


def get_memory_info() -> tuple:
    try:
        with open('/proc/meminfo', 'r') as f:
            meminfo = {line.split()[0].rstrip(':'): int(line.split()[1]) for line in f}
        total = meminfo.get('MemTotal', 0)
        available = meminfo.get('MemAvailable', meminfo.get('MemFree', 0))
        used = total - available
        return (used / 1048576, total / 1048576, (used / total * 100) if total > 0 else 0)
    except Exception:
        return (0.0, 0.0, 0.0)


def get_disk_info(path: Optional[str] = None) -> tuple:
    if path is None:
        path = get_build_directory()
    try:
        if not os.path.exists(path):
            path = get_home_directory()
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        used = total - free
        return (free / 1073741824, total / 1073741824, (used / total * 100) if total > 0 else 0)
    except Exception:
        return (0.0, 0.0, 0.0)


def get_cpu_temp() -> float:
    hwmon_base = '/sys/class/hwmon'
    if os.path.exists(hwmon_base):
        for hwmon in os.listdir(hwmon_base):
            path = os.path.join(hwmon_base, hwmon)
            try:
                with open(os.path.join(path, "name"), "r") as f:
                    if f.read().strip() in ('coretemp', 'k10temp', 'acpitz'):
                        for entry in os.listdir(path):
                            if entry.startswith('temp') and entry.endswith('_input'):
                                with open(os.path.join(path, entry), 'r') as tf:
                                    return int(tf.read().strip()) / 1000
            except Exception:
                pass
    return -1.0
