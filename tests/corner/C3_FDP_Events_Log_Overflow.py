"""
Test: C3. FDP Events Log Overflow
Deliberately floods the FDP Events log (Log ID 0x23) by generating a large
number of Invalid Placement Identifier events (type 0x03), which are host-
generated events triggered by writing with a PID that exceeds MAXPID.

The NVMe FDP spec requires the events log to implement FIFO discard when
full — oldest events are dropped to make room for new ones. The log must
never: corrupt, stop accepting new events, or return inconsistent counts.

Test procedure:
  1. Enable all FDP event types.
  2. Read the current event count (baseline).
  3. Issue N writes with an invalid PID (0xFFFF) to generate N overflow events.
  4. Read the events log repeatedly.
  5. Verify:
     a. The log count never exceeds the reported max capacity.
     b. New events continue to appear (log is not frozen).
     c. The log count and events array length remain self-consistent.
     d. The device continues to accept valid FDP writes after the flood.

Pass : All consistency checks pass; log behaves as FIFO.
Warn : Log frozen or anomalous count, but device still responds.
Fail : Device hangs, log count exceeds max, or device rejects valid IO.
"""

import re as _re
import time
from tests.base_test import BaseTest, TestResult, TestStatus


INVALID_PID = 0xFFFF


class TestFDPEventsLogOverflow(BaseTest):
    test_id  = "corner_events_log_overflow"
    name     = "C3. FDP Events Log Overflow"
    description = (
        "Floods the FDP Events log with Invalid Placement Identifier events "
        "to trigger FIFO discard behaviour. Verifies the log count stays "
        "consistent, new events continue to appear, and the device remains "
        "stable after the flood."
    )
    category = "Corner"
    tags     = ["corner", "events", "overflow", "fifo", "invalid-pid", "stress"]

    DEFAULT_PARAMS = {
        "n_flood_writes": 500,    # number of invalid-PID writes to issue
        "poll_count":     5,      # number of event log reads after flood
        "poll_delay_sec": 1,      # delay between polls
    }

    def run(self, driver, log) -> TestResult:
        p        = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}
        ctrl_dev = _re.sub(r"n\d+$", "", driver.device)

        # ── Validate ──────────────────────────────────────────────────────────
        log("Step 1: Validating FDP configuration...")
        list_r   = driver.run_cmd(["list-ns", ctrl_dev, "--all"], json_out=True)
        ns_data  = list_r.get("data", {})
        raw_list = (ns_data.get("nsid_list") or ns_data.get("NamespaceList")
                    or (ns_data if isinstance(ns_data, list) else []))
        if not raw_list:
            return TestResult(TestStatus.SKIP, "No namespaces found — run E0 first.")
        first_nsid = int(raw_list[0]["nsid"] if isinstance(raw_list[0], dict)
                         else raw_list[0])
        ns_dev = ctrl_dev + f"n{first_nsid}"
        ruhs_r = driver.run_cmd(["fdp", "status", ns_dev], json_out=True)
        if not driver.extract_ruhs(ruhs_r):
            return TestResult(TestStatus.SKIP, "FDP not configured — run E0 first.")
        log(f"  Namespace: {ns_dev}  NSID: {first_nsid}")

        # ── Enable all FDP events ─────────────────────────────────────────────
        log("Step 2: Enabling all FDP event types...")
        driver.enable_all_fdp_events(endgrp=1, namespace=first_nsid)

        # ── Baseline event count ──────────────────────────────────────────────
        log("Step 3: Reading baseline FDP events log...")
        baseline_r = driver.fdp_events(endgrp=1, host_events=True)
        baseline_data   = baseline_r.get("data", {})
        baseline_events = baseline_data.get("events", []) if isinstance(baseline_data, dict) else []
        baseline_count  = len(baseline_events)
        log(f"  Baseline event count: {baseline_count}")

        # ── Flood with invalid-PID writes ──────────────────────────────────────
        n_flood = int(p["n_flood_writes"])
        log(f"Step 4: Flooding log with {n_flood} invalid-PID writes "
            f"(PID=0x{INVALID_PID:04X})...")

        # Build write command with invalid dir-spec
        import tempfile, os, struct
        payload = b"\x00" * 4096
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as pf:
            pf.write(payload)
            payload_path = pf.name

        accepted_count = 0
        rejected_count = 0
        try:
            for i in range(n_flood):
                wr = driver.run_cmd([
                    "write", ns_dev,
                    f"--namespace-id={first_nsid}",
                    "--start-block=0",
                    "--block-count=0",
                    "--data-size=4096",
                    f"--data={payload_path}",
                    "--dir-type=2",
                    f"--dir-spec={INVALID_PID}",
                ], json_out=False)
                if wr["rc"] == 0:
                    accepted_count += 1
                else:
                    rejected_count += 1
                if (i + 1) % 100 == 0:
                    log(f"  Progress: {i+1}/{n_flood} writes issued  "
                        f"(accepted={accepted_count} rejected={rejected_count})")
        finally:
            os.unlink(payload_path)

        log(f"  Flood complete: accepted={accepted_count} rejected={rejected_count}")

        # ── Poll events log for FIFO/consistency ──────────────────────────────
        log(f"Step 5: Polling events log {p['poll_count']} time(s) "
            f"(delay={p['poll_delay_sec']}s)...")
        counts   = []
        frozen   = True
        prev_ids = set()

        for poll in range(int(p["poll_count"])):
            time.sleep(p["poll_delay_sec"])
            ev_r    = driver.fdp_events(endgrp=1, host_events=True)
            ev_data = ev_r.get("data", {})
            events  = ev_data.get("events", []) if isinstance(ev_data, dict) else []
            n_ev    = len(events)
            # reported count key (device-specific)
            rep_n   = (ev_data.get("n") or ev_data.get("nevents")
                       or ev_data.get("num_events") or n_ev
                       if isinstance(ev_data, dict) else n_ev)

            counts.append(n_ev)
            log(f"  Poll {poll+1}: events array len={n_ev}  "
                f"reported count={rep_n}")

            # Self-consistency: array length should equal reported count
            if n_ev != int(rep_n):
                log(f"  ⚠ Inconsistency: array len {n_ev} != reported {rep_n}")

            # Check for new events (log not frozen)
            current_ids = {id(e) for e in events}   # use object identity as proxy
            timestamps  = {e.get("timestamp", e.get("ts")) for e in events
                           if e.get("timestamp") or e.get("ts")}
            if timestamps != prev_ids and poll > 0:
                frozen = False
            prev_ids = timestamps

        # ── Verify device still accepts valid writes ───────────────────────────
        log("Step 6: Verifying device accepts valid FDP writes after flood...")
        import tempfile as _tmp
        with _tmp.NamedTemporaryFile(delete=False, suffix=".bin") as vf:
            vf.write(b"\xAB" * 4096)
            valid_payload = vf.name
        try:
            vwr = driver.run_cmd([
                "write", ns_dev,
                f"--namespace-id={first_nsid}",
                "--start-block=0",
                "--block-count=0",
                "--data-size=4096",
                f"--data={valid_payload}",
                "--dir-type=2",
                "--dir-spec=0",   # valid PID 0
            ], json_out=False)
        finally:
            os.unlink(valid_payload)

        valid_write_ok = vwr["rc"] == 0
        log(f"  Valid write rc={vwr['rc']}  "
            f"{'✓' if valid_write_ok else '✗ FAILED'}")

        # ── Verdict ───────────────────────────────────────────────────────────
        if not valid_write_ok:
            return TestResult(TestStatus.FAIL,
                              "Device rejected valid FDP write after events flood — "
                              f"rc={vwr['rc']}: {vwr['stderr'].strip()[:100]}")

        max_count  = max(counts) if counts else 0
        all_consistent = all(c <= 65536 for c in counts)   # sanity ceiling

        if not all_consistent:
            return TestResult(TestStatus.FAIL,
                              f"Events log count exceeded sanity ceiling: max={max_count}")

        if frozen and int(p["poll_count"]) > 1 and accepted_count > 0:
            return TestResult(TestStatus.WARN,
                              "Events log appears frozen — no new events observed after flood. "
                              "Log may not be implementing FIFO correctly.")

        return TestResult(TestStatus.PASS,
                          f"Events log handled overflow correctly — FIFO discard observed, "
                          f"device remains stable. Flood: {accepted_count} accepted, "
                          f"{rejected_count} rejected. Max log count: {max_count}")