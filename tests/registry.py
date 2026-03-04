"""
Central test registry — add new test classes here and they automatically
appear in the web UI. Import order determines default display order.
"""

# ── Original basic / status tests ────────────────────────────────────────────
from tests.fdp.test_fdp_status       import TestFDPStatus
from tests.fdp.test_fdp_configs      import TestFDPConfigs
from tests.fdp.test_placement_ids    import TestPlacementIDs
from tests.fdp.test_reclaim_units    import TestReclaimUnits
from tests.fdp.test_fdp_events       import TestFDPEvents

# ── IO write tests ────────────────────────────────────────────────────────────
from tests.fdp.test_nvme_write_valid_pid       import TestNVMeWriteValidPID
from tests.fdp.test_nvme_write_user_controlled import TestNVMeWriteUserControlled
from tests.fdp.test_nvme_write_invalid_pid     import TestNVMeWriteInvalidPID
from tests.fdp.test_nvme_write_legacy          import TestNVMeWriteLegacy

# ── IO Management tests ───────────────────────────────────────────────────────
from tests.fdp.test_io_mgmt_send_valid         import TestIOMgmtSendValid
from tests.fdp.test_io_mgmt_send_invalid       import TestIOMgmtSendInvalid
from tests.fdp.test_io_mgmt_receive_valid      import TestIOMgmtReceiveValid
from tests.fdp.test_io_mgmt_fdp_disabled       import TestIOMgmtFDPDisabled

# ── Endurance / advanced tests ────────────────────────────────────────────────
from tests.fdp.test_fdp_endurance              import TestFDPEndurance
from tests.fdp.test_fdp_multi_handle_isolation import TestFDPMultiHandleIsolation
from tests.fdp.test_fdp_handle_exhaustion      import TestFDPHandleCapacityExhaustion


ALL_TESTS = [
    # Basic / status
    TestFDPStatus,
    TestFDPConfigs,
    TestPlacementIDs,
    TestReclaimUnits,
    TestFDPEvents,

    # IO write
    TestNVMeWriteValidPID,
    TestNVMeWriteUserControlled,
    TestNVMeWriteInvalidPID,
    TestNVMeWriteLegacy,

    # IO Management
    TestIOMgmtSendValid,
    TestIOMgmtSendInvalid,
    TestIOMgmtReceiveValid,
    TestIOMgmtFDPDisabled,

    # Endurance / advanced
    TestFDPEndurance,
    TestFDPMultiHandleIsolation,
    TestFDPHandleCapacityExhaustion,
]


def get_test_by_id(test_id: str):
    return next((cls for cls in ALL_TESTS if cls.test_id == test_id), None)
