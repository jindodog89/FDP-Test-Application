"""
Central test registry — add new test classes here and they automatically
appear in the web UI. Import order determines default display order.
"""

# ── Basic / status tests ──────────────────────────────────────────────────────
from tests.basic.test_fdp_status       import TestFDPStatus
from tests.basic.test_fdp_configs      import TestFDPConfigs
from tests.basic.test_placement_ids    import TestPlacementIDs
from tests.basic.test_reclaim_units    import TestReclaimUnits
from tests.basic.test_fdp_events       import TestFDPEvents

# ── IO write tests ────────────────────────────────────────────────────────────
from tests.io.test_nvme_write_valid_pid       import TestNVMeWriteValidPID
from tests.io.test_nvme_write_user_controlled import TestNVMeWriteUserControlled
from tests.io.test_nvme_write_invalid_pid     import TestNVMeWriteInvalidPID
from tests.io.test_nvme_write_legacy          import TestNVMeWriteLegacy

# ── IO Management tests ───────────────────────────────────────────────────────
from tests.io.test_io_mgmt_send_valid         import TestIOMgmtSendValid
from tests.io.test_io_mgmt_send_invalid       import TestIOMgmtSendInvalid
from tests.io.test_io_mgmt_receive_valid      import TestIOMgmtReceiveValid
from tests.io.test_io_mgmt_fdp_disabled       import TestIOMgmtFDPDisabled

# ── Endurance / advanced tests ────────────────────────────────────────────────
from tests.io.test_fdp_endurance              import TestFDPEndurance
from tests.io.test_fdp_multi_handle_isolation import TestFDPMultiHandleIsolation
from tests.io.test_fdp_handle_exhaustion      import TestFDPHandleCapacityExhaustion

# ── Reset: FDP enable persistence ────────────────────────────────────────────
from tests.reset.test_fdp_enable_persist_ctrl_reset      import TestFDPEnablePersistCtrlReset
from tests.reset.test_fdp_enable_persist_subsystem_reset import TestFDPEnablePersistSubsystemReset
from tests.reset.test_fdp_enable_persist_device_reset    import TestFDPEnablePersistDeviceReset

# ── Reset: FDP statistics persistence ────────────────────────────────────────
from tests.reset.test_fdp_stats_persist_ctrl_reset       import TestFDPStatsPersistCtrlReset
from tests.reset.test_fdp_stats_persist_subsystem_reset  import TestFDPStatsPersistSubsystemReset
from tests.reset.test_fdp_stats_persist_device_reset     import TestFDPStatsPersistDeviceReset

# ── Reset: Directive, mapping and disable persistence ────────────────────────
from tests.reset.test_fdp_directives_persist_reset       import TestFDPDirectivesPersistReset
from tests.reset.test_ph_ruh_mapping_persistence         import TestPHToRUHMappingPersistence
from tests.reset.test_fdp_disable_persistence            import TestFDPDisablePersistenceAcrossReset

# ── Reset: Additional persistence coverage ───────────────────────────────────
from tests.reset.test_fdp_config_index_persistence       import TestFDPConfigIndexPersistence
from tests.reset.test_fdp_stats_monotonicity             import TestFDPStatsMonotonicity
from tests.reset.test_fdp_event_log_persistence          import TestFDPEventLogPersistReset

# ── Admin: Identify Controller ────────────────────────────────────────────────
from tests.admin.test_admin_identify_fdps                import TestAdminIdentifyFDPS
from tests.admin.test_admin_identify_fcm                 import TestAdminIdentifyFCM
from tests.admin.test_admin_identify_vwc_global          import TestAdminIdentifyVWCGlobal
from tests.admin.test_admin_identify_vwc_flush           import TestAdminIdentifyVWCFlush
from tests.admin.test_admin_identify_fdps_command_set    import TestAdminIdentifyFDPSCommandSet

# ── Admin: FDP Enable / Disable ───────────────────────────────────────────────
from tests.admin.test_admin_enable_fdp_empty             import TestAdminEnableFDPEmpty
from tests.admin.test_admin_enable_fdp_with_ns           import TestAdminEnableFDPWithNS
from tests.admin.test_admin_enable_fdp_invalid_config    import TestAdminEnableFDPInvalidConfig
from tests.admin.test_admin_disable_fdp_stats_clear      import TestAdminDisableFDPStatsClear

# ── Admin: Namespace Management ───────────────────────────────────────────────
from tests.admin.test_admin_create_ns_valid_phl          import TestAdminCreateNSValidPHL
from tests.admin.test_admin_create_ns_invalid_phl        import TestAdminCreateNSInvalidPHL

# ── Admin: Log Page reads ─────────────────────────────────────────────────────
from tests.admin.test_admin_read_fdp_configs_log         import TestAdminReadFDPConfigsLog
from tests.admin.test_admin_read_fdp_stats               import TestAdminReadFDPStats
from tests.admin.test_admin_partial_log_page_read        import TestAdminPartialLogPageRead

# ── Admin: Log Page validation ────────────────────────────────────────────────
from tests.admin.test_admin_validate_fdp_configs_header      import TestAdminValidateFDPConfigsHeader
from tests.admin.test_admin_validate_fdp_config_desc_header  import TestAdminValidateFDPConfigDescHeader
from tests.admin.test_admin_validate_fdp_attributes          import TestAdminValidateFDPAttributes
from tests.admin.test_admin_validate_reclaim_resources       import TestAdminValidateReclaimResources
from tests.admin.test_admin_validate_maxpid                  import TestAdminValidateMAXPID
from tests.admin.test_admin_validate_rgif                    import TestAdminValidateRGIF

# ── Admin: FDP Statistics ─────────────────────────────────────────────────────
from tests.admin.test_admin_validate_fdp_stats_monotonicity  import TestAdminValidateFDPStatsMonotonicity
from tests.admin.test_admin_validate_hbw_accuracy            import TestAdminValidateHBWAccuracy
from tests.admin.test_admin_calculate_waf                    import TestAdminCalculateWAF
from tests.admin.test_admin_dwpd_calculation                 import TestAdminDWPDCalculation

# ── Admin: FDP Events ─────────────────────────────────────────────────────────
from tests.admin.test_admin_validate_event_log_header        import TestAdminValidateEventLogHeader
from tests.admin.test_admin_validate_event_invalid_pid       import TestAdminValidateEventInvalidPID
from tests.admin.test_admin_validate_event_masking           import TestAdminValidateEventMasking
from tests.admin.test_admin_validate_event_ordering          import TestAdminValidateEventOrdering
from tests.admin.test_admin_event_log_retention              import TestAdminEventLogRetention


ALL_TESTS = [
    # ── Basic / status ────────────────────────────────────────────────────────
    TestFDPStatus,
    TestFDPConfigs,
    TestPlacementIDs,
    TestReclaimUnits,
    TestFDPEvents,

    # ── IO write ──────────────────────────────────────────────────────────────
    TestNVMeWriteValidPID,
    TestNVMeWriteUserControlled,
    TestNVMeWriteInvalidPID,
    TestNVMeWriteLegacy,

    # ── IO Management ─────────────────────────────────────────────────────────
    TestIOMgmtSendValid,
    TestIOMgmtSendInvalid,
    TestIOMgmtReceiveValid,
    TestIOMgmtFDPDisabled,

    # ── Endurance / advanced ──────────────────────────────────────────────────
    TestFDPEndurance,
    TestFDPMultiHandleIsolation,
    TestFDPHandleCapacityExhaustion,

    # ── Reset: FDP enable persistence ─────────────────────────────────────────
    TestFDPEnablePersistCtrlReset,
    TestFDPEnablePersistSubsystemReset,
    TestFDPEnablePersistDeviceReset,

    # ── Reset: FDP statistics persistence ─────────────────────────────────────
    TestFDPStatsPersistCtrlReset,
    TestFDPStatsPersistSubsystemReset,
    TestFDPStatsPersistDeviceReset,

    # ── Reset: Directives, mapping, disable ───────────────────────────────────
    TestFDPDirectivesPersistReset,
    TestPHToRUHMappingPersistence,
    TestFDPDisablePersistenceAcrossReset,

    # ── Reset: Additional coverage ────────────────────────────────────────────
    TestFDPConfigIndexPersistence,
    TestFDPStatsMonotonicity,
    TestFDPEventLogPersistReset,

    # ── Admin: Identify Controller ────────────────────────────────────────────
    TestAdminIdentifyFDPS,
    TestAdminIdentifyFCM,
    TestAdminIdentifyVWCGlobal,
    TestAdminIdentifyVWCFlush,
    TestAdminIdentifyFDPSCommandSet,

    # ── Admin: FDP Enable / Disable ───────────────────────────────────────────
    TestAdminEnableFDPEmpty,
    TestAdminEnableFDPWithNS,
    TestAdminEnableFDPInvalidConfig,
    TestAdminDisableFDPStatsClear,

    # ── Admin: Namespace Management ───────────────────────────────────────────
    TestAdminCreateNSValidPHL,
    TestAdminCreateNSInvalidPHL,

    # ── Admin: Log Page reads ─────────────────────────────────────────────────
    TestAdminReadFDPConfigsLog,
    TestAdminReadFDPStats,
    TestAdminPartialLogPageRead,

    # ── Admin: Log Page validation ────────────────────────────────────────────
    TestAdminValidateFDPConfigsHeader,
    TestAdminValidateFDPConfigDescHeader,
    TestAdminValidateFDPAttributes,
    TestAdminValidateReclaimResources,
    TestAdminValidateMAXPID,
    TestAdminValidateRGIF,

    # ── Admin: FDP Statistics ─────────────────────────────────────────────────
    TestAdminValidateFDPStatsMonotonicity,
    TestAdminValidateHBWAccuracy,
    TestAdminCalculateWAF,
    TestAdminDWPDCalculation,

    # ── Admin: FDP Events ─────────────────────────────────────────────────────
    TestAdminValidateEventLogHeader,
    TestAdminValidateEventInvalidPID,
    TestAdminValidateEventMasking,
    TestAdminValidateEventOrdering,
    TestAdminEventLogRetention,
]


def get_test_by_id(test_id: str):
    return next((cls for cls in ALL_TESTS if cls.test_id == test_id), None)