"""
Regression tests for the established `render_json` display behaviour.
"""

import unittest
from typing import Any

from solala.utils.json_extras import JSONValue, render_json


class TestRenderJson(unittest.TestCase):
    """
    Characterise currently correct rendering before refactoring.
    """

    def check_render(self, value: JSONValue, expected: str, **kwargs: Any) -> None:
        """
        Compare the complete rendered output with an explicit expectation.
        """
        self.assertEqual(expected, render_json(value, **kwargs))

    def test_positive_integer(self) -> None:
        self.check_render(123, '123')

    def test_negative_integer(self) -> None:
        self.check_render(-12, '-12')

    # TODO currently fails
    # def test_positive_float_integer(self) -> None:
    #     self.check_render(123.0, '123')

    def test_negative_float_integer(self) -> None:
        self.check_render(-12.0, '-12')

    def test_zero(self) -> None:
        self.check_render(0, '0')

    def test_zero_float(self) -> None:
        self.check_render(0.0, '0')

    def test_float_default_precision(self) -> None:
        self.check_render(1.234, '1.2')

    def test_float_custom_precision(self) -> None:
        self.check_render(1.234, '1.23', float_format='.2f')

    def test_float_trailing_zeros_removed(self) -> None:
        self.check_render(1.5, '1.5', float_format='.3f')

    def test_negative_zero(self) -> None:
        self.check_render(-0.0, '0')

    def test_nan(self) -> None:
        self.check_render(float('nan'), 'nan')

    def test_inf(self) -> None:
        self.check_render(float('inf'), 'inf')

    def test_neg_inf(self) -> None:
        self.check_render(float('-inf'), '-inf')

    def test_small_float(self) -> None:
        self.check_render(0.0000123, '1.2e-05')

    def test_true(self) -> None:
        self.check_render(True, 'true')

    def test_false(self) -> None:
        self.check_render(False, 'false')

    def test_none(self) -> None:
        self.check_render(None, 'none')

    def test_string(self) -> None:
        self.check_render('hello', "'hello'")

    def test_empty_string(self) -> None:
        self.check_render('', "''")

    def test_empty_list(self) -> None:
        self.check_render([], '[]')

    def test_integer_list(self) -> None:
        self.check_render(
            [1, 2],
            '[\n'
            '  1\n'
            '  2\n'
            ']',
        )

    def test_mixed_list(self) -> None:
        self.check_render(
            [1, 'hello', True, None],
            '[\n'
            '  1\n'
            "  'hello'\n"
            '  true\n'
            '  none\n'
            ']',
        )

    def test_empty_dictionary(self) -> None:
        self.check_render({}, '')

    def test_single_dictionary_entry(self) -> None:
        self.check_render({'power': 123}, '  power = 123')

    def test_multiple_dictionary_entries(self) -> None:
        self.check_render(
            {'a': 1, 'b': 2},
            '  a = 1\n'
            '  b = 2',
        )

    def test_dictionary_string(self) -> None:
        self.check_render({'name': 'hello'}, "  name = 'hello'")

    def test_dictionary_boolean(self) -> None:
        self.check_render({'enabled': True}, '  enabled = true')

    def test_dictionary_none(self) -> None:
        self.check_render({'value': None}, '  value = none')

    def test_dictionary_list(self) -> None:
        self.check_render(
            {'a': [1, 2]},
            '  a = [\n'
            '    1\n'
            '    2\n'
            '  ]',
        )

    def test_list_of_dictionaries(self) -> None:
        self.check_render(
            [{'a': 1}, {'b': 2}],
            '[\n'
            '    a = 1\n'
            '    b = 2\n'
            ']',
        )

    def test_key_underscores_removed(self) -> None:
        self.check_render({'solar_power': 1}, '  solar power = 1')

    def test_key_underscores_preserved(self) -> None:
        self.check_render({'solar_power': 1}, '  solar_power = 1', remove_key_underscores=False)

    def test_value_underscores_removed(self) -> None:
        self.check_render('FORCE_CHARGE', "'FORCE CHARGE'")

    def test_value_underscores_preserved(self) -> None:
        self.check_render('FORCE_CHARGE', "'FORCE_CHARGE'", remove_value_underscores=False)

    def test_numeric_unit(self) -> None:
        self.check_render({'power': 123}, '  power = 123 W', units={'power': ' W'})

    def test_float_unit(self) -> None:
        self.check_render({'power': 1.25}, '  power = 1.25 W', units={'power': ' W'}, float_format='.2f')

    def test_units_use_original_key(self) -> None:
        self.check_render({'solar_power': 123}, '  solar power = 123 W', units={'solar_power': ' W'})

    def test_string_does_not_get_unit(self) -> None:
        self.check_render({'power': 'unknown'}, "  power = 'unknown'", units={'power': ' W'})

    def test_none_does_not_get_unit(self) -> None:
        self.check_render({'power': None}, '  power = none', units={'power': ' W'})

    def test_deeply_nested_dictionaries(self) -> None:
        self.check_render(
            {'outer': {'inner': {'value': 42}}},
            '  outer:\n'
            '    inner:\n'
            '      value = 42',
        )

    def test_nested_list_of_dictionaries(self) -> None:
        self.check_render(
            {'groups': [{'name': 'alpha', 'readings': [1, 2]}, {'name': 'beta', 'readings': [3, 4]}]},
            '  groups = [\n'
            "      name = 'alpha'\n"
            '      readings = [\n'
            '        1\n'
            '        2\n'
            '      ]\n'
            "      name = 'beta'\n"
            '      readings = [\n'
            '        3\n'
            '        4\n'
            '      ]\n'
            '  ]',
        )

    def test_deeply_nested_mixed_containers(self) -> None:
        self.check_render(
            {'a': [{'b': {'c': [1, {'d': None}]}}]},
            '  a = [\n'
            '      b:\n'
            '        c = [\n'
            '          1\n'
            '            d = none\n'
            '        ]\n'
            '  ]',
        )

    def test_nested_containers_with_empty_list(self) -> None:
        self.check_render(
            [{'section': {'measurements': [{'power': 1.25, 'active': True}, {'power': 2.5, 'active': False}]}},
             {'section': {'measurements': []}}],
            '[\n'
            '    section:\n'
            '      measurements = [\n'
            '          power = 1.2\n'
            '          active = true\n'
            '          power = 2.5\n'
            '          active = false\n'
            '      ]\n'
            '    section:\n'
            '      measurements = []\n'
            ']',
        )


    def test_nested_units(self) -> None:
        self.check_render(
            {'system': {'battery': {'power': 1.25}}},
            '  system:\n'
            '    battery:\n'
            '      power = 1.25 W',
            units={'power': ' W'},
            float_format='.2f',
        )

    def test_nested_key_underscores_preserved(self) -> None:
        self.check_render(
            {'solar_data': {'battery_power': 123}},
            '  solar_data:\n'
            '    battery_power = 123',
            remove_key_underscores=False,
        )

    def test_nested_value_underscores_preserved(self) -> None:
        self.check_render(
            {'system': {'battery_mode': 'FORCE_CHARGE'}},
            '  system:\n'
            "    battery mode = 'FORCE_CHARGE'",
            remove_value_underscores=False,
        )

    def test_unicode_string(self) -> None:
        self.check_render('café', "'café'")

    def test_unicode_string_ascii_disabled(self) -> None:
        self.check_render('café', "'café'", ensure_ascii=False)

    def test_tuple_like_list(self) -> None:
        self.check_render(
            (1, 'hello', True),
            '[\n'
            '  1\n'
            "  'hello'\n"
            '  true\n'
            ']',
        )

    def test_nested_tuple_like_list(self) -> None:
        self.check_render(
            {'values': (1, 2)},
            '  values = [\n'
            '    1\n'
            '    2\n'
            '  ]',
        )

    def test_empty_dictionary_nested_in_dictionary(self) -> None:
        self.check_render({'empty': {}, 'value': 1}, '  value = 1')

    def test_empty_dictionary_nested_in_list(self) -> None:
        self.check_render(
            [{}, {'value': 1}],
            '[\n'
            '    value = 1\n'
            ']',
        )

    def test_empty_dictionary_nested_at_multiple_depths(self) -> None:
        self.check_render(
            {'outer': {'empty': {}, 'value': 1}},
            '  outer:\n'
            '    value = 1',
        )

    def test_positive_integral_float(self) -> None:
        self.check_render(123.0, '123')

    def test_large_integral_float(self) -> None:
        self.check_render(1000.0, '1000')

    def test_negative_integral_float(self) -> None:
        self.check_render(-123.0, '-123')

    def test_integral_float_with_custom_format(self) -> None:
        self.check_render(123.0, '123', float_format='.2f')

    def test_unicode_ascii_escaping(self) -> None:
        self.check_render('café', r"'caf\u00e9'", ensure_ascii=True)

    def test_custom_indent(self) -> None:
        self.check_render(
            [1, 2],
            '[\n'
            '    1\n'
            '    2\n'
            ']',
            indent=4,
        )
