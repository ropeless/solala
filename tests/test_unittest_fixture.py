"""
Test array and dictionary comparison helpers.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from tests.unittest_fixture import Fixture, make_suit


class NestedArrayComparisonTests(Fixture):
    """
    Check that both array assertions reject unmatched nested elements.
    """

    def test_rejects_extra_nested_elements(self) -> None:
        """
        Reject an extra nested element on either side of the comparison.
        """
        for compare in (self.assertArrayEqual, self.assertArrayAlmostEqual):
            for got, expected in (([[1]], [[1, 2]]), ([[1, 2]], [[1]])):
                with self.subTest(assertion=compare.__name__, got=got, expected=expected):
                    with self.assertRaises(AssertionError):
                        compare(got, expected)


class DictionaryComparisonTests(Fixture):
    """
    Check that approximate dictionary comparisons require matching keys.
    """

    def test_rejects_different_keys_at_equal_length(self) -> None:
        """
        Raise AssertionError when equal-length dictionaries have different keys.
        """
        got = {'shared': 1.0, 'actual_only': 2.0}
        expected = {'shared': 1.0, 'expected_only': 2.0}

        with self.assertRaises(AssertionError):
            self.assertDictAlmostEqual(got, expected)


class SuiteLoadingTests(Fixture):
    """
    Check how the runner loads standard and custom suites.
    """

    def test_loads_module_relative_to_package(self) -> None:
        """
        Use the qualified module when discovering standard test cases.
        """
        suite = make_suit(['test_unittest_fixture'], package='tests')
        self.assertIn(
            'test_loads_module_relative_to_package',
            str(suite),
        )

    def test_propagates_errors_from_custom_suite(self) -> None:
        """
        Surface errors raised by a custom suite factory.
        """
        for error_type in (ImportError, AttributeError):
            with self.subTest(error=error_type.__name__):
                module = SimpleNamespace(suite=Mock(side_effect=error_type('broken suite')))
                with patch('tests.unittest_fixture._import', return_value=module):
                    with self.assertRaisesRegex(error_type, 'broken suite'):
                        make_suit(['test_unittest_fixture'], package='tests')
