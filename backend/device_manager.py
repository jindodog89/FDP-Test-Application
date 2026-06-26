"""
Device Manager — discovers NVMe devices and constructs the appropriate driver.

Dummy device support
--------------------
Two virtual devices are always prepended to the device list for offline
debugging (no physical NVMe hardware required):

  /dev/nvme-dummy-fdp-on   — simulates an FDP-capable, FDP-enabled drive
  /dev/nvme-dummy-fdp-off  — simulates a drive with FDP disabled

All driver calls against these paths are intercepted by DummyNVMeDriver
and return realistic canned responses — nothing touches the kernel.
"""

import subprocess
import json
import glob
import re
import os
import sys

# ── driver imports ────────────────────────────────────────────────────────────

def _get_nvme_cli_driver():
    from backend.drivers.nvme_cli_driver import NVMeCliDriver
    return NVMeCliDriver


def _get_dummy_driver():
    """Import DummyNVMeDriver and the sentinel path constants."""
    try:
        from backend.drivers.dummy_driver import (
            DummyNVMeDriver,
            DUMMY_FDP_ON,
            DUMMY_FDP_OFF,
            DUMMY_DEVICES,
        )
        return DummyNVMeDriver, DUMMY_FDP_ON, DUMMY_FDP_OFF, DUMMY_DEVICES
    except ImportError:
        return None, None, None, set()


# Resolve dummy constants at module load so the rest of the file can use them
_DummyNVMeDriver, DUMMY_FDP_ON, DUMMY_FDP_OFF, DUMMY_DEVICES = _get_dummy_driver()

# ── static metadata for the dummy entries ────────────────────────────────────

_DUMMY_DEVICE_LIST = []
if _DummyNVMeDriver is not None:
    _DUMMY_DEVICE_LIST = [
        {
            "path":     DUMMY_FDP_ON,
            "model":    "[DUMMY] FDP-Enabled SSD",
            "serial":   "DUMMY-FDP-ON",
            "firmware": "1.0.0",
            "size_gb":  256.0,
            "dummy":    True,
        },
        {
            "path":     DUMMY_FDP_OFF,
            "model":    "[DUMMY] FDP-Disabled SSD",
            "serial":   "DUMMY-FDP-OFF",
            "firmware": "1.0.0",
            "size_gb":  256.0,
            "dummy":    True,
        },
    ]


# ── DeviceManager ─────────────────────────────────────────────────────────────

class DeviceManager:

    def list_devices(self) -> list:
        """
        Returns a list of device dicts.  Dummy devices are always prepended
        so they appear at the top of the dropdown even with no hardware present.
        """
        real_devices = self._discover_real_devices()
        return _DUMMY_DEVICE_LIST + real_devices

    def _discover_real_devices(self) -> list:
        """
        Run 'nvme list -o json' and return one entry per controller device
        (e.g. /dev/nvme0), grouping any namespace entries (nvme0n1, nvme0n2…)
        under a 'namespaces' list so they are shown as informational sub-items
        in the UI rather than separate selectable devices.
        """
        try:
            result = subprocess.run(
                ["nvme", "list", "-o", "json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                # Group by controller path (strip trailing nN)
                controllers = {}
                for dev in data.get("Devices", []):
                    ns_path = dev.get("DevicePath", "")
                    # Derive controller path: /dev/nvme0n1 -> /dev/nvme0
                    ctrl = re.sub(r'n\d+$', '', ns_path)
                    if ctrl not in controllers:
                        controllers[ctrl] = {
                            "path":       ctrl,
                            "model":      dev.get("ModelNumber", "Unknown").strip(),
                            "serial":     dev.get("SerialNumber", "").strip(),
                            "firmware":   dev.get("Firmware", "").strip(),
                            "size_gb":    round(dev.get("PhysicalSize", 0) / 1e9, 1),
                            "dummy":      False,
                            "namespaces": [],
                        }
                    # Parse namespace ID from path suffix
                    m = re.search(r'n(\d+)$', ns_path)
                    if m:
                        controllers[ctrl]["namespaces"].append({
                            "nsid":    int(m.group(1)),
                            "path":    ns_path,
                            "size_gb": round(dev.get("PhysicalSize", 0) / 1e9, 1),
                        })
                # Also detect namespace-less controllers not returned by nvme list
                self._add_namespaceless_controllers(controllers)
                return list(controllers.values())
        except Exception:
            pass

        # Fallback: glob /dev/nvme[0-9] controller devices directly
        devices = []
        controllers_fallback = {}
        for path in sorted(glob.glob("/dev/nvme[0-9]*")):
            if not re.search(r'n\d+$', path):   # controller only
                controllers_fallback[path] = {
                    "path":          path,
                    "model":         "Unknown",
                    "serial":        "",
                    "firmware":      "",
                    "size_gb":       0,
                    "dummy":         False,
                    "namespaces":    [],
                    "no_namespaces": True,
                }
        return list(controllers_fallback.values())

    def _add_namespaceless_controllers(self, controllers: dict):
        """
        Detect NVMe controllers that have no namespaces (not returned by
        'nvme list') by globbing /dev/nvme* and adding any controller-only
        devices not already in the supplied controllers dict.
        Queries id-ctrl for model/serial info where available.
        """
        for path in sorted(glob.glob("/dev/nvme[0-9]*")):
            if re.search(r'n\d+$', path):
                continue                       # skip namespace devices
            if path in controllers:
                continue                       # already discovered via nvme list
            # Try to get controller info via id-ctrl
            model = "Unknown"
            serial = ""
            firmware = ""
            try:
                r = subprocess.run(
                    ["nvme", "id-ctrl", path, "-o", "json"],
                    capture_output=True, text=True, timeout=5
                )
                if r.returncode == 0:
                    info = json.loads(r.stdout)
                    model    = info.get("mn", "Unknown").strip()
                    serial   = info.get("sn", "").strip()
                    firmware = info.get("fr", "").strip()
            except Exception:
                pass
            controllers[path] = {
                "path":          path,
                "model":         model,
                "serial":        serial,
                "firmware":      firmware,
                "size_gb":       0,
                "dummy":         False,
                "namespaces":    [],
                "no_namespaces": True,
            }

    def get_fdp_info(self, device: str) -> dict:
        driver = self._make_driver(device)
        status  = driver.get_fdp_status()
        configs = driver.get_fdp_configs()
        fdp_supported = "error" not in status
        return {
            "device":        device,
            "fdp_supported": fdp_supported,
            "status":        status,
            "configs":       configs,
        }

    def _make_driver(self, device: str):
        """
        Factory — returns DummyNVMeDriver for dummy sentinel paths,
        NVMeCliDriver for everything else.
        """
        if _DummyNVMeDriver is not None and device in DUMMY_DEVICES:
            return _DummyNVMeDriver(device)
        NVMeCliDriver = _get_nvme_cli_driver()
        return NVMeCliDriver(device)