import unittest

from solala.utils.type_extras import check_bool, check_num, check_str


class TypeExtrasTestCase(unittest.TestCase):
    """
    Verify general-purpose scalar type checking.
    """

    def test_check_str(self) -> None:
        self.assertEqual(check_str('hello'), 'hello')
        for value in (None, 1, True, []):
            with self.subTest(value=value), self.assertRaises(TypeError):
                check_str(value)

    def test_check_num(self) -> None:
        self.assertEqual(check_num(3), 3)
        self.assertEqual(check_num(1.25), 1.25)
        # Preserve the previous json_num behavior until validation policy is decided.
        self.assertIs(check_num(True), True)
        for value in (None, '3', []):
            with self.subTest(value=value), self.assertRaises(TypeError):
                check_num(value)

    def test_check_bool(self) -> None:
        self.assertIs(check_bool(True), True)
        self.assertIs(check_bool(False), False)
        for value in (None, 0, 1, 'true'):
            with self.subTest(value=value), self.assertRaises(TypeError):
                check_bool(value)


if __name__ == '__main__':
    unittest.main()
