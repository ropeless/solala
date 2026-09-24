from typing import Dict, Tuple, Iterator, Mapping

from solala.power_controller.impl_modbus.register_access import NEXT_SF as _NEXT_SF, uint32, MODBUS_MODEL
from solala.power_controller.impl_modbus.register_access import RegisterAccess, str16, str8, uint16, scaled_uint, \
    scaled_int

MPPT_MODEL: MODBUS_MODEL = 160  # special model with variable number of registers

_TMP_SF = 36  # Model 101

_WMax_SF = 23  # Model 121

_WMaxLimPct_SF = 24  # Model 123

_WChaMax_SF = 19  # Model 124
_WChaDisChaGra_SF = 20  # Model 124
_MinRsvPct_SF = 22  # Model 124
_ChaState_SF = 23  # Model 124
_InOutWRte_SF = 26  # Model 124

_DCW_SF = 5  # Model 160

_W_SF = 23  # Model 201

MODELS: Mapping[MODBUS_MODEL, Dict[str, RegisterAccess]] = {
    # Common
    1: {
        'manufacturer': str16(3),
        'name': str16(19),
        'software_version': str8(43),
        'serial_number': str16(51),
    },

    # Inverter
    101: {
        'W': scaled_int(15, _NEXT_SF),
        'HZ': scaled_uint(17, _NEXT_SF),
        'DCW': scaled_int(32, _NEXT_SF),
        'TmpCab': scaled_int(34, _TMP_SF),  # Temperature in Celsius
    },

    # Inverter Nameplate
    120: {
        'WRtg': scaled_uint(4, _NEXT_SF),  # Inverter maximum output power
    },

    # Inverter Settings
    121: {
        'WMax': scaled_uint(3, _WMax_SF),  # Inverter maximum output power
    },

    # Inverter Status
    122: {
        'PVConn': uint16(3),
        'StorConn': uint16(4),
        'ECPConn': uint16(5),
        'StActCtl': uint32(36),
    },

    # Inverter Control
    123: {
        'Conn_WinTms': uint16(3, writable=True),
        'Conn_RvrtTms': uint16(4, writable=True),
        'Conn': uint16(5, writable=True),
        'WMaxLimPct': scaled_uint(6, _WMaxLimPct_SF, writable=True),
        'WMaxLimPct_WinTms': uint16(7, writable=True),
        'WMaxLimPct_RvrtTms': uint16(8, writable=True),
        'WMaxLimPct_RmpTms': uint16(9, writable=True),
        'WMaxLim_Ena': uint16(10, writable=True),
    },

    # Storage Control
    124: {
        'WchaMax': scaled_uint(3, _WChaMax_SF, writable=True),
        'WchaGra': scaled_uint(4, _WChaDisChaGra_SF, writable=True),
        'WdisChaGra': scaled_uint(5, _WChaDisChaGra_SF, writable=True),
        'StorCtl_Mod': uint16(6, writable=True),  # 0 or 1
        'MinRsvPct': scaled_uint(8, _MinRsvPct_SF, writable=True),
        'ChaState': scaled_uint(9, _ChaState_SF),
        'OutWRte': scaled_int(13, _InOutWRte_SF, writable=True),
        'InWRte': scaled_int(14, _InOutWRte_SF, writable=True),
    },

    # Smart Meter
    201: {
        'W': scaled_int(19, _W_SF),
        'Hz': scaled_int(17, _NEXT_SF),
    },

    # MPPT common
    MPPT_MODEL: {
        'N': uint16(9),
    },
}


def mppt_modules(number_of_modules: int) -> Iterator[Tuple[str, RegisterAccess]]:
    """
    Additional registers for MPPT modules.
    """
    for module_number in range(number_of_modules):
        module_id = module_number + 1
        module_offset = module_number * 20
        yield f'module/{module_id}/ID', uint16(11 + module_offset)
        yield f'module/{module_id}/IDStr', str8(12 + module_offset),
        yield f'module/{module_id}/DCW', scaled_uint(22 + module_offset, _DCW_SF)
