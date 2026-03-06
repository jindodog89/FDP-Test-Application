"""
Test: fdp_directives_persistent_across_reset

Uses the Directive Receive command (Type 00h / Identify, Operation 01h) to
verify that the Data Placement Directive is:
  a) Supported by the controller
  b) Marked as "Persistent Across Controller Level Resets"

Then performs a Controller Reset and confirms the Supported bit is still set.

Per NVMe TP4146, Data Placement Directive support is an inherent controller
capability and MUST be persistent across all controller-level resets.

The Identify Directive response (DTYP 00h, DOPER 01h) returns a 4096-byte
structure where each byte corresponds to a directive type:
  Byte 0 = Identify Directive (type 0x00)
  Byte 1 = Streams Directive (type 0x01)
  Byte 2 = Data Placement Directive (type 0x02)

Each byte encodes:
  Bit 0 = Directives Supported
  Bit 1 = Directives Enabled
  Bit 2 = Persistent Across Controller Level Resets

Pass criteria : Supported + Persistent bits set before reset; Supported bit
               still set after Controller Reset.
Warn criteria : Persistent bit not set (capability mis-declared by firmware).
Fail criteria : Supported bit absent, or absent after reset.
Skip criteria : FDP not enabled, or Directive Receive command not supported.
"""

import time
from tests.base_test import BaseTest, TestResult, TestStatus
from tests.fdp.reset_base import ResetTestBase


class TestFDPDirectivesPersistReset(ResetTestBase, BaseTest):
    test_id   = "fdp_directives_persistent_across_reset"
    name      = "FDP Directives — Controller Reset Persistence"
    description = (
        "Sends a Directive Receive (Type 00h Identify, Operation 01h) command "
        "to read the directive capability structure, verifies that the Data "
        "Placement Directive (type 0x02) has the 'Directives Supported' and "
        "'Persistent Across Controller Level Resets' bits set, then performs "
        "a Controller Reset and confirms the Supported bit is still present."
    )
    category = "Reset"
    tags     = ["reset", "controller-reset", "directives", "data-placement",
                "dir-receive", "persistence"]

    DEFAULT_PARAMS = {
        "namespace": 1,
        "endgrp":    1,
    }

    # Directive type identifiers
    DTYPE_IDENTIFY       = 0x00
    DTYPE_STREAMS        = 0x01
    DTYPE_DATA_PLACEMENT = 0x02

    # Bits within each directive capability byte
    BIT_SUPPORTED   = 0x01
    BIT_ENABLED     = 0x02
    BIT_PERSISTENT  = 0x04

    def run(self, driver, log) -> TestResult:
        p = {**self.DEFAULT_PARAMS, **getattr(self, "params", {})}

        # ── Step 1: Confirm FDP is enabled ────────────────────────────────────
        log("Step 1: Checking FDP enable state...")
        skip = self._assert_fdp_enabled(driver, log, endgrp=p["endgrp"])
        if skip:
            return skip

        # ── Step 2: Send Directive Receive (Identify) ─────────────────────────
        log("\nStep 2: Sending Directive Receive — Type 00h (Identify), "
            "Operation 01h (Return Parameters)...")
        dir_data_before = self._read_identify_directive(
            driver, log, namespace=p["namespace"]
        )
        if dir_data_before is None:
            return TestResult(
                TestStatus.SKIP,
                "Directive Receive command not supported or failed. "
                "Device may not implement the Identify Directive."
            )

        log(f"  Raw directive data: {dir_data_before}")

        # ── Step 3: Check Data Placement Directive capability bits ─────────────
        log("\nStep 3: Inspecting Data Placement Directive capability bits...")
        dp_caps_before = self._extract_directive_caps(
            dir_data_before, self.DTYPE_DATA_PLACEMENT, log, label="pre-reset"
        )

        if dp_caps_before is None:
            return TestResult(
                TestStatus.FAIL,
                "Could not extract Data Placement Directive capability from "
                "Identify Directive response. The response structure may be "
                "non-standard or the directive is not implemented."
            )

        supported_before  = bool(dp_caps_before & self.BIT_SUPPORTED)
        persistent_before = bool(dp_caps_before & self.BIT_PERSISTENT)
        enabled_before    = bool(dp_caps_before & self.BIT_ENABLED)

        log(f"  Data Placement Directive caps byte: 0x{dp_caps_before:02x}")
        log(f"    Supported:  {'✓' if supported_before else '✗'} ({int(supported_before)})")
        log(f"    Enabled:    {'✓' if enabled_before else '–'} ({int(enabled_before)})")
        log(f"    Persistent: {'✓' if persistent_before else '✗'} ({int(persistent_before)})")

        if not supported_before:
            return TestResult(
                TestStatus.FAIL,
                "Data Placement Directive 'Directives Supported' bit is NOT set "
                "before reset. Controller does not report FDP directive support "
                "via the Identify Directive — firmware defect."
            )

        if not persistent_before:
            log("  ⚠ 'Persistent Across Controller Level Resets' bit NOT set — "
                "this may indicate a firmware declaration error")
            # Continue the test — the reset will reveal the true behaviour

        # ── Step 4: Controller Reset ───────────────────────────────────────────
        log("\nStep 4: Issuing NVMe Controller Reset...")
        err = self._do_controller_reset(driver, log)
        if err:
            return err

        # ── Step 5: Wait for recovery ──────────────────────────────────────────
        log("\nStep 5: Waiting for controller to recover...")
        if not self._post_reset_recovery(driver, log):
            return TestResult(
                TestStatus.FAIL,
                f"Controller did not respond within {self.RESET_TIMEOUT_S}s "
                "after Controller Reset"
            )

        # ── Step 6: Re-read Identify Directive and check Supported bit ─────────
        log("\nStep 6: Re-reading Identify Directive post-reset...")
        dir_data_after = self._read_identify_directive(
            driver, log, namespace=p["namespace"]
        )
        if dir_data_after is None:
            return TestResult(
                TestStatus.FAIL,
                "Directive Receive command failed after Controller Reset — "
                "directive functionality may have been lost."
            )

        dp_caps_after    = self._extract_directive_caps(
            dir_data_after, self.DTYPE_DATA_PLACEMENT, log, label="post-reset"
        )
        supported_after  = bool((dp_caps_after or 0) & self.BIT_SUPPORTED)
        persistent_after = bool((dp_caps_after or 0) & self.BIT_PERSISTENT)

        log(f"\n  Data Placement Directive caps byte post-reset: "
            f"0x{dp_caps_after or 0:02x}")
        log(f"    Supported:  {'✓' if supported_after else '✗'}")
        log(f"    Persistent: {'✓' if persistent_after else '✗'}")

        # ── Evaluate ──────────────────────────────────────────────────────────
        if not supported_after:
            return TestResult(
                TestStatus.FAIL,
                "Data Placement Directive 'Directives Supported' bit is CLEARED "
                "after Controller Reset — directive capability was lost. "
                "This is a firmware defect."
            )

        if not persistent_before:
            # Supported bit survived reset even though persistent bit wasn't set
            return TestResult(
                TestStatus.WARN,
                "Data Placement Directive Supported bit persisted across reset, "
                "but the 'Persistent Across Controller Level Resets' capability "
                "bit was not declared before reset. Firmware should set this bit."
            )

        return TestResult(
            TestStatus.PASS,
            "Data Placement Directive is supported and correctly declared as "
            "persistent, and the Supported bit remained set after Controller Reset"
        )

    # ── Helper ────────────────────────────────────────────────────────────────

    def _extract_directive_caps(self, data: dict, dtype: int,
                                 log, label: str = "") -> int | None:
        """
        Extract the capability byte for a specific directive type from the
        Identify Directive Return Parameters response.

        nvme-cli returns the structure in several possible shapes:
          1. {"directives": [{"dtype": 0, "doper": 0, "fdir": X}, ...]}
          2. {"dtype_00h": {"dp_dir_supported": 1, ...}}
          3. Raw list of bytes in a "data" field
          4. Direct key like "data_placement_supported"

        We handle all common shapes and fall back to raw byte extraction.
        """
        tag = f"[{label}] " if label else ""

        if not isinstance(data, dict):
            log(f"  {tag}Unexpected response type: {type(data)}")
            return None

        # Shape 1: list of directive entries
        if "directives" in data:
            for entry in data["directives"]:
                if entry.get("dtype") == dtype or entry.get("type") == dtype:
                    cap_byte = 0
                    if entry.get("doper", entry.get("supported")):
                        cap_byte |= self.BIT_SUPPORTED
                    if entry.get("enabled"):
                        cap_byte |= self.BIT_ENABLED
                    if entry.get("persistent", entry.get("persistent_across_reset")):
                        cap_byte |= self.BIT_PERSISTENT
                    return cap_byte

        # Shape 2: direct keys for data placement directive (type 0x02)
        if dtype == self.DTYPE_DATA_PLACEMENT:
            dp_sup_keys = (
                "dp_dir_supported", "data_placement_supported",
                "DataPlacementSupported", "dp_supported",
            )
            for key in dp_sup_keys:
                if key in data:
                    cap_byte = self.BIT_SUPPORTED if data[key] else 0
                    # Check for persistent flag nearby
                    for pk in ("dp_dir_persistent", "persistent",
                               "persistent_across_resets"):
                        if data.get(pk):
                            cap_byte |= self.BIT_PERSISTENT
                    return cap_byte

        # Shape 3: raw byte array — byte index = directive type
        for arr_key in ("supported_directives", "directive_types", "bytes", "raw"):
            if arr_key in data and isinstance(data[arr_key], (list, bytes)):
                arr = data[arr_key]
                if dtype < len(arr):
                    return int(arr[dtype])

        # Shape 4: flat dict with integer keys (byte offsets)
        if dtype in data:
            return int(data[dtype])
        if str(dtype) in data:
            return int(data[str(dtype)])

        log(f"  {tag}Could not locate directive type 0x{dtype:02x} in response: "
            f"{list(data.keys())[:10]}")
        return None
