import unittest

from solala.power_controller.impl_modbus.register_access import check_valid_int


class MyTestCase(unittest.TestCase):

    def test_uint16(self):
        count = 1
        signed = False

        check_valid_int(0, count, signed)
        check_valid_int(1, count, signed)
        check_valid_int(65535, count, signed)

        with self.assertRaises(ValueError):
            check_valid_int(-1, count, signed)

        with self.assertRaises(ValueError):
            check_valid_int(65536, count, signed)

    def test_int16(self):
        count = 1
        signed = True

        check_valid_int(-32768, count, signed)
        check_valid_int(-1, count, signed)
        check_valid_int(0, count, signed)
        check_valid_int(1, count, signed)
        check_valid_int(32767, count, signed)

        with self.assertRaises(ValueError):
            check_valid_int(-32769, count, signed)

        with self.assertRaises(ValueError):
            check_valid_int(32768, count, signed)


if __name__ == '__main__':
    unittest.main()
