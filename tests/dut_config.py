"""
dut_config.py — DUT (Device Under Test) FDP configuration snapshot.

Usage in test scripts
─────────────────────
    from tests.dut_config import dut_config

    class TestMyCase(BaseTest):
        def run(self, driver, log):
            cfg = dut_config.require(log)   # returns None and logs a warning
            if cfg is None:                 # if no snapshot has been taken yet
                ...

    # Or access fields directly (all are None if not yet populated):
    n_handles   = dut_config.n_ruhs                 # int | None
    ruhs        = dut_config.ruhs                   # list[dict] | None
    fdp_enabled = dut_config.fdp_enabled            # bool | None
    configs     = dut_config.fdp_configs            # dict | None
    usage       = dut_config.fdp_usage              # dict | None
    stats       = dut_config.fdp_stats              # dict | None
    feature     = dut_config.fdp_feature            # dict | None

Population
──────────
The GUI button "Extract DUT FDP Config" calls POST /api/ctrl/extract-fdp-config,
which calls DUTConfig.populate(driver) and stores the result here.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import re
from datetime import datetime
from typing import Any


@dataclass
class DUTConfig:
    """
    Holds a snapshot of all FDP-related information for the current DUT.
    All fields default to None until populate() is called.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    device:       str | None = None
    captured_at:  str | None = None   # ISO timestamp

    # ── FDP enable state (nvme get-feature --feature-id=0x1D) ─────────────────
    fdp_enabled:  bool | None = None
    fdp_feature:  dict | None = None  # raw get-feature response data

    # ── FDP Configurations log (nvme fdp configs) ─────────────────────────────
    fdp_configs:  dict | None = None

    # ── Reclaim Unit Handle Status (nvme fdp status -n <ns>) ──────────────────
    ruhs:         list | None = None  # list[{"ruhid": int, "ruamw": int}]
    n_ruhs:       int  | None = None  # len(ruhs) convenience accessor

    # ── FDP RUH Usage log (nvme fdp usage) ───────────────────────────────────
    fdp_usage:    dict | None = None

    # ── FDP Statistics log (nvme fdp stats) ──────────────────────────────────
    fdp_stats:    dict | None = None

    # ── Raw command results (for debugging) ──────────────────────────────────
    _raw: dict = field(default_factory=dict, repr=False)

    # ─────────────────────────────────────────────────────────────────────────

    @property
    def is_populated(self) -> bool:
        return self.device is not None

    def require(self, log=None) -> "DUTConfig | None":
        """
        Return self if populated, else log a warning and return None.
        Designed for use at the top of a test's run() method:

            cfg = dut_config.require(log)
            if cfg is None:
                return TestResult(TestStatus.SKIP, "No DUT config — press 'Extract DUT FDP Config' first")
        """
        if not self.is_populated:
            msg = (
                "DUT FDP config has not been extracted yet. "
                "Click 'Extract DUT FDP Config' in the Device Control bar before running tests."
            )
            if log:
                log(f"⚠ {msg}")
            return None
        return self

    def populate(self, driver) -> dict:
        """
        Run all FDP discovery commands against `driver` and store the results.
        Returns a summary dict suitable for JSON serialisation to the frontend.

        Commands issued:
          nvme fdp status <dev>              — FDP enable state
          nvme fdp status <dev> -n 1         — Reclaim Unit Handle Status (RUHS)
          nvme fdp configs <dev> -e 1        — FDP Configurations log
          nvme fdp usage  <dev> -e 1         — RUH Usage log
          nvme fdp stats  <dev> -e 1         — FDP Statistics log
          nvme get-feature <dev> --feature-id=0x1D --cdw11=1  — FDP feature
        """
        self.device      = driver.device
        self.captured_at = datetime.now().isoformat()
        self._raw        = {}
        summary          = {"device": self.device, "captured_at": self.captured_at, "commands": []}

        def _run(label: str, result: dict):
            """Store a raw result and append a summary entry."""
            self._raw[label] = result
            summary["commands"].append({
                "label":  label,
                "cmd":    result.get("cmd", ""),
                "rc":     result.get("rc", -1),
                "ok":     result.get("rc", -1) == 0,
                "stderr": result.get("stderr", "").strip(),
            })
            return result

        # Derive controller device once — used throughout populate()
        ctrl_dev = re.sub(r'n\d+$', '', driver.device)

        # ── 1. FDP enable state ───────────────────────────────────────────────
        feat_r = _run("get_feature_fdp",
                      driver.run_cmd(
                          ["get-feature", ctrl_dev,
                           "--feature-id=0x1d", "--cdw11=1",
                           "--namespace-id=0"],
                          json_out=True
                      ))
        self.fdp_feature = feat_r.get("data")
        self.fdp_enabled = self._parse_fdp_enabled(feat_r)

        # ── 2. FDP Configurations log ─────────────────────────────────────────
        cfg_r = _run("fdp_configs", driver.get_fdp_configs(endgrp=1))
        self.fdp_configs = cfg_r.get("data")

        # ── 3-6. All namespaces: list-ns on controller, then per-NS id-ns + RUHS ─
        idns_r = _run("id_ns", driver.run_cmd(
            ["id-ns", driver.device, "--namespace-id=1"], json_out=True))
        self.id_ns = idns_r.get("data")

        ns_list_r = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
        all_ns = []
        if ns_list_r["rc"] == 0:
            ns_data = ns_list_r.get("data", {})
            raw_list = []
            if isinstance(ns_data, dict):
                raw_list = ns_data.get("nsid_list", ns_data.get("NamespaceList", []))
            elif isinstance(ns_data, list):
                raw_list = ns_data
            for raw in raw_list:
                nsid = int(raw["nsid"]) if isinstance(raw, dict) else int(raw)
                ns_entry = {"nsid": nsid}
                # id-ns
                idr = driver.run_cmd(["id-ns", ctrl_dev,
                                      f"--namespace-id={nsid}"], json_out=True)
                if idr["rc"] == 0:
                    d = idr.get("data", {})
                    if isinstance(d, dict):
                        ns_entry["id_ns"] = d
                # RUHS per namespace — fdp status takes the namespace device
                # path directly (e.g. /dev/nvme0n1); -n flag causes "invalid
                # argument" on this device.
                ns_dev = ctrl_dev + f"n{nsid}"
                ruhs_r = _run(f"fdp_ruhs_ns{nsid}",
                    driver.run_cmd(["fdp", "status", ns_dev], json_out=True))
                ns_entry["ruhs"] = driver.extract_ruhs(ruhs_r) or []
                ns_entry["ruhs_rc"]  = ruhs_r.get("rc")
                ns_entry["ruhs_err"] = ruhs_r.get("stderr", "").strip()
                all_ns.append(ns_entry)
        if not all_ns:
            # Fallback: at least include NSID 1 with whatever RUHS we can get
            ruhs_r = _run("fdp_ruhs", driver.run_cmd(
                ["fdp", "status", ctrl_dev + "n1"], json_out=True))
            self.ruhs = driver.extract_ruhs(ruhs_r)
            all_ns = [{"nsid": 1, "id_ns": self.id_ns, "ruhs": self.ruhs or []}]
        else:
            # Use first NS RUHS as the top-level summary for backwards compat
            _first_ns_dev = ctrl_dev + f"n{all_ns[0]['nsid']}"
            _run("fdp_ruhs", driver.run_cmd(
                ["fdp", "status", _first_ns_dev], json_out=True))

        # Top-level ruhs = first namespace's handles (used by diagram header)
        self.ruhs   = all_ns[0]["ruhs"] if all_ns else []
        self.n_ruhs = max(len(ns.get("ruhs", [])) for ns in all_ns) if all_ns else None

        # ── 4. FDP RUH Usage log ──────────────────────────────────────────────
        usage_r = _run("fdp_usage", driver.get_fdp_placement_ids(endgrp=1))
        self.fdp_usage = usage_r.get("data")

        # ── 5. FDP Statistics log ─────────────────────────────────────────────
        stats_r = _run("fdp_stats", driver.get_fdp_stats(endgrp=1))
        self.fdp_stats = stats_r.get("data")

        # ── 7. Identify Controller — for tnvmcap (total NVM capacity) ────────
        idctrl_r = _run("id_ctrl", driver.run_cmd(
            ["id-ctrl", ctrl_dev], json_out=True))
        self.id_ctrl = idctrl_r.get("data")

        # ── Build human-readable summary for the GUI modal ───────────────────
        summary["id_ctrl"]     = self.id_ctrl
        summary["fdp_enabled"] = self.fdp_enabled
        summary["n_ruhs"]      = self.n_ruhs
        summary["ruhs"]        = self.ruhs
        summary["fdp_configs"] = self.fdp_configs
        summary["fdp_usage"]   = self.fdp_usage
        summary["fdp_stats"]   = self.fdp_stats
        summary["fdp_feature"] = self.fdp_feature
        summary["id_ns"]       = self.id_ns
        summary["namespaces"]  = all_ns
        return summary

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_fdp_enabled(feat_result: dict) -> bool | None:
        """
        Parse the get-feature FID 0x1D response to determine if FDP is enabled.
        Returns True/False, or None if the command failed or output is ambiguous.

        nvme-cli returns a nested structure for FID 0x1D:
          {
            ...,
            "Feature: 0x1d": [
              {
                "Flexible Data Placement Enable (FDPE)": "Yes",
                ...
              }
            ],
            ...
          }
        Fallback tiers handle older/alternative nvme-cli output formats.
        """
        import re as _re

        if feat_result.get("rc", -1) != 0:
            return None

        data = feat_result.get("data", {})

        if isinstance(data, dict):
            # 1. Primary: scan for a key containing "Feature: 0x1d" (case-insensitive)
            #    whose value is a list of dicts containing the FDPE field.
            for key, val in data.items():
                if _re.search(r'feature.*0x1d', str(key), _re.IGNORECASE):
                    entries = val if isinstance(val, list) else [val]
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        for ekey, eVal in entry.items():
                            if 'fdpe' in ekey.lower() or 'flexible data placement enable' in ekey.lower():
                                return str(eVal).strip().lower() in ('yes', '1', 'true', 'enabled')

            # 2. Clean JSON keys fallback
            for key in ("fdp_enabled", "FdpEnabled", "FDP Enabled", "value", "result"):
                if key in data:
                    raw = data[key]
                    try:
                        val = int(str(raw).split()[0], 0) if isinstance(raw, str) else int(raw)
                        return bool(val)
                    except (ValueError, TypeError):
                        pass

            # 3. Description-as-key scan — e.g. "..., value : 0x00000001"
            for key in data:
                m = _re.search(r'value\s*[=:]\s*(0x[0-9a-fA-F]+|\d+)', str(key))
                if m:
                    try:
                        return bool(int(m.group(1), 0))
                    except (ValueError, TypeError):
                        pass

        # 4. Raw stdout fallback
        stdout = feat_result.get("stdout", "")
        m = _re.search(r'value\s*[=:]\s*(0x[0-9a-fA-F]+|\d+)', stdout, _re.IGNORECASE)
        if m:
            try:
                return bool(int(m.group(1), 0))
            except (ValueError, TypeError):
                pass

        return None

    def clear(self):
        """Reset to unpopulated state."""
        self.__init__()


# ── Module-level singleton ────────────────────────────────────────────────────
#
# All test scripts import this one object:
#
#     from tests.dut_config import dut_config
#
dut_config = DUTConfig()