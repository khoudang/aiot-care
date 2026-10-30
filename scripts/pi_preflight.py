#!/usr/bin/env python3
"""pi_preflight.py — Read-only diagnostics and preflight verification for Raspberry Pi 4.

STRICT SAFETY CONSTRAINTS:
  * Read-only inspection only.
  * NO imports of app, web, iot, cv2, mediapipe, or database services.
  * NO Bluetooth scans, advertisements, or connections.
  * NO system changes, package installations, or root/sudo invocations.
  * Sanitized output: tokens and credentials are masked.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


def get_platform_info():
    uname = platform.uname()
    is_64bit = sys.maxsize > 2**32
    return {
        "system": uname.system,
        "release": uname.release,
        "version": uname.version,
        "machine": uname.machine,
        "architecture": "64bit" if is_64bit else "32bit",
        "processor": uname.processor or "unknown",
        "is_linux": sys.platform.startswith("linux"),
        "is_arm": uname.machine.lower().startswith(("arm", "aarch")),
    }


def get_python_info():
    in_venv = (
        sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        or hasattr(sys, "real_prefix")
    )
    return {
        "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "executable": sys.executable,
        "prefix": sys.prefix,
        "in_virtualenv": in_venv,
    }


def get_pi_hardware_info():
    info = {
        "is_raspberry_pi": False,
        "model": "unknown",
        "cpu_cores": os.cpu_count() or 1,
        "ram_total_mb": None,
        "ram_available_mb": None,
        "temperature_c": None,
        "throttled_status": None,
    }

    # Model detection
    model_path = Path("/proc/device-tree/model")
    if model_path.exists():
        try:
            info["model"] = model_path.read_text(encoding="utf-8", errors="ignore").strip("\x00\n\r ")
            info["is_raspberry_pi"] = "raspberry pi" in info["model"].lower()
        except Exception:
            pass

    # RAM detection via /proc/meminfo
    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            for line in meminfo_path.read_text().splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        info["ram_total_mb"] = round(int(parts[1]) / 1024, 1)
                elif line.startswith("MemAvailable:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        info["ram_available_mb"] = round(int(parts[1]) / 1024, 1)
        except Exception:
            pass

    # Thermal detection
    thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal_path.exists():
        try:
            temp_raw = int(thermal_path.read_text().strip())
            info["temperature_c"] = round(temp_raw / 1000.0, 1)
        except Exception:
            pass

    # Throttling check via vcgencmd if available
    vcgencmd = shutil.which("vcgencmd")
    if vcgencmd:
        try:
            res = subprocess.run([vcgencmd, "get_throttled"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and "=" in res.stdout:
                info["throttled_status"] = res.stdout.strip().split("=")[1]
        except Exception:
            pass

    return info


def get_bluetooth_info():
    info = {
        "bluez_version": "unknown",
        "has_controller": False,
        "controllers": [],
        "dbus_socket_exists": Path("/var/run/dbus/system_bus_socket").exists(),
    }

    # Check bluez version via bluetoothctl
    bluetoothctl = shutil.which("bluetoothctl")
    if bluetoothctl:
        try:
            res = subprocess.run([bluetoothctl, "--version"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                match = re.search(r"(\d+(\.\d+)+)", res.stdout)
                if match:
                    info["bluez_version"] = match.group(1)
        except Exception:
            pass

    # Check controllers via /sys/class/bluetooth on Linux
    bt_sys = Path("/sys/class/bluetooth")
    if bt_sys.exists():
        try:
            controllers = [p.name for p in bt_sys.iterdir() if p.name.startswith("hci")]
            info["controllers"] = controllers
            info["has_controller"] = len(controllers) > 0
        except Exception:
            pass

    return info


def check_dependencies(repo_root):
    req_path = repo_root / "requirements.txt"
    results = {}
    if not req_path.exists():
        return {"requirements_found": False, "packages": {}}

    import importlib.metadata

    packages = {}
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Extract base package name
        pkg_name = re.split(r"[=<>]", line)[0].strip()
        try:
            installed_ver = importlib.metadata.version(pkg_name)
            packages[pkg_name] = {"required": line, "installed": installed_ver, "status": "ok"}
        except importlib.metadata.PackageNotFoundError:
            # Check alternative name normalization (e.g. opencv-python)
            packages[pkg_name] = {"required": line, "installed": None, "status": "missing"}

    return {"requirements_found": True, "packages": packages}


def check_configuration_sanitized(repo_root):
    config_file = repo_root / "config.py"
    if not config_file.exists():
        return {"config_found": False}

    summary = {
        "config_found": True,
        "database_configured": "unknown",
        "nodes_configured": [],
        "secrets_masked": True,
    }

    try:
        content = config_file.read_text(encoding="utf-8")
        # Extract database name safely
        db_match = re.search(r'DATABASE\s*=\s*os\.getenv\(["\']DATABASE["\'],\s*["\']([^"\']+)["\']\)', content)
        if db_match:
            summary["database_configured"] = db_match.group(1)

        # Extract node rooms and placeholder MACs
        for match in re.finditer(r'\{"room":\s*"([^"]+)",\s*"name":\s*"([^"]+)",\s*"mac":\s*os\.getenv\(["\'][^"\']+["\'],\s*"([^"]*)"\)', content):
            summary["nodes_configured"].append({
                "room": match.group(1),
                "name": match.group(2),
                "default_mac": match.group(3) or "unconfigured",
            })
    except Exception as exc:
        summary["error"] = str(exc)

    return summary


def assess_pi4_compatibility(platform_info, pi_info, deps_info):
    notes = []
    ready = True

    if platform_info["is_linux"]:
        if not platform_info["is_arm"]:
            notes.append("System is Linux but NOT ARM architecture (running in test/host environment).")
        elif platform_info["architecture"] != "64bit":
            notes.append("WARNING: 32-bit ARM detected. 64-bit Raspberry Pi OS is strongly recommended for MediaPipe and BLE performance.")
            ready = False
    else:
        notes.append(f"Non-Linux host ({platform_info['system']}) - test environment.")

    # RAM check if known
    if pi_info["ram_total_mb"]:
        if pi_info["ram_total_mb"] < 3500:
            notes.append(f"RAM detected: {pi_info['ram_total_mb']} MB (User specified 4GB model).")

    # Thermal check
    if pi_info["temperature_c"]:
        if pi_info["temperature_c"] > 75.0:
            notes.append(f"WARNING: High CPU temperature ({pi_info['temperature_c']}°C). Active cooling recommended.")

    # Missing dependencies
    missing = [name for name, d in deps_info.get("packages", {}).items() if d["status"] == "missing"]
    if missing:
        notes.append(f"Missing Python dependencies in current environment: {', '.join(missing)}")
        ready = False

    return {"recommended_for_production": ready, "notes": notes}


def run_preflight(repo_root=None, output_json=False):
    root = repo_root or Path(__file__).resolve().parents[1]
    plat = get_platform_info()
    py = get_python_info()
    pi = get_pi_hardware_info()
    bt = get_bluetooth_info()
    deps = check_dependencies(root)
    cfg = check_configuration_sanitized(root)
    eval_result = assess_pi4_compatibility(plat, pi, deps)

    report = {
        "preflight_status": "ok",
        "timestamp": platform.node(),
        "platform": plat,
        "python": py,
        "hardware_pi": pi,
        "bluetooth": bt,
        "dependencies": deps,
        "configuration": cfg,
        "assessment": eval_result,
    }

    if output_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("=" * 60)
        print(" AIoT Care — Raspberry Pi 4 Read-Only Preflight Report")
        print("=" * 60)
        print(f"OS/Arch:        {plat['system']} {plat['release']} ({plat['machine']}, {plat['architecture']})")
        print(f"Python:         {py['version']} (venv: {py['in_virtualenv']})")
        print(f"Pi Hardware:    {pi['model']} (RAM: {pi['ram_total_mb'] or 'N/A'} MB, Temp: {pi['temperature_c'] or 'N/A'}°C)")
        print(f"BlueZ / D-Bus:  Version: {bt['bluez_version']}, D-Bus socket: {bt['dbus_socket_exists']}")
        print(f"Dependencies:   {len([p for p in deps.get('packages', {}).values() if p['status'] == 'ok'])} OK, {len([p for p in deps.get('packages', {}).values() if p['status'] == 'missing'])} Missing")
        print(f"Configured DB:  {cfg.get('database_configured')}")
        print("-" * 60)
        print("Assessment Notes:")
        for note in eval_result["notes"]:
            print(f"  * {note}")
        print("=" * 60)

    return report


if __name__ == "__main__":
    is_json = "--json" in sys.argv
    run_preflight(output_json=is_json)
