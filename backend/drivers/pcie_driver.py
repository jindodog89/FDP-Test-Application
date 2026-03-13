"""
PCIe Driver — userspace PCIe config space and link control via Linux sysfs.

Provides access to both the NVMe endpoint device and its upstream root port /
bridge, enabling test cases to manipulate link state, perform resets, and
read/write config space registers without requiring SPDK or kernel modules.

Sysfs interface summary used here:
  /sys/bus/pci/devices/<bdf>/
    config              — raw 256/4096-byte config space (r/w binary file)
    enable              — "1" if device is enabled, write 0/1 to disable/enable
    reset               — write 1 to trigger FLR (Function Level Reset)
    remove              — write 1 to remove device from kernel
    rescan              — write 1 to rescan parent bus (at bus level)
    link/l1_aspm        — ASPM L1 control
  /sys/bus/pci/devices/<upstream_port>/
    reset               — FLR on the upstream port
    reset_subordinate   — write 1 to reset all devices on subordinate bus
                          (kernel 6.6+; equivalent to Secondary Bus Reset)
  /sys/bus/pci/rescan    — global rescan

Secondary Bus Reset (SBR) on older kernels is done by directly setting
bit 6 (Secondary Bus Reset) of the Bridge Control register (offset 0x3E
in Type 1 config space) via setpci, which is the standard userspace method.

Reference: https://alexforencich.com/wiki/en/pcie/hot-reset-linux
"""

import os
import glob
import struct
import subprocess
import logging
import time
from pathlib import Path

from backend.drivers.base_driver import BaseNVMeDriver

log = logging.getLogger("nvme_cli.debug")

# PCI config space offsets (Type 0 — endpoint)
PCI_VENDOR_ID        = 0x00   # u16
PCI_DEVICE_ID        = 0x02   # u16
PCI_COMMAND          = 0x04   # u16
PCI_STATUS           = 0x06   # u16
PCI_CLASS_REVISION   = 0x08   # u32
PCI_CACHE_LINE_SIZE  = 0x0C   # u8
PCI_LATENCY_TIMER    = 0x0D   # u8
PCI_HEADER_TYPE      = 0x0E   # u8
PCI_CAPABILITIES_PTR = 0x34   # u8

# PCI Command register bits
PCI_CMD_IO_SPACE      = 0x0001
PCI_CMD_MEM_SPACE     = 0x0002
PCI_CMD_BUS_MASTER    = 0x0004
PCI_CMD_INT_DISABLE   = 0x0400

# PCI Express Capability offsets (relative to cap base)
PCIE_CAP_ID          = 0x00   # u8  must == 0x10
PCIE_LINK_CONTROL    = 0x10   # u16
PCIE_LINK_STATUS     = 0x12   # u16
PCIE_LINK_CONTROL2   = 0x30   # u16

# PCIe Link Control bits
PCIE_LNKCTL_ASPM_L0S  = 0x0001
PCIE_LNKCTL_ASPM_L1   = 0x0002
PCIE_LNKCTL_LINK_DIS   = 0x0010
PCIE_LNKCTL_RCB        = 0x0008
PCIE_LNKCTL_RETRAIN    = 0x0020
PCIE_LNKCTL_CCC        = 0x0040

# Bridge Control register (Type 1 config space, offset 0x3E)
PCI_BRIDGE_CONTROL     = 0x3E
PCI_BRIDGE_CTL_SBR     = 0x0040   # Secondary Bus Reset bit


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: list, timeout: int = 10) -> dict:
    """Run a shell command, return {rc, stdout, stderr, cmd}."""
    cmd_str = " ".join(str(c) for c in cmd)
    log.debug("PCIE CMD: %s", cmd_str)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.stdout.strip():
            log.debug("PCIE OUT: %s", r.stdout.strip()[:1000])
        if r.stderr.strip():
            log.debug("PCIE ERR: %s", r.stderr.strip()[:500])
        return {"rc": r.returncode, "stdout": r.stdout,
                "stderr": r.stderr, "cmd": cmd_str}
    except FileNotFoundError:
        return {"rc": 127, "stdout": "", "stderr": f"Command not found: {cmd[0]}",
                "cmd": cmd_str}
    except subprocess.TimeoutExpired:
        return {"rc": -1, "stdout": "", "stderr": "Timed out", "cmd": cmd_str}


def _sysfs_write(path: str, value: str) -> dict:
    """Write a string value to a sysfs file."""
    log.debug("PCIE SYSFS WRITE: %s <- %r", path, value)
    try:
        with open(path, "w") as f:
            f.write(value)
        return {"rc": 0, "path": path, "value": value}
    except PermissionError:
        return {"rc": 1, "error": f"Permission denied: {path} (run as root)"}
    except FileNotFoundError:
        return {"rc": 2, "error": f"Sysfs node not found: {path}"}
    except OSError as e:
        return {"rc": 3, "error": str(e)}


def _sysfs_read(path: str) -> str | None:
    """Read a sysfs file, return stripped string or None."""
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


# ── PCIe Driver ───────────────────────────────────────────────────────────────

class PCIeDriver:
    """
    Sysfs-backed PCIe driver for an NVMe endpoint and its upstream port.

    Usage:
        pcie = PCIeDriver.from_nvme_device("/dev/nvme0")
        info = pcie.get_device_info()
        pcie.disable_link()
        pcie.secondary_bus_reset()
        pcie.enable_link()
        dump = pcie.dump_config_space()
    """

    def __init__(self, bdf: str, upstream_bdf: str | None = None):
        """
        Args:
            bdf:          PCI BDF of the NVMe endpoint, e.g. "0000:01:00.0"
            upstream_bdf: BDF of the upstream root port/bridge. Auto-detected
                          if not provided.
        """
        self.bdf          = self._normalise_bdf(bdf)
        self.sysfs_dev    = f"/sys/bus/pci/devices/{self.bdf}"
        self.upstream_bdf = (self._normalise_bdf(upstream_bdf)
                             if upstream_bdf else self._find_upstream())
        self.sysfs_up     = (f"/sys/bus/pci/devices/{self.upstream_bdf}"
                             if self.upstream_bdf else None)

        log.debug("PCIeDriver init: dev=%s  upstream=%s", self.bdf, self.upstream_bdf)

    # ── Construction helpers ──────────────────────────────────────────────────

    @classmethod
    def from_nvme_device(cls, nvme_dev: str) -> "PCIeDriver":
        """
        Build a PCIeDriver from an NVMe device path like /dev/nvme0 or /dev/nvme0n1.
        Resolves the PCI BDF via the sysfs 'device' symlink.

        'ls -l /sys/class/nvme/nvme*' shows each controller as a symlink:
            /sys/class/nvme/nvme0 -> ../../devices/pci0000:00/.../0000:01:00.0/nvme/nvme0
        """
        # Strip namespace suffix: /dev/nvme0n1 -> nvme0, /dev/nvme0 -> nvme0
        import re as _re
        ctrl = _re.sub(r'n\d+$', '', os.path.basename(nvme_dev))

        sysfs_nvme = f"/sys/class/nvme/{ctrl}"
        if not os.path.exists(sysfs_nvme):
            raise FileNotFoundError(
                f"NVMe controller '{ctrl}' not found in sysfs at {sysfs_nvme}"
            )

        # /sys/class/nvme/<ctrl>/device is a symlink -> PCI device directory
        device_link = f"{sysfs_nvme}/device"
        if not os.path.exists(device_link):
            raise FileNotFoundError(
                f"Sysfs 'device' symlink not found: {device_link}"
            )

        # Resolve the symlink — its basename is the BDF
        real = os.path.realpath(device_link)
        bdf = os.path.basename(real)

        if not cls._is_bdf(bdf):
            raise RuntimeError(
                f"Could not resolve PCI BDF for {nvme_dev}: "
                f"'{device_link}' resolved to '{real}' "
                f"(basename '{bdf}' is not a valid BDF)"
            )

        return cls(bdf)

    @staticmethod
    def _is_bdf(s: str) -> bool:
        """Return True if string looks like DDDD:BB:DD.F"""
        import re
        return bool(re.match(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]$", s))

    @staticmethod
    def _normalise_bdf(bdf: str) -> str:
        """Add domain prefix if missing: 01:00.0 -> 0000:01:00.0"""
        if bdf.count(":") == 1:
            return "0000:" + bdf
        return bdf

    def _find_upstream(self) -> str | None:
        """
        Locate the upstream root port / bridge by following the sysfs symlink
        of the device's parent directory.
        """
        try:
            real = os.path.realpath(self.sysfs_dev)
            parent = os.path.dirname(real)
            parent_name = os.path.basename(parent)
            if self._is_bdf(parent_name):
                log.debug("Upstream port: %s", parent_name)
                return parent_name
        except Exception as e:
            log.debug("Could not find upstream port: %s", e)
        return None

    # ── Device info ───────────────────────────────────────────────────────────

    def get_device_info(self) -> dict:
        """
        Return a summary of the PCIe device: BDF, vendor/device ID, link
        speed/width, enabled state, driver, upstream port.
        """
        info = {
            "bdf":           self.bdf,
            "upstream_bdf":  self.upstream_bdf,
            "sysfs_path":    self.sysfs_dev,
            "exists":        os.path.isdir(self.sysfs_dev),
        }

        if not info["exists"]:
            return info

        for attr in ("vendor", "device", "class", "enable", "driver"):
            path = f"{self.sysfs_dev}/{attr}"
            if attr == "driver":
                drv = os.path.realpath(path) if os.path.exists(path) else None
                info["driver"] = os.path.basename(drv) if drv else None
            else:
                info[attr] = _sysfs_read(path)

        # Link status from lspci
        lspci = _run(["lspci", "-vv", "-s", self.bdf])
        if lspci["rc"] == 0:
            import re
            m = re.search(r"LnkSta:.*?Speed\s+([\w.]+),.*?Width\s+(x\d+)", lspci["stdout"])
            if m:
                info["link_speed"] = m.group(1)
                info["link_width"] = m.group(2)
            m2 = re.search(r"LnkCap:.*?Speed\s+([\w.]+),.*?Width\s+(x\d+)", lspci["stdout"])
            if m2:
                info["max_link_speed"] = m2.group(1)
                info["max_link_width"] = m2.group(2)

        return info

    # ── Config space access ───────────────────────────────────────────────────

    def read_config_space(self, bdf: str | None = None) -> bytes | None:
        """
        Read raw config space bytes for the endpoint (default) or any BDF.
        Returns up to 4096 bytes (PCIe extended config space).
        """
        target_bdf = self._normalise_bdf(bdf) if bdf else self.bdf
        config_path = f"/sys/bus/pci/devices/{target_bdf}/config"
        log.debug("PCIE READ CONFIG: %s", config_path)
        try:
            return Path(config_path).read_bytes()
        except FileNotFoundError:
            log.debug("Config space not found: %s", config_path)
            return None
        except PermissionError:
            log.debug("Permission denied reading config: %s", config_path)
            return None

    def dump_config_space(self, bdf: str | None = None) -> dict:
        """
        Dump and decode config space for the endpoint or a specified BDF.
        Returns both the raw hex dump and decoded standard fields.
        """
        target_bdf = self._normalise_bdf(bdf) if bdf else self.bdf
        raw = self.read_config_space(target_bdf)
        if raw is None:
            return {"error": f"Could not read config space for {target_bdf}"}

        result = {
            "bdf":       target_bdf,
            "size":      len(raw),
            "hex_dump":  self._hex_dump(raw),
            "fields":    {},
        }

        # Decode standard Type 0 header fields
        if len(raw) >= 64:
            f = result["fields"]
            f["vendor_id"]   = f"0x{struct.unpack_from('<H', raw, 0x00)[0]:04x}"
            f["device_id"]   = f"0x{struct.unpack_from('<H', raw, 0x02)[0]:04x}"
            f["command"]     = f"0x{struct.unpack_from('<H', raw, 0x04)[0]:04x}"
            f["status"]      = f"0x{struct.unpack_from('<H', raw, 0x06)[0]:04x}"
            f["revision_id"] = f"0x{struct.unpack_from('<B', raw, 0x08)[0]:02x}"
            f["class_code"]  = f"0x{struct.unpack_from('<I', raw, 0x08)[0] >> 8:06x}"
            f["header_type"] = f"0x{struct.unpack_from('<B', raw, 0x0E)[0]:02x}"

            cmd = struct.unpack_from('<H', raw, 0x04)[0]
            f["command_decoded"] = {
                "io_space":      bool(cmd & PCI_CMD_IO_SPACE),
                "mem_space":     bool(cmd & PCI_CMD_MEM_SPACE),
                "bus_master":    bool(cmd & PCI_CMD_BUS_MASTER),
                "int_disable":   bool(cmd & PCI_CMD_INT_DISABLE),
            }

            # Walk capability list
            f["capabilities"] = self._parse_capabilities(raw)

        return result

    def read_config_register(self, offset: int, width: int = 2,
                              bdf: str | None = None) -> int | None:
        """
        Read a single config space register.
        width: 1=byte, 2=word, 4=dword
        """
        target_bdf = self._normalise_bdf(bdf) if bdf else self.bdf
        raw = self.read_config_space(target_bdf)
        if raw is None or offset + width > len(raw):
            return None
        fmt = {1: "<B", 2: "<H", 4: "<I"}[width]
        return struct.unpack_from(fmt, raw, offset)[0]

    def write_config_register(self, offset: int, value: int, width: int = 2,
                               bdf: str | None = None) -> dict:
        """
        Write a single config space register via setpci.
        width: 1=byte, 2=word, 4=dword (b/w/l in setpci notation)
        """
        target_bdf = self._normalise_bdf(bdf) if bdf else self.bdf
        fmt = {1: "b", 2: "w", 4: "l"}[width]
        width_bits = width * 8
        value_str = f"{value:0{width*2}x}"
        result = _run(["setpci", "-s", target_bdf,
                        f"{offset:#04x}.{fmt}={value_str}"])
        result["offset"] = offset
        result["value"]  = value
        return result

    # ── Link control ──────────────────────────────────────────────────────────

    def disable_link(self) -> dict:
        """
        Disable the PCIe link by setting the Link Disable bit (bit 4) in the
        Link Control register of the upstream port's PCIe capability.
        The NVMe device will become unreachable until the link is re-enabled.
        """
        if not self.upstream_bdf:
            return {"rc": 1, "error": "No upstream port found — cannot disable link"}

        log.debug("Disabling PCIe link on upstream port %s", self.upstream_bdf)
        current = self._read_lnkctl(self.upstream_bdf)
        if current is None:
            return {"rc": 1, "error": "Could not read Link Control register"}

        new_val = current | PCIE_LNKCTL_LINK_DIS
        result = self.write_config_register(
            self._get_pcie_cap_offset(self.upstream_bdf) + PCIE_LINK_CONTROL,
            new_val, width=2, bdf=self.upstream_bdf
        )
        result["lnkctl_before"] = f"0x{current:04x}"
        result["lnkctl_after"]  = f"0x{new_val:04x}"
        result["action"] = "link_disable"
        return result

    def enable_link(self, retrain: bool = True) -> dict:
        """
        Re-enable the PCIe link by clearing the Link Disable bit, then
        optionally trigger link retraining.
        """
        if not self.upstream_bdf:
            return {"rc": 1, "error": "No upstream port found"}

        log.debug("Enabling PCIe link on upstream port %s", self.upstream_bdf)
        current = self._read_lnkctl(self.upstream_bdf)
        if current is None:
            return {"rc": 1, "error": "Could not read Link Control register"}

        new_val = current & ~PCIE_LNKCTL_LINK_DIS
        if retrain:
            new_val |= PCIE_LNKCTL_RETRAIN

        result = self.write_config_register(
            self._get_pcie_cap_offset(self.upstream_bdf) + PCIE_LINK_CONTROL,
            new_val, width=2, bdf=self.upstream_bdf
        )
        result["lnkctl_before"] = f"0x{current:04x}"
        result["lnkctl_after"]  = f"0x{new_val:04x}"
        result["action"] = "link_enable"
        return result

    def get_link_status(self) -> dict:
        """
        Read Link Status register from the endpoint's PCIe capability.
        Returns link speed, width, training state, and slot clock config.
        """
        raw = self.read_config_space()
        if raw is None:
            return {"error": "Could not read config space"}

        cap_off = self._get_pcie_cap_offset(self.bdf)
        if cap_off is None:
            return {"error": "PCIe capability not found in endpoint config space"}

        lnksta_off = cap_off + PCIE_LINK_STATUS
        if lnksta_off + 2 > len(raw):
            return {"error": "Config space too short to read Link Status"}

        lnksta = struct.unpack_from("<H", raw, lnksta_off)[0]
        speed_map = {1: "2.5 GT/s", 2: "5 GT/s", 3: "8 GT/s",
                     4: "16 GT/s", 5: "32 GT/s", 6: "64 GT/s"}
        cur_speed = lnksta & 0x000F
        cur_width = (lnksta >> 4) & 0x003F

        return {
            "lnksta_raw":    f"0x{lnksta:04x}",
            "link_speed":    speed_map.get(cur_speed, f"Unknown ({cur_speed})"),
            "link_width":    f"x{cur_width}",
            "link_training": bool(lnksta & 0x0800),
            "slot_clk_cfg":  bool(lnksta & 0x1000),
            "link_active":   not bool(lnksta & 0x2000),
        }

    # ── Reset operations ──────────────────────────────────────────────────────

    def function_level_reset(self) -> dict:
        """
        Trigger a Function Level Reset (FLR) on the NVMe endpoint via sysfs.
        Equivalent to writing 1 to /sys/bus/pci/devices/<bdf>/reset.
        """
        reset_path = f"{self.sysfs_dev}/reset"
        if not os.path.exists(reset_path):
            return {"rc": 1, "error": "FLR not supported (reset file not present in sysfs)"}
        log.debug("FLR on %s", self.bdf)
        result = _sysfs_write(reset_path, "1")
        result["action"] = "function_level_reset"
        result["bdf"]    = self.bdf
        return result

    def secondary_bus_reset(self, hold_ms: int = 10) -> dict:
        """
        Perform a Secondary Bus Reset (Hot Reset) on the upstream bridge.

        Strategy (in order of preference):
          1. reset_subordinate sysfs node (kernel 6.6+) on upstream port
          2. setpci: set then clear Bridge Control bit 6 (SBR) on upstream port
             — the standard userspace method for older kernels
        """
        if not self.upstream_bdf:
            return {"rc": 1, "error": "No upstream port found — cannot perform SBR"}

        log.debug("Secondary Bus Reset via upstream port %s", self.upstream_bdf)

        # Method 1: reset_subordinate (kernel 6.6+)
        reset_sub = f"{self.sysfs_up}/reset_subordinate"
        if os.path.exists(reset_sub):
            log.debug("Using reset_subordinate sysfs node")
            result = _sysfs_write(reset_sub, "1")
            result["action"] = "secondary_bus_reset"
            result["method"] = "sysfs_reset_subordinate"
            result["upstream_bdf"] = self.upstream_bdf
            return result

        # Method 2: setpci SBR bit toggle
        log.debug("reset_subordinate not available, using setpci SBR method")
        bc_result = _run(["setpci", "-s", self.upstream_bdf,
                           f"{PCI_BRIDGE_CONTROL:#04x}.w"])
        if bc_result["rc"] != 0:
            return {
                "rc": bc_result["rc"],
                "error": f"Could not read Bridge Control: {bc_result['stderr']}",
                "action": "secondary_bus_reset",
            }

        try:
            bc_val = int(bc_result["stdout"].strip(), 16)
        except ValueError:
            return {"rc": 1, "error": f"Unexpected Bridge Control value: {bc_result['stdout']}"}

        log.debug("Bridge Control before SBR: 0x%04x", bc_val)

        # Set SBR bit
        set_result = _run(["setpci", "-s", self.upstream_bdf,
                            f"{PCI_BRIDGE_CONTROL:#04x}.w={bc_val | PCI_BRIDGE_CTL_SBR:04x}"])
        if set_result["rc"] != 0:
            return {"rc": set_result["rc"],
                    "error": f"Failed to set SBR bit: {set_result['stderr']}"}

        time.sleep(hold_ms / 1000.0)

        # Clear SBR bit
        clr_result = _run(["setpci", "-s", self.upstream_bdf,
                            f"{PCI_BRIDGE_CONTROL:#04x}.w={bc_val & ~PCI_BRIDGE_CTL_SBR:04x}"])

        time.sleep(0.5)  # Allow device to complete reset and re-enumerate

        return {
            "rc":              clr_result["rc"],
            "action":          "secondary_bus_reset",
            "method":          "setpci_bridge_control",
            "upstream_bdf":    self.upstream_bdf,
            "bridge_ctl_before": f"0x{bc_val:04x}",
            "bridge_ctl_sbr":    f"0x{bc_val | PCI_BRIDGE_CTL_SBR:04x}",
            "bridge_ctl_after":  f"0x{bc_val & ~PCI_BRIDGE_CTL_SBR:04x}",
            "hold_ms":         hold_ms,
        }

    def hot_reset(self, rescan: bool = True) -> dict:
        """
        Full hot reset sequence:
          1. Remove endpoint from kernel
          2. Perform Secondary Bus Reset on upstream port
          3. Rescan parent bus to re-enumerate the device

        This is the safe userspace hot reset procedure as documented at
        https://alexforencich.com/wiki/en/pcie/hot-reset-linux
        """
        results = {}

        # Step 1: Remove endpoint
        log.debug("Hot reset step 1: removing endpoint %s", self.bdf)
        results["remove"] = _sysfs_write(f"{self.sysfs_dev}/remove", "1")
        time.sleep(0.1)

        # Step 2: SBR
        log.debug("Hot reset step 2: secondary bus reset")
        results["sbr"] = self.secondary_bus_reset()

        # Step 3: Rescan
        if rescan:
            log.debug("Hot reset step 3: rescanning parent bus")
            rescan_path = f"{self.sysfs_up}/rescan" if self.sysfs_up else "/sys/bus/pci/rescan"
            results["rescan"] = _sysfs_write(rescan_path, "1")
            time.sleep(0.5)

        overall_rc = max(
            results.get("remove", {}).get("rc", 0),
            results.get("sbr", {}).get("rc", 0),
            results.get("rescan", {}).get("rc", 0),
        )
        return {
            "rc":     overall_rc,
            "action": "hot_reset",
            "steps":  results,
            "bdf":    self.bdf,
        }

    # ── Device enable / disable ───────────────────────────────────────────────

    def remove_device(self) -> dict:
        """Remove the endpoint from the kernel's device tree (non-destructive)."""
        result = _sysfs_write(f"{self.sysfs_dev}/remove", "1")
        result["action"] = "remove_device"
        return result

    def rescan_bus(self) -> dict:
        """Rescan the parent bus to re-discover the device after removal."""
        path = f"{self.sysfs_up}/rescan" if self.sysfs_up else "/sys/bus/pci/rescan"
        result = _sysfs_write(path, "1")
        result["action"] = "rescan_bus"
        result["path"]   = path
        return result

    def set_bus_master(self, enable: bool) -> dict:
        """Enable or disable Bus Master Enable (BME) in the Command register."""
        current = self.read_config_register(PCI_COMMAND, width=2)
        if current is None:
            return {"rc": 1, "error": "Could not read Command register"}
        new_val = (current | PCI_CMD_BUS_MASTER) if enable else (current & ~PCI_CMD_BUS_MASTER)
        result = self.write_config_register(PCI_COMMAND, new_val, width=2)
        result["action"]  = "set_bus_master"
        result["enabled"] = enable
        result["cmd_before"] = f"0x{current:04x}"
        result["cmd_after"]  = f"0x{new_val:04x}"
        return result

    # ── ASPM control ─────────────────────────────────────────────────────────

    def get_aspm_state(self) -> dict:
        """Read current ASPM policy from sysfs link_power_management_policy."""
        path = f"{self.sysfs_dev}/link/l1_aspm"
        val = _sysfs_read(path)
        # Also check power management policy
        policy_path = f"{self.sysfs_dev}/power/control"
        policy = _sysfs_read(policy_path)
        return {
            "l1_aspm":       val,
            "power_control": policy,
            "lnkctl":        (f"0x{self._read_lnkctl(self.bdf):04x}"
                              if self._read_lnkctl(self.bdf) is not None else None),
        }

    def set_aspm(self, mode: str = "disabled") -> dict:
        """
        Set ASPM state.
        mode: "disabled", "l0s", "l1", "l0s_l1"
        """
        aspm_bits = {
            "disabled": 0x0000,
            "l0s":      PCIE_LNKCTL_ASPM_L0S,
            "l1":       PCIE_LNKCTL_ASPM_L1,
            "l0s_l1":   PCIE_LNKCTL_ASPM_L0S | PCIE_LNKCTL_ASPM_L1,
        }
        if mode not in aspm_bits:
            return {"rc": 1, "error": f"Unknown ASPM mode '{mode}'. "
                    f"Valid: {list(aspm_bits.keys())}"}

        cap_off = self._get_pcie_cap_offset(self.bdf)
        if cap_off is None:
            return {"rc": 1, "error": "PCIe capability not found"}

        current = self.read_config_register(cap_off + PCIE_LINK_CONTROL, width=2)
        if current is None:
            return {"rc": 1, "error": "Could not read Link Control register"}

        mask    = ~(PCIE_LNKCTL_ASPM_L0S | PCIE_LNKCTL_ASPM_L1) & 0xFFFF
        new_val = (current & mask) | aspm_bits[mode]
        result  = self.write_config_register(cap_off + PCIE_LINK_CONTROL, new_val, width=2)
        result["action"]       = "set_aspm"
        result["aspm_mode"]    = mode
        result["lnkctl_before"] = f"0x{current:04x}"
        result["lnkctl_after"]  = f"0x{new_val:04x}"
        return result

    # ── Capability scanning ───────────────────────────────────────────────────

    def list_capabilities(self) -> dict:
        """List all PCI and PCIe extended capabilities in config space."""
        raw = self.read_config_space()
        if raw is None:
            return {"error": "Could not read config space"}
        return {
            "bdf":          self.bdf,
            "capabilities": self._parse_capabilities(raw),
        }

    # ── lspci wrappers ────────────────────────────────────────────────────────

    def lspci_verbose(self, bdf: str | None = None) -> dict:
        """Run lspci -vvv on the endpoint or a specified BDF."""
        target = self._normalise_bdf(bdf) if bdf else self.bdf
        result = _run(["lspci", "-vvv", "-s", target])
        result["bdf"] = target
        return result

    def lspci_tree(self) -> dict:
        """Run lspci -t to show the PCIe topology."""
        return _run(["lspci", "-tv"])

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_pcie_cap_offset(self, bdf: str) -> int | None:
        """
        Walk the capability linked list to find the PCIe capability (ID 0x10).
        Returns the byte offset in config space, or None if not found.
        """
        raw = self.read_config_space(bdf)
        if raw is None or len(raw) < 64:
            return None

        ptr = struct.unpack_from("<B", raw, PCI_CAPABILITIES_PTR)[0] & ~0x3
        visited = set()
        while ptr and ptr not in visited and ptr + 2 <= len(raw):
            visited.add(ptr)
            cap_id = struct.unpack_from("<B", raw, ptr)[0]
            if cap_id == 0x10:  # PCIe capability
                return ptr
            ptr = struct.unpack_from("<B", raw, ptr + 1)[0] & ~0x3

        return None

    def _read_lnkctl(self, bdf: str) -> int | None:
        """Read Link Control register value for the given BDF."""
        cap_off = self._get_pcie_cap_offset(bdf)
        if cap_off is None:
            return None
        return self.read_config_register(cap_off + PCIE_LINK_CONTROL, width=2, bdf=bdf)

    def _parse_capabilities(self, raw: bytes) -> list:
        """Walk the standard capability list and return decoded entries."""
        if len(raw) < 64:
            return []

        cap_names = {
            0x01: "Power Management",
            0x02: "AGP",
            0x04: "Slot ID",
            0x05: "MSI",
            0x10: "PCIe",
            0x11: "MSI-X",
            0x12: "SATA",
            0x13: "AF",
        }

        caps = []
        ptr = struct.unpack_from("<B", raw, PCI_CAPABILITIES_PTR)[0] & ~0x3
        visited = set()

        while ptr and ptr not in visited and ptr + 2 <= len(raw):
            visited.add(ptr)
            cap_id  = struct.unpack_from("<B", raw, ptr)[0]
            next_ptr = struct.unpack_from("<B", raw, ptr + 1)[0] & ~0x3
            entry = {
                "offset": f"0x{ptr:02x}",
                "id":     f"0x{cap_id:02x}",
                "name":   cap_names.get(cap_id, f"Unknown (0x{cap_id:02x})"),
            }
            if cap_id == 0x10 and ptr + PCIE_LINK_STATUS + 2 <= len(raw):
                lnksta = struct.unpack_from("<H", raw, ptr + PCIE_LINK_STATUS)[0]
                entry["link_speed_raw"] = lnksta & 0x000F
                entry["link_width_raw"] = (lnksta >> 4) & 0x003F
            caps.append(entry)
            ptr = next_ptr

        return caps

    @staticmethod
    def _hex_dump(data: bytes, bytes_per_row: int = 16) -> str:
        """Format raw bytes as an annotated hex dump string."""
        lines = []
        for i in range(0, len(data), bytes_per_row):
            chunk = data[i:i + bytes_per_row]
            hex_part  = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{i:04x}  {hex_part:<{bytes_per_row*3}}  {ascii_part}")
        return "\n".join(lines)