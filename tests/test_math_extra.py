import math
import unittest

from solala.utils.math_extra import safe_divide


class SafeDivideTestCase(unittest.TestCase):
    """
    Verify ordinary division and overflow-safe integer rounding.
    """

    def test_ordinary_division_preserves_fraction(self) -> None:
        self.assertEqual(safe_divide(7, 2), 3.5)
        self.assertEqual(safe_divide(-7, 2), -3.5)
        self.assertEqual(safe_divide(0, 5), 0.0)
        self.assertEqual(safe_divide(1.5, 2), 0.75)

    def test_zero_denominator_raises(self) -> None:
        for numerator in (0, 1, 10 ** 400):
            with self.subTest(numerator=numerator):
                with self.assertRaises(ZeroDivisionError):
                    safe_divide(numerator, 0)

    def test_huge_integer_division(self) -> None:
        huge = 10 ** 400
        self.assertEqual(safe_divide(huge, 1000), huge // 1000)
        self.assertIsInstance(safe_divide(huge, 1000), int)
        self.assertEqual(safe_divide(-huge, 1000), -(huge // 1000))
        self.assertEqual(safe_divide(huge, -1000), -(huge // 1000))
        self.assertEqual(safe_divide(huge, 1000.0), huge // 1000)

    def test_huge_integer_rounds_ties_to_even(self) -> None:
        huge_even = 10 ** 400
        self.assertEqual(safe_divide(huge_even + 1, 2), huge_even // 2)
        self.assertEqual(safe_divide(huge_even + 3, 2), huge_even // 2 + 2)
        self.assertEqual(safe_divide(-(huge_even + 3), 2), -(huge_even // 2 + 2))

    def test_large_remainder_and_denominator(self) -> None:
        denominator = 10 ** 400 + 3
        self.assertEqual(safe_divide(denominator * (10 ** 400) + denominator - 1, denominator), 10 ** 400 + 1)

    def test_nonfinite_denominator(self) -> None:
        self.assertEqual(safe_divide(1, math.inf), 0.0)
        self.assertTrue(math.isnan(safe_divide(1, math.nan)))


if __name__ == '__main__':
    unittest.main()
