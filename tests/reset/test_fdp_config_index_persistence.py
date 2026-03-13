"""
Test: fdp_config_index_persistence_across_reset

When multiple FDP configurations are available (as reported by
`nvme fdp configs`), the active configuration index is set at enable time
and must persist across all resets.  A configuration switch after reset
would change the number of placement handles available to the host,
silently breaking FDP-aware applications.

This test reads the active config index before and after each reset type
and verifies it is unchanged.

Pass criteria : Active FDP config index identical before and after every reset.
Fail criteria : Config index changes after any reset.
Skip criteria : FDP not enabled, or only one config available (nothing to compare).
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.reset.reset_base import ResetTestBase


class TestFDPConfigIndexPersistence(ResetTestBase, BaseTest):
    test_id   = "fdp_config_index_persistence_across_reset"
    name      = "FDP Config Index — Persistence Across All Reset Types"
    description = (
        "Reads the active FDP configuration index via Get Feature FID 0x1D "
        "and the FDP Configs log page, then verifies the same configuration "
        "remains active after a Controller Reset, NVM Subsystem Reset, and "
        "PCIe link reset. A configuration change after reset would alter "
        "the number of active placement handles, breaking FDP isolation."
    )
    category = "Reset"
    tags     = ["reset", "fdp-config", "config-index", "controller-reset",
                "subsystem-reset", "pcie", "persistence"]

    DEFAULT_PARAMS = {
        "endgrp": 1,
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: FDP enabled? ───────────────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log, endgrp=p["endgrp"])
        if skip:
            return skip

        # ── Step 2: Read baseline config ───────────────────────────────────────
        log(f"\nStep 2: Reading active FDP configuration (endgrp={p['endgrp']})...")
        cfg_before = self._read_active_config(driver, log, p["endgrp"])
        if cfg_before is None:
            return TestResult(
                TestStatus.SKIP,
                "Could not determine active FDP configuration index. "
                "Device may only support one configuration."
            )
        log(f"  Active config: index={cfg_before.get('index')}  "
            f"nruh={cfg_before.get('nruh')}  npids={cfg_before.get('npids')}")

        failures = []

        for reset_label, reset_fn, is_link in [
            ("Controller Reset",          self._do_controller_reset, False),
            ("NVM Subsystem Reset (NSSR)", self._do_subsystem_reset,  False),
            ("PCIe Link Reset",           self._do_link_reset,        True),
        ]:
            log(f"\n━━━ {reset_label} ━━━")
            err = reset_fn(driver, log)
            if err:
                if is_link:
                    log(f"  ⚠ Skipping PCIe reset: {err.message}")
                    continue
                return err

            recovery_ok = self._post_reset_recovery(
                driver, log, is_link_reset=is_link
            )
            if not recovery_ok:
                return TestResult(
                    TestStatus.FAIL,
                    f"Device did not recover after {reset_label}"
                )

            cfg_after = self._read_active_config(driver, log, p["endgrp"])
            if cfg_after is None:
                failures.append(f"{reset_label}: config unreadable after reset")
                continue

            log(f"  Active config post-reset: index={cfg_after.get('index')}  "
                f"nruh={cfg_after.get('nruh')}  npids={cfg_after.get('npids')}")

            if cfg_after.get("index") != cfg_before.get("index"):
                failures.append(
                    f"{reset_label}: config index changed "
                    f"{cfg_before.get('index')} → {cfg_after.get('index')}"
                )
                log(f"  ✗ Config index changed!")
            elif cfg_after.get("nruh") != cfg_before.get("nruh"):
                failures.append(
                    f"{reset_label}: nruh changed "
                    f"{cfg_before.get('nruh')} → {cfg_after.get('nruh')}"
                )
                log(f"  ✗ NRUH count changed!")
            else:
                log(f"  ✓ Config unchanged after {reset_label}")

        if not failures:
            return TestResult(
                TestStatus.PASS,
                f"FDP configuration index ({cfg_before.get('index')}) persisted "
                "correctly across all reset types"
            )
        return TestResult(
            TestStatus.FAIL,
            "FDP configuration changed after reset(s): " + "; ".join(failures),
            details={"failures": failures, "baseline": cfg_before}
        )

    # ── Helper ────────────────────────────────────────────────────────────────

    def _read_active_config(self, driver, log, endgrp: int) -> dict | None:
        """
        Return a dict describing the currently active FDP config:
          {"index": N, "nruh": M, "npids": K}
        Uses Get Feature FID 0x1D to get the active config index, then
        FDP Configs log to get the RUH/PID counts for that index.
        """
        # Get Feature FID 0x1D — bits [7:0] of result = active config index
        feat = driver.run_cmd(
            ["get-feature", driver.device,
             "--feature-id=0x1d", f"--cdw11={endgrp}"],
            json_out=True
        )
        active_idx = None
        if feat["rc"] == 0:
            data = feat.get("data", {})
            if isinstance(data, dict):
                for k in ("active_fdp_config_index", "fdp_config_index",
                          "FdpConfigIndex", "conf_idx", "value"):
                    if k in data:
                        try:
                            active_idx = int(str(data[k]).split()[0], 0)
                        except (ValueError, IndexError):
                            pass
                        break

        # FDP Configs log
        cfg_result = driver.fdp_configs(endgrp=endgrp)
        if cfg_result["rc"] != 0:
            return None

        cfg_data = cfg_result.get("data", {})
        nruh  = None
        npids = None

        # Try to extract NRUH and NPIDS for the active config
        configs = None
        if isinstance(cfg_data, list):
            configs = cfg_data
        elif isinstance(cfg_data, dict):
            for k in ("fdp_configurations", "configurations", "configs", "fdp_cfgs"):
                if k in cfg_data and isinstance(cfg_data[k], list):
                    configs = cfg_data[k]
                    break

        if configs:
            idx = active_idx if active_idx is not None else 0
            if idx < len(configs):
                cfg_entry = configs[idx]
                for nk in ("nruh", "NRUH", "num_ruh", "number_of_ruh"):
                    if nk in cfg_entry:
                        nruh = int(cfg_entry[nk])
                        break
                for pk in ("npids", "NPIDS", "num_pids", "number_of_pids"):
                    if pk in cfg_entry:
                        npids = int(cfg_entry[pk])
                        break

        if active_idx is None and configs is None:
            return None

        return {"index": active_idx, "nruh": nruh, "npids": npids}
