import unittest
from unittest.mock import Mock

from solala.delegates.power_controller.modbus_power_controller.modbus_register_access import (
    RegisterContext,
    scaled_uint16,
)


class TestRegisterAccessScaled(unittest.TestCase):

    def setUp(self) -> None:
        self.client = Mock()
        self.client.read_holding_registers.return_value = Mock(
            isError=Mock(return_value=False),
            registers=[2],
        )
        self.client.write_registers.return_value = Mock(isError=Mock(return_value=False))
        self.context = RegisterContext(
            client=self.client,
            device_id=1,
            modbus_model=1,
            address_offset=0,
        )
        self.register = scaled_uint16(addr=10, scale_addr=11, writable=True)

    def test_set_integer_with_positive_scale(self) -> None:
        self.register.set(self.context, 1200)

        self.client.write_registers.assert_called_once_with(
            10,
            values=[12],
            device_id=1,
        )

    def test_set_integer_not_multiple_of_positive_scale_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, 'not an integer multiple'):
            self.register.set(self.context, 1234)

        self.client.write_registers.assert_not_called()


if __name__ == '__main__':
    unittest.main()
