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
        """Run 'nvme list -o json' and return a list of device dicts."""
        try:
            result = subprocess.run(
                ["nvme", "list", "-o", "json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                devices = []
                for dev in data.get("Devices", []):
                    devices.append({
                        "path":     dev.get("DevicePath", ""),
                        "model":    dev.get("ModelNumber", "Unknown").strip(),
                        "serial":   dev.get("SerialNumber", "").strip(),
                        "firmware": dev.get("Firmware", "").strip(),
                        "size_gb":  round(dev.get("PhysicalSize", 0) / 1e9, 1),
                        "dummy":    False,
                    })
                return devices
        except Exception:
            pass

        # Fallback: glob /dev/nvme*
        devices = []
        for path in sorted(glob.glob("/dev/nvme[0-9]")):
            devices.append({
                "path":     path,
                "model":    "Unknown",
                "serial":   "",
                "firmware": "",
                "size_gb":  0,
                "dummy":    False,
            })
        return devices

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
