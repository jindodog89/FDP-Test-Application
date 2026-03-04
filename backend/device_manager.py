import subprocess
import json
import re
from .nvme_cli_driver import NVMeCliDriver

class DeviceManager:
    def list_devices(self) -> list:
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
                        "path": dev.get("DevicePath", ""),
                        "model": dev.get("ModelNumber", "Unknown"),
                        "serial": dev.get("SerialNumber", ""),
                        "firmware": dev.get("Firmware", ""),
                        "size_gb": round(dev.get("PhysicalSize", 0) / 1e9, 1),
                    })
                return devices
        except Exception as e:
            pass

        # Fallback: scan /dev/nvme*
        import glob
        devices = []
        for path in sorted(glob.glob("/dev/nvme[0-9]")):
            devices.append({"path": path, "model": "Unknown", "serial": "", "firmware": "", "size_gb": 0})
        return devices

    def get_fdp_info(self, device: str) -> dict:
        driver = NVMeCliDriver(device)
        status = driver.get_fdp_status()
        configs = driver.get_fdp_configs()
        fdp_supported = "error" not in status
        return {
            "device": device,
            "fdp_supported": fdp_supported,
            "status": status,
            "configs": configs,
        }
    
    def _make_driver(self, device: str):
        from backend.drivers.nvme_cli_driver import NVMeCliDriver
        return NVMeCliDriver(device)