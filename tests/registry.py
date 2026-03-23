"""
Central test registry — add new test classes here and they automatically
appear in the web UI. Import order determines default display order.
"""

# ── Basic / status tests (B series) ──────────────────────────────────────────
from tests.basic.B1_FDP_Status_Check                    import TestFDPStatus
from tests.basic.B2_FDP_Configurations_Enumeration      import TestFDPConfigs
from tests.basic.B3_Placement_Identifier_Verification   import TestPlacementIDs
from tests.basic.B4_Reclaim_Unit_Handle_Status          import TestReclaimUnits
from tests.basic.B5_FDP_Events_Log                      import TestFDPEvents

# ── IO write tests (I series) ─────────────────────────────────────────────────
from tests.io.I1_NVMe_Write_Valid_Placement_ID          import TestNVMeWriteValidPID
from tests.io.I2_NVMe_Write_Invalid_Placement_ID        import TestNVMeWriteInvalidPID
from tests.io.I3_NVMe_Write_User_Controlled_Parameters  import TestNVMeWriteUserControlled
from tests.io.I4_NVMe_Write_Legacy                      import TestNVMeWriteLegacy

# ── IO Management tests (I series) ────────────────────────────────────────────
from tests.io.I8_IO_Mgmt_Recv_Valid                     import TestIOMgmtReceiveValid
from tests.io.I9_IO_Mgmt_Recv_Invalid                   import TestIOMgmtFDPDisabled
from tests.io.I10_IO_Mgmt_Send_Valid                    import TestIOMgmtSendValid
from tests.io.I11_IO_Mgmt_Send_Invalid                  import TestIOMgmtSendInvalid

# ── Endurance / advanced tests (I series) ────────────────────────────────────
from tests.io.I5_Endurance_WAF_Calculation              import TestFDPEndurance
from tests.io.I6_Multi_Handle_Isolation                  import TestFDPMultiHandleIsolation
from tests.io.I7_Placement_Handle_Capacity_Exhaustion   import TestFDPHandleCapacityExhaustion

# ── Reset: FDP enable persistence (R series) ─────────────────────────────────
from tests.reset.R1_FDP_Enable_Persistence_Ctrl_Reset   import TestFDPEnablePersistCtrlReset
from tests.reset.R2_FDP_Enable_Persistence_Link_Reset   import TestFDPEnablePersistDeviceReset
from tests.reset.R3_FDP_Enable_Persistence_NSSR         import TestFDPEnablePersistSubsystemReset

# ── Reset: FDP statistics persistence (R series) ─────────────────────────────
from tests.reset.R5_FDP_Stats_Persistence_Ctrl_Reset    import TestFDPStatsPersistCtrlReset
from tests.reset.R6_FDP_Stats_Persistence_Link_Reset    import TestFDPStatsPersistDeviceReset
from tests.reset.R7_FDP_Stats_Persistence_NSSR          import TestFDPStatsPersistSubsystemReset

# ── Reset: Additional persistence (R series) ─────────────────────────────────
from tests.reset.R4_FDP_Disable_Persistence             import TestFDPDisablePersistenceAcrossReset
from tests.reset.R8_FDP_Stats_Monotonicity              import TestFDPStatsMonotonicity
from tests.reset.R9_FDP_Configs_Persistence             import TestFDPConfigIndexPersistence
from tests.reset.R10_Directives_Persistence             import TestFDPDirectivesPersistReset
from tests.reset.R11_FDP_Event_Log_Persistence          import TestFDPEventLogPersistReset
from tests.reset.R12_PH_to_RUH_Mapping_Persistence      import TestPHToRUHMappingPersistence

# ── Admin: Identify Controller (A series) ────────────────────────────────────
from tests.admin.A1_Validate_FDPS_Bit_in_Identify_Ctrl  import TestAdminIdentifyFDPS
from tests.admin.A14_Identify_Fixed_Capacity_Management import TestAdminIdentifyFCM
from tests.admin.A17_Identify_VWC_Global                import TestAdminIdentifyVWCGlobal
from tests.admin.A16_Identify_VWC_Flush_Behavior        import TestAdminIdentifyVWCFlush
from tests.admin.A15_Identify_FDPS_Command_Set_Consistency import TestAdminIdentifyFDPSCommandSet

# ── Admin: FDP Enable / Disable (A series) ───────────────────────────────────
from tests.admin.A20_Enable_FDP_on_Empty_Endgrp         import TestAdminEnableFDPEmpty
from tests.admin.A22_Enable_FDP_with_NS                 import TestAdminEnableFDPWithNS
from tests.admin.A21_Enable_FDP_Invalid_Config          import TestAdminEnableFDPInvalidConfig
from tests.admin.A27_Disable_FDP_Stats_Clear            import TestAdminDisableFDPStatsClear

# ── Admin: Namespace Management (A series) ───────────────────────────────────
from tests.admin.A19_Create_NS_Valid_PHL                import TestAdminCreateNSValidPHL
from tests.admin.A18_Create_NS_Invalid_PHL              import TestAdminCreateNSInvalidPHL

# ── Admin: Log Page reads (A series) ─────────────────────────────────────────
from tests.admin.A25_Read_FDP_Configs_Log               import TestAdminReadFDPConfigsLog
from tests.admin.A26_Read_FDP_Stats                     import TestAdminReadFDPStats
from tests.admin.A24_Partial_Log_Page_Read              import TestAdminPartialLogPageRead

# ── Admin: Log Page validation (A series) ────────────────────────────────────
from tests.admin.A2_Validate_FDP_Configs_Header         import TestAdminValidateFDPConfigsHeader
from tests.admin.A3_Validate_FDP_Config_Desc_Header     import TestAdminValidateFDPConfigDescHeader
from tests.admin.A5_Validate_FDP_Attributes             import TestAdminValidateFDPAttributes
from tests.admin.A7_Validate_Reclaim_Resources          import TestAdminValidateReclaimResources
from tests.admin.A6_Validate_Max_Placement_Identifiers  import TestAdminValidateMAXPID
from tests.admin.A8_Validate_Reclaim_Group_Identifier_Format import TestAdminValidateRGIF

# ── Admin: FDP Statistics (A series) ─────────────────────────────────────────
from tests.admin.A13_Validate_FDP_Stats_Monotonicity    import TestAdminValidateFDPStatsMonotonicity
from tests.admin.A10_Validate_Host_Bytes_Written_Accuracy import TestAdminValidateHBWAccuracy
from tests.admin.A28_Calculate_WAF                      import TestAdminCalculateWAF
from tests.admin.A29_DWPD_Calculation                   import TestAdminDWPDCalculation

# ── Admin: FDP Events (A series) ─────────────────────────────────────────────
from tests.admin.A4_Validate_Event_Log_Header           import TestAdminValidateEventLogHeader
from tests.admin.A9_Validate_Event_Descriptor_Invalid_PID import TestAdminValidateEventInvalidPID
from tests.admin.A11_Validate_Event_Masking_Disabled    import TestAdminValidateEventMasking
from tests.admin.A12_Validate_Event_Timestamp_and_Ordering import TestAdminValidateEventOrdering
from tests.admin.A23_Event_Log_Retention                import TestAdminEventLogRetention


ALL_TESTS = [
    # ── Basic / status ────────────────────────────────────────────────────────
    TestFDPStatus,
    TestFDPConfigs,
    TestPlacementIDs,
    TestReclaimUnits,
    TestFDPEvents,

    # ── IO write ──────────────────────────────────────────────────────────────
    TestNVMeWriteValidPID,
    TestNVMeWriteInvalidPID,
    TestNVMeWriteUserControlled,
    TestNVMeWriteLegacy,

    # ── IO Management ─────────────────────────────────────────────────────────
    TestIOMgmtReceiveValid,
    TestIOMgmtFDPDisabled,
    TestIOMgmtSendValid,
    TestIOMgmtSendInvalid,

    # ── Endurance / advanced ──────────────────────────────────────────────────
    TestFDPEndurance,
    TestFDPMultiHandleIsolation,
    TestFDPHandleCapacityExhaustion,

    # ── Reset: FDP enable persistence ─────────────────────────────────────────
    TestFDPEnablePersistCtrlReset,
    TestFDPEnablePersistDeviceReset,
    TestFDPEnablePersistSubsystemReset,

    # ── Reset: FDP statistics persistence ─────────────────────────────────────
    TestFDPStatsPersistCtrlReset,
    TestFDPStatsPersistDeviceReset,
    TestFDPStatsPersistSubsystemReset,

    # ── Reset: Additional persistence ─────────────────────────────────────────
    TestFDPDisablePersistenceAcrossReset,
    TestFDPStatsMonotonicity,
    TestFDPConfigIndexPersistence,
    TestFDPDirectivesPersistReset,
    TestFDPEventLogPersistReset,
    TestPHToRUHMappingPersistence,

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