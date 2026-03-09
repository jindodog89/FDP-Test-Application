"""
Test: fdp_handle_capacity_exhaustion (extra — not in original list)
Write enough data to a single placement handle to exhaust its reclaim unit,
then verify the device either triggers a new reclaim unit assignment (RUHU)
or returns an appropriate status. Tests the handle rotation/wraparound behavior.
"""

import subprocess
from tests.base_test import BaseTest, TestResult, TestStatus


class TestFDPHandleCapacityExhaustion(BaseTest):
    test_id = "fdp_handle_capacity_exhaustion"
    name = "FDP Handle Capacity Exhaustion"
    description = (
        "Writes data to a single placement handle until the reclaim unit's "
        "remaining capacity (RUAMW) reaches zero, then checks whether the device "
        "automatically assigns a new reclaim unit (RUHU) or surfaces an event. "
        "Validates reclaim unit rotation behavior per FDP spec."
    )
    category = "Endurance"
    tags = ["write", "exhaustion", "ruhu", "ruhs", "capacity", "rotation"]

    DEFAULT_PARAMS = {
        "placement_handle": 0,
        "namespace":        1,
        "max_iterations":   500,    # Safety cap to avoid infinite loop
        "block_size_bytes": 4096,
    }

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: Check initial capacity ────────────────────────────────────
        log(f"Step 1: Reading initial capacity for handle {p['placement_handle']}...")
        ruhs_result = driver.fdp_ruhs(ns=p["namespace"])
        if ruhs_result["rc"] != 0:
            return TestResult(TestStatus.FAIL, f"Cannot read RUHS: {ruhs_result['stderr'].strip()}")

        ruhs = driver.extract_ruhs(ruhs_result)
        handle = self._find_handle(ruhs, p["placement_handle"])
        if handle is None:
            return TestResult(TestStatus.FAIL, f"Handle {p['placement_handle']} not found in RUHS")

        initial_cap = int(handle.get("ruamw", handle.get("RUAMWSectors", 0)))
        log(f"  Handle {p['placement_handle']} initial capacity: {initial_cap:,} sectors")

        if initial_cap == 0:
            return TestResult(TestStatus.SKIP, "Handle already at 0 capacity — reset device state before running")

        # Estimate iterations needed (each write = 1 block = block_size/sector_size sectors)
        sector_size = 4096  # Assume 4K sectors for this device
        sectors_per_write = p["block_size_bytes"] // sector_size
        estimated_writes = (initial_cap // sectors_per_write) + 1
        log(f"  Estimated writes to exhaust: {estimated_writes:,} (capped at {p['max_iterations']})")

        if estimated_writes > p["max_iterations"]:
            return TestResult(
                TestStatus.SKIP,
                f"Handle has {initial_cap:,} sectors remaining — would require {estimated_writes:,} writes "
                f"to exhaust (max_iterations={p['max_iterations']}). Increase max_iterations or use a "
                "handle with less remaining capacity."
            )

        # ── Step 2: Write until capacity is exhausted ─────────────────────────
        log(f"\nStep 2: Writing to handle {p['placement_handle']} until capacity exhausted...")
        iteration = 0
        cap_at_start_of_batch = initial_cap
        ruhu_triggered = False

        while iteration < p["max_iterations"]:
            result = driver.run_cmd([
                "write", driver.device,
                f"--namespace-id={p['namespace']}",
                "--start-block=0",
                "--block-count=0",
                f"--data-size={p['block_size_bytes']}",
                "--data=/dev/zero",
                "--dtype=2",
                f"--dspec={p['placement_handle']}",
            ], json_out=False)

            iteration += 1

            if result["rc"] != 0:
                stderr = result["stderr"].strip().lower()
                # Check if device rejected because capacity is full
                if any(k in stderr for k in ("capacity", "full", "enospc", "no space")):
                    log(f"  Iteration {iteration}: Device rejected write (capacity full) ✓")
                    break
                log(f"  Iteration {iteration}: Write error (rc={result['rc']}): {result['stderr'].strip()[:80]}")
                break

            # Periodically check capacity
            if iteration % max(1, estimated_writes // 10) == 0 or iteration == 1:
                ruhs_check = driver.fdp_ruhs(ns=p["namespace"])
                if ruhs_check["rc"] == 0:
                    ruhs_cur = driver.extract_ruhs(ruhs_check)
                    h = self._find_handle(ruhs_cur, p["placement_handle"])
                    if h:
                        cur_cap = int(h.get("ruamw", h.get("RUAMWSectors", 0)))
                        ruhu = h.get("ruhu", h.get("RUHU", None))
                        log(f"  Iteration {iteration}: capacity={cur_cap:,}  ruhu={ruhu}")
                        if cur_cap == 0:
                            log(f"  Capacity reached 0 at iteration {iteration}")
                            break
                        # Detect RUHU (new reclaim unit assigned)
                        if ruhu and str(ruhu) not in ("0", "false", "False", "None"):
                            log(f"  ✓ RUHU triggered at iteration {iteration} — device assigned new reclaim unit")
                            ruhu_triggered = True
                            break

        log(f"\n  Completed {iteration} write(s)")

        # ── Step 3: Final RUHS read ───────────────────────────────────────────
        log("\nStep 3: Final RUHS read...")
        final_ruhs_result = driver.fdp_ruhs(ns=p["namespace"])
        final_cap = None
        if final_ruhs_result["rc"] == 0:
            final_ruhs = driver.extract_ruhs(final_ruhs_result)
            final_handle = self._find_handle(final_ruhs, p["placement_handle"])
            if final_handle:
                final_cap = int(final_handle.get("ruamw", final_handle.get("RUAMWSectors", 0)))
                log(f"  Final capacity: {final_cap:,} sectors")

        details = {
            "iterations": iteration,
            "initial_capacity": initial_cap,
            "final_capacity": final_cap,
            "ruhu_triggered": ruhu_triggered,
        }

        if ruhu_triggered:
            return TestResult(
                TestStatus.PASS,
                f"Device correctly triggered RUHU (new reclaim unit assignment) "
                f"after {iteration} write(s)",
                details=details
            )

        if final_cap is not None and final_cap == 0:
            return TestResult(
                TestStatus.PASS,
                f"Handle capacity reached 0 after {iteration} write(s) — "
                "exhaustion behavior confirmed (RUHU may be triggered on next write)",
                details=details
            )

        consumed = initial_cap - (final_cap or 0)
        return TestResult(
            TestStatus.WARN,
            f"Wrote {iteration} time(s), consumed {consumed:,} sectors. "
            "Capacity not fully exhausted within iteration limit.",
            details=details
        )

    def _find_handle(self, ruhs: list, handle_id: int) -> dict:
        for ruh in ruhs:
            candidate = ruh.get("phndl", ruh.get("PlacementHandle", ruh.get("ruhid", None)))
            if candidate is not None and int(candidate) == handle_id:
                return ruh
        return None
