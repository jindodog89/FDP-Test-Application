"""
Central test registry — imports and ALL_TESTS list.
Tests are ordered strictly by case number within each category (B, I, R, A).
"""

# ── Endurance (E1–) ─────────────────────────────────────────────
from tests.endurance.E0_Endurance_preconditioning          import TestPreconditioning
from tests.endurance.E1_Endurance_WAF_per_RUH              import TestEnduranceWAF
from tests.endurance.E2_Endurance_WAF_overall              import TestEnduranceWAFAllRUH
from tests.endurance.E3_Endurance_Single_RUH               import TestEnduranceSingleRUH

# ── Basic (B1–B5) ─────────────────────────────────────────────────────────────
from tests.basic.B1_FDP_Status_Check                       import TestFDPStatus
from tests.basic.B2_FDP_Configurations_Enumeration         import TestFDPConfigs
from tests.basic.B3_Placement_Identifier_Verification      import TestPlacementIDs
from tests.basic.B4_Reclaim_Unit_Handle_Status             import TestReclaimUnits
from tests.basic.B5_FDP_Events_Log                         import TestFDPEvents
from tests.basic.B6_FDP_Update                             import TestFDPUpdate

# ── IO (I1–I11) ───────────────────────────────────────────────────────────────
from tests.io.I1_NVMe_Write_Valid_Placement_ID             import TestNVMeWriteValidPID
from tests.io.I2_NVMe_Write_Invalid_Placement_ID           import TestNVMeWriteInvalidPID
from tests.io.I3_NVMe_Write_User_Controlled_Parameters     import TestNVMeWriteUserControlled
from tests.io.I4_NVMe_Write_Legacy                         import TestNVMeWriteLegacy
from tests.io.I6_Multi_Handle_Isolation                    import TestFDPMultiHandleIsolation
from tests.io.I7_Placement_Handle_Capacity_Exhaustion      import TestFDPHandleCapacityExhaustion
from tests.io.I8_IO_Mgmt_Recv_Valid                        import TestIOMgmtReceiveValid
from tests.io.I9_IO_Mgmt_Recv_Invalid                      import TestIOMgmtFDPDisabled
from tests.io.I10_IO_Mgmt_Send_Valid                       import TestIOMgmtSendValid
from tests.io.I11_IO_Mgmt_Send_Invalid                     import TestIOMgmtSendInvalid

# ── Reset (R1–R12) ────────────────────────────────────────────────────────────
from tests.reset.R1_FDP_Enable_Persistence_Ctrl_Reset      import TestFDPEnablePersistCtrlReset
from tests.reset.R2_FDP_Enable_Persistence_Link_Reset      import TestFDPEnablePersistDeviceReset
from tests.reset.R3_FDP_Enable_Persistence_NSSR            import TestFDPEnablePersistSubsystemReset
from tests.reset.R4_FDP_Disable_Persistence                import TestFDPDisablePersistenceAcrossReset
from tests.reset.R5_FDP_Stats_Persistence_Ctrl_Reset       import TestFDPStatsPersistCtrlReset
from tests.reset.R6_FDP_Stats_Persistence_Link_Reset       import TestFDPStatsPersistDeviceReset
from tests.reset.R7_FDP_Stats_Persistence_NSSR             import TestFDPStatsPersistSubsystemReset
from tests.reset.R8_FDP_Stats_Monotonicity                 import TestFDPStatsMonotonicity
from tests.reset.R9_FDP_Configs_Persistence                import TestFDPConfigIndexPersistence
from tests.reset.R10_Directives_Persistence                import TestFDPDirectivesPersistReset
from tests.reset.R11_FDP_Event_Log_Persistence             import TestFDPEventLogPersistReset
from tests.reset.R12_PH_to_RUH_Mapping_Persistence         import TestPHToRUHMappingPersistence

# ── Admin (A1–A29) ────────────────────────────────────────────────────────────
from tests.admin.A1_Validate_FDPS_Bit_in_Identify_Ctrl     import TestAdminIdentifyFDPS
from tests.admin.A2_Validate_FDP_Configs_Header            import TestAdminValidateFDPConfigsHeader
from tests.admin.A3_Validate_FDP_Config_Desc_Header        import TestAdminValidateFDPConfigDescHeader
from tests.admin.A4_Validate_Event_Log_Header              import TestAdminValidateEventLogHeader
from tests.admin.A5_Validate_FDP_Attributes                import TestAdminValidateFDPAttributes
from tests.admin.A6_Validate_Max_Placement_Identifiers     import TestAdminValidateMAXPID
from tests.admin.A7_Validate_Reclaim_Resources             import TestAdminValidateReclaimResources
from tests.admin.A8_Validate_Reclaim_Group_Identifier_Format import TestAdminValidateRGIF
from tests.admin.A9_Validate_Event_Descriptor_Invalid_PID  import TestAdminValidateEventInvalidPID
from tests.admin.A10_Validate_Host_Bytes_Written_Accuracy  import TestAdminValidateHBWAccuracy
from tests.admin.A11_Validate_Event_Masking_Disabled       import TestAdminValidateEventMasking
from tests.admin.A12_Validate_Event_Timestamp_and_Ordering import TestAdminValidateEventOrdering
from tests.admin.A13_Validate_FDP_Stats_Monotonicity       import TestAdminValidateFDPStatsMonotonicity
from tests.admin.A14_Identify_Fixed_Capacity_Management    import TestAdminIdentifyFCM
from tests.admin.A15_Identify_FDPS_Command_Set_Consistency import TestAdminIdentifyFDPSCommandSet
from tests.admin.A16_Identify_VWC_Flush_Behavior           import TestAdminIdentifyVWCFlush
from tests.admin.A17_Identify_VWC_Global                   import TestAdminIdentifyVWCGlobal
from tests.admin.A18_Create_NS_Invalid_PHL                 import TestAdminCreateNSInvalidPHL
from tests.admin.A19_Create_NS_Valid_PHL                   import TestAdminCreateNSValidPHL
from tests.admin.A20_Enable_FDP_on_Empty_Endgrp            import TestAdminEnableFDPEmpty
from tests.admin.A21_Enable_FDP_Invalid_Config             import TestAdminEnableFDPInvalidConfig
from tests.admin.A22_Enable_FDP_with_NS                    import TestAdminEnableFDPWithNS
from tests.admin.A23_Event_Log_Retention                   import TestAdminEventLogRetention
from tests.admin.A24_Partial_Log_Page_Read                 import TestAdminPartialLogPageRead
from tests.admin.A25_Read_FDP_Configs_Log                  import TestAdminReadFDPConfigsLog
from tests.admin.A26_Read_FDP_Stats                        import TestAdminReadFDPStats
from tests.admin.A27_Disable_FDP_Stats_Clear               import TestAdminDisableFDPStatsClear
from tests.admin.A28_Calculate_WAF                         import TestAdminCalculateWAF
from tests.admin.A29_DWPD_Calculation                      import TestAdminDWPDCalculation

# ── Corner (C1, C14, C17, C20) ──────────────────────────────────────────────
from tests.corner.C1_Sanitize_During_FDP_IO              import TestSanitizeDuringFDPIO
from tests.corner.C2_RUHU_During_Active_Write            import TestRUHUDuringActiveWrite
from tests.corner.C3_FDP_Events_Log_Overflow             import TestFDPEventsLogOverflow
from tests.corner.C4_Format_During_FDP_Write             import TestFormatDuringFDPWrite


ALL_TESTS = [
    # E1–
    TestPreconditioning,
    TestEnduranceWAF,
    TestEnduranceWAFAllRUH,
    TestEnduranceSingleRUH,

    # B1–B6
    TestFDPStatus,
    TestFDPConfigs,
    TestPlacementIDs,
    TestReclaimUnits,
    TestFDPEvents,
    TestFDPUpdate,

    # I1–I11
    TestNVMeWriteValidPID,
    TestNVMeWriteInvalidPID,
    TestNVMeWriteUserControlled,
    TestNVMeWriteLegacy,
    TestFDPMultiHandleIsolation,
    TestFDPHandleCapacityExhaustion,
    TestIOMgmtReceiveValid,
    TestIOMgmtFDPDisabled,
    TestIOMgmtSendValid,
    TestIOMgmtSendInvalid,

    # R1–R12
    TestFDPEnablePersistCtrlReset,
    TestFDPEnablePersistDeviceReset,
    TestFDPEnablePersistSubsystemReset,
    TestFDPDisablePersistenceAcrossReset,
    TestFDPStatsPersistCtrlReset,
    TestFDPStatsPersistDeviceReset,
    TestFDPStatsPersistSubsystemReset,
    TestFDPStatsMonotonicity,
    TestFDPConfigIndexPersistence,
    TestFDPDirectivesPersistReset,
    TestFDPEventLogPersistReset,
    TestPHToRUHMappingPersistence,

    # A1–A29
    TestAdminIdentifyFDPS,
    TestAdminValidateFDPConfigsHeader,
    TestAdminValidateFDPConfigDescHeader,
    TestAdminValidateEventLogHeader,
    TestAdminValidateFDPAttributes,
    TestAdminValidateMAXPID,
    TestAdminValidateReclaimResources,
    TestAdminValidateRGIF,
    TestAdminValidateEventInvalidPID,
    TestAdminValidateHBWAccuracy,
    TestAdminValidateEventMasking,
    TestAdminValidateEventOrdering,
    TestAdminValidateFDPStatsMonotonicity,
    TestAdminIdentifyFCM,
    TestAdminIdentifyFDPSCommandSet,
    TestAdminIdentifyVWCFlush,
    TestAdminIdentifyVWCGlobal,
    TestAdminCreateNSInvalidPHL,
    TestAdminCreateNSValidPHL,
    TestAdminEnableFDPEmpty,
    TestAdminEnableFDPInvalidConfig,
    TestAdminEnableFDPWithNS,
    TestAdminEventLogRetention,
    TestAdminPartialLogPageRead,
    TestAdminReadFDPConfigsLog,
    TestAdminReadFDPStats,
    TestAdminDisableFDPStatsClear,
    TestAdminCalculateWAF,
    TestAdminDWPDCalculation,

    # Corner
    TestSanitizeDuringFDPIO,
    TestRUHUDuringActiveWrite,
    TestFDPEventsLogOverflow,
    TestFormatDuringFDPWrite,
]


def get_test_by_id(test_id: str):
    return next((cls for cls in ALL_TESTS if cls.test_id == test_id), None)