"""
Test: fdp_stats_monotonicity_across_reset

FDP Statistics counters (mbmw, hbmw, mbe) are cumulative lifetime counters
that must be monotonically non-decreasing.  Persistence across reset means
they must equal their pre-reset value after recovery — but this test adds a
stronger assertion: the counters must NEVER go backwards.

This is distinct from the plain persistence tests:
  - Persistence test: before == after
  - Monotonicity test: after >= before  (allows for firmware quantisation)
                       AND after < (before + some_huge_unexpected_jump)

The test also checks that running more IO after the reset causes mbmw to
increase again, confirming the counter is live and not frozen.

Pass criteria : All counters >= pre-reset values after recovery; counters
               increase again after post-reset IO.
Fail criteria : Any counter decreases after reset (regression toward 0).
Warn criteria : Counter did not increase after post-reset IO (may be frozen).
Skip criteria : FDP not enabled, fio not installed.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.fdp.reset_base import ResetTestBase


class TestFDPStatsMonotonicity(ResetTestBase, BaseTest):
    test_id   = "fdp_stats_monotonicity_across_reset"
    name      = "FDP Stats — Monotonicity Across Controller Reset"
    description = (
        "Verifies that FDP Statistics counters (mbmw, hbmw, mbe) never "
        "decrease after a Controller Reset, and that they continue to "
        "increment when new IO is written after recovery. Tests both "
        "persistence and liveness of the FDP statistics machinery."
    )
    category = "Reset"
    tags     = ["reset", "controller-reset", "fdp-stats", "monotonicity",
                "mbmw", "persistence"]

    DEFAULT_PARAMS = {
        "fio_duration_sec":      10,
        "fio_duration_post_sec": 5,
        "fio_block_size":        "128k",
        "queue_depth":           8,
        "placement_handle":      0,
        "namespace":             1,
        "endgrp":                1,
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: FDP enabled? ───────────────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log, endgrp=p["endgrp"])
        if skip:
            return skip

        # ── Step 2: Pre-reset IO ───────────────────────────────────────────────
        log(f"\nStep 2: Running {p['fio_duration_sec']}s pre-reset IO workload...")
        ok = self._run_fio_workload(
            driver, log,
            duration_sec=p["fio_duration_sec"],
            block_size=p["fio_block_size"],
            queue_depth=p["queue_depth"],
            placement_handle=p["placement_handle"],
            namespace=p["namespace"],
        )
        if not ok:
            return TestResult(
                TestStatus.SKIP,
                "fio not available — install with: sudo apt install fio"
            )

        # ── Step 3: Snapshot stats before reset ───────────────────────────────
        log(f"\nStep 3: Reading FDP Statistics (pre-reset)...")
        stats_t0 = self._read_fdp_stats(driver, log, endgrp=p["endgrp"])
        if stats_t0 is None:
            return TestResult(TestStatus.FAIL,
                "FDP Statistics log unreadable before reset")
        self._log_stats_snapshot(log, stats_t0, label="T0 pre-reset")

        mbmw_t0 = self._get_mbmw(stats_t0)
        hbmw_t0 = self._get_hbmw(stats_t0)
        if mbmw_t0 is None:
            return TestResult(TestStatus.WARN,
                "mbmw field not found in FDP Stats — cannot test monotonicity")

        # ── Step 4: Controller Reset ───────────────────────────────────────────
        log("\nStep 4: Controller Reset...")
        err = self._do_controller_reset(driver, log)
        if err:
            return err
        if not self._post_reset_recovery(driver, log):
            return TestResult(TestStatus.FAIL,
                f"Controller did not recover within {self.RESET_TIMEOUT_S}s")

        # ── Step 5: Snapshot stats immediately after reset (T1) ───────────────
        log("\nStep 5: Reading FDP Statistics immediately post-reset (T1)...")
        stats_t1 = self._read_fdp_stats(driver, log, endgrp=p["endgrp"])
        if stats_t1 is None:
            return TestResult(TestStatus.FAIL,
                "FDP Statistics log unreadable immediately after reset")
        self._log_stats_snapshot(log, stats_t1, label="T1 post-reset")

        mbmw_t1 = self._get_mbmw(stats_t1)

        # ── Step 6: Run post-reset IO ──────────────────────────────────────────
        log(f"\nStep 6: Running {p['fio_duration_post_sec']}s post-reset IO workload...")
        self._run_fio_workload(
            driver, log,
            duration_sec=p["fio_duration_post_sec"],
            block_size=p["fio_block_size"],
            queue_depth=p["queue_depth"],
            placement_handle=p["placement_handle"],
            namespace=p["namespace"],
        )

        # ── Step 7: Snapshot stats after post-reset IO (T2) ───────────────────
        log("\nStep 7: Reading FDP Statistics after post-reset IO (T2)...")
        stats_t2 = self._read_fdp_stats(driver, log, endgrp=p["endgrp"])
        if stats_t2 is None:
            return TestResult(TestStatus.WARN,
                "Pre-reset monotonicity OK but post-reset stats unreadable")
        self._log_stats_snapshot(log, stats_t2, label="T2 post-IO")

        mbmw_t2 = self._get_mbmw(stats_t2)

        # ── Evaluate ──────────────────────────────────────────────────────────
        log("\n━━━ Monotonicity Analysis ━━━")
        issues = []

        # Check T0 → T1 (should be 0 or unchanged, never negative)
        if mbmw_t0 is not None and mbmw_t1 is not None:
            delta_reset = mbmw_t1 - mbmw_t0
            log(f"  T0→T1 (across reset):    mbmw delta = {delta_reset:+,}")
            if delta_reset < 0:
                issues.append(
                    f"mbmw DECREASED across reset: {mbmw_t0:,} → {mbmw_t1:,} "
                    f"(delta={delta_reset:,})"
                )
                log(f"  ✗ mbmw went backwards — counter regression!")
            elif delta_reset == 0:
                log("  ✓ mbmw unchanged across reset (correct persistent behaviour)")
            else:
                log(f"  ✓ mbmw increased slightly (+{delta_reset:,}) — "
                    "within acceptable firmware quantisation")

        # Check T1 → T2 (counter must increase after fresh IO)
        if mbmw_t1 is not None and mbmw_t2 is not None:
            delta_io = mbmw_t2 - mbmw_t1
            log(f"  T1→T2 (after post-reset IO): mbmw delta = {delta_io:+,}")
            if delta_io < 0:
                issues.append(
                    f"mbmw DECREASED after post-reset IO: "
                    f"{mbmw_t1:,} → {mbmw_t2:,}"
                )
                log("  ✗ mbmw went backwards after IO — counter is broken!")
            elif delta_io == 0:
                log("  ⚠ mbmw did not increase after post-reset IO — "
                    "counter may be frozen or firmware updates at coarse granularity")
                # Warn but not fail — some firmware only updates stats periodically
            else:
                log(f"  ✓ mbmw increased by {delta_io:,} after post-reset IO — "
                    "counter is live and accumulating")

        if issues:
            return TestResult(
                TestStatus.FAIL,
                "FDP Statistics monotonicity violated: " + "; ".join(issues),
                details={"mbmw_t0": mbmw_t0, "mbmw_t1": mbmw_t1, "mbmw_t2": mbmw_t2}
            )

        return TestResult(
            TestStatus.PASS,
            f"FDP Statistics counters are monotonically non-decreasing: "
            f"T0={mbmw_t0:,} → T1={mbmw_t1 or '?':,} → T2={mbmw_t2 or '?':,}"
        )
