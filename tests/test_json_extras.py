"""
Tests specifying the intended `render_json` display behaviour.
"""

import unittest
from typing import Any

from solala.utils.json_extras import JSONValue, render_json


class TestRenderJson(unittest.TestCase):
    """
    Specify expected rendering, including behaviour not yet implemented.
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

    def test_positive_float_integer_simple(self) -> None:
        self.check_render(1.0, '1')

    def test_negative_float_integer_simple(self) -> None:
        self.check_render(-2.0, '-2')

    def test_positive_float_integer(self) -> None:
        self.check_render(12.0, '12')

    def test_negative_float_integer(self) -> None:
        self.check_render(-12.0, '-12')

    def test_positive_integral_float(self) -> None:
        self.check_render(123.0, '123')

    def test_negative_integral_float(self) -> None:
        self.check_render(-123.0, '-123')

    def test_large_integral_float(self) -> None:
        self.check_render(1000.0, '1000')

    def test_large_negative_integral_float(self) -> None:
        self.check_render(-1000.0, '-1000')

    def test_zero(self) -> None:
        self.check_render(0, '0')

    def test_zero_float(self) -> None:
        self.check_render(0.0, '0')

    def test_float_default_precision(self) -> None:
        self.check_render(1.234, '1.2')

    def test_integral_float_with_custom_format(self) -> None:
        self.check_render(123.0, '123', float_format='.2f')

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
        self.check_render([1, 2], "[1, 2]")

    def test_mixed_list(self) -> None:
        self.check_render([1, 'hello', True, None], "[1, 'hello', true, none]")

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
        self.check_render({'a': [1, 2]}, "  a = [1, 2]")

    def test_list_of_dictionaries(self) -> None:
        self.check_render([{'a': 1}, {'b': 2}], "[\n  1:\n    a = 1\n  2:\n    b = 2\n]")

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
        self.check_render({'groups': [{'name': 'alpha', 'readings': [1, 2]}, {'name': 'beta', 'readings': [3, 4]}]}, "  groups = [\n    1:\n      name = 'alpha'\n      readings = [1, 2]\n    2:\n      name = 'beta'\n      readings = [3, 4]\n  ]")

    def test_deeply_nested_mixed_containers(self) -> None:
        self.check_render({'a': [{'b': {'c': [1, {'d': None}]}}]}, "  a = [\n    1:\n      b:\n        c = [\n          1: 1\n          2:\n            d = none\n        ]\n  ]")

    def test_nested_containers_with_empty_list(self) -> None:
        self.check_render([{'section': {'measurements': [{'power': 1.25, 'active': True}, {'power': 2.5, 'active': False}]}}, {'section': {'measurements': []}}], "[\n  1:\n    section:\n      measurements = [\n        1:\n          power = 1.2\n          active = true\n        2:\n          power = 2.5\n          active = false\n      ]\n  2:\n    section:\n      measurements = []\n]")

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
        self.check_render((1, 'hello', True), "[1, 'hello', true]")

    def test_nested_tuple_like_list(self) -> None:
        self.check_render({'values': (1, 2)}, "  values = [1, 2]")

    def test_empty_dictionary_nested_in_dictionary(self) -> None:
        self.check_render({'empty': {}, 'value': 1}, '  value = 1')

    def test_empty_dictionary_nested_in_list(self) -> None:
        self.check_render([{}, {'value': 1}], "[\n  2:\n    value = 1\n]")

    def test_empty_dictionary_omitted_but_empty_list_preserved(self) -> None:
        self.check_render({'empty_dict': {}, 'empty_list': []}, '  empty list = []')

    def test_recursively_empty_dictionaries(self) -> None:
        self.check_render({'outer': {'inner': {}}}, '')

    def test_empty_dictionary_nested_at_multiple_depths(self) -> None:
        self.check_render(
            {'outer': {'empty': {}, 'value': 1}},
            '  outer:\n'
            '    value = 1',
        )

    def test_unicode_ascii_escaping(self) -> None:
        self.check_render('café', r"'caf\u00e9'", ensure_ascii=True)

    def test_custom_indent(self) -> None:
        self.check_render([1, 2], "[1, 2]", indent=4)

    def test_string_with_colon(self) -> None:
        self.check_render('status: ready', "'status: ready'")

    def test_dictionary_string_with_colon(self) -> None:
        self.check_render({'message': 'status: ready'}, "  message = 'status: ready'")

    def test_dictionary_key_with_colon(self) -> None:
        self.check_render({'message: status': 'ready'}, "  'message: status' = 'ready'")

    def test_dictionary_key_with_equals(self) -> None:
        self.check_render({'message = status': 'ready'}, "  'message = status' = 'ready'")

    def test_dictionary_key_with_tab(self) -> None:
        self.check_render({'message\tstatus': 'ready'}, "  'message\\tstatus' = 'ready'")

    def test_dictionary_key_with_quote(self) -> None:
        self.check_render({"message'status": 'ready'}, "  message'status = 'ready'")

    def test_dictionary_key_with_quote_and_space(self) -> None:
        self.check_render({"message' status": 'ready'}, "  \"message' status\" = 'ready'")

    def test_dictionary_key_with_colon_without_space(self) -> None:
        self.check_render({'message:status': 'ready'}, "  message:status = 'ready'")

    def test_dictionary_key_with_equals_without_space(self) -> None:
        self.check_render({'message=status': 'ready'}, "  message=status = 'ready'")

    def test_dictionary_key_with_double_quote(self) -> None:
        self.check_render({'message"status': 'ready'}, "  'message\"status' = 'ready'")

    def test_string_with_double_quote(self) -> None:
        self.check_render('a"b', "'a\"b'")

    def test_string_with_single_quote(self) -> None:
        self.check_render("a'b", '"a\'b"')

    def test_string_with_backslash(self) -> None:
        self.check_render('a\\b', r"'a\\b'")

    def test_string_with_newline(self) -> None:
        self.check_render('a\nb', r"'a\nb'")

    def test_string_with_tab(self) -> None:
        self.check_render('a\tb', r"'a\tb'")

    def test_string_with_carriage_return(self) -> None:
        self.check_render('a\rb', r"'a\rb'")

    def test_string_with_colon_and_underscore(self) -> None:
        self.check_render('FORCE_CHARGE: active', "'FORCE CHARGE: active'")

    def test_dictionary_key_with_dash(self) -> None:
        self.check_render({'grid-power': 123}, '  grid-power = 123')

    def test_dictionary_key_with_dot(self) -> None:
        self.check_render({'grid.power': 123}, '  grid.power = 123')

    def test_dictionary_key_with_colon_int_value(self) -> None:
        self.check_render({'grid:power': 123}, '  grid:power = 123')

    def test_dictionary_key_with_slash(self) -> None:
        self.check_render({'grid/power': 123}, '  grid/power = 123')

    def test_dictionary_key_with_double_quote_int_value(self) -> None:
        self.check_render({'a"b': 1}, '  a"b = 1')

    def test_dictionary_key_with_unicode(self) -> None:
        self.check_render({'café': 1}, '  café = 1')

    def test_dictionary_key_with_leading_space(self) -> None:
        self.check_render({' power': 1}, "  ' power' = 1")

    def test_dictionary_key_with_trailing_space(self) -> None:
        self.check_render({'power ': 1}, "  'power ' = 1")

    def test_dictionary_key_with_empty_string(self) -> None:
        self.check_render({'': 1}, "  '' = 1")

    def test_nested_dictionary_key_with_punctuation(self) -> None:
        self.check_render(
            {'system': {'grid.power': 123}},
            '  system:\n'
            '    grid.power = 123',
        )

    def test_boolean_does_not_get_unit(self) -> None:
        self.check_render({'enabled': True}, '  enabled = true', units={'enabled': ' W'})

    def test_false_does_not_get_unit(self) -> None:
        self.check_render({'enabled': False}, '  enabled = false', units={'enabled': ' W'})

    def test_units_in_nested_list_dictionary(self) -> None:
        self.check_render({'readings': [{'power': 12}, {'power': 34}]}, "  readings = [\n    1:\n      power = 12 W\n    2:\n      power = 34 W\n  ]", units={'power': ' W'})

    def test_units_on_nested_integral_float(self) -> None:
        self.check_render(
            {'battery': {'power': 123.0}},
            '  battery:\n'
            '    power = 123 W',
            units={'power': ' W'},
        )

    def test_empty_dictionary_as_only_nested_value(self) -> None:
        self.check_render({'empty': {}}, '')

    def test_empty_dictionaries_only_in_list(self) -> None:
        self.check_render([{}, {}], "[\n]")

    def test_empty_dictionary_in_tuple(self) -> None:
        self.check_render(({}, {'power': 1}), "[\n  2:\n    power = 1\n]")

    def test_empty_tuple(self) -> None:
        self.check_render((), '[]')

    def test_nested_tuple_and_list(self) -> None:
        self.check_render([(1, 2), [3, 4]], "[\n  1: [1, 2]\n  2: [3, 4]\n]")

    def test_float_exponent_preserved(self) -> None:
        self.check_render(1.234e20, '1.2e+20')

    def test_integral_float_in_list(self) -> None:
        self.check_render([123.0, -123.0], "[123, -123]")


    def test_simple_list_nine_elements(self) -> None:
        self.check_render(list(range(1, 10)), '[1, 2, 3, 4, 5, 6, 7, 8, 9]')

    def test_complex_list_ten_elements(self) -> None:
        self.check_render(
            list(range(1, 11)),
            '[\n'
            '  1: 1\n'
            '  2: 2\n'
            '  3: 3\n'
            '  4: 4\n'
            '  5: 5\n'
            '  6: 6\n'
            '  7: 7\n'
            '  8: 8\n'
            '  9: 9\n'
            '  10: 10\n'
            ']',
        )

    def test_simple_list_with_escaped_characters(self) -> None:
        self.check_render(['a\nb', 'c\td'], r"['a\nb', 'c\td']")

    def test_simple_list_with_colon_and_equals(self) -> None:
        self.check_render(['mode:auto', 'power=123'], "['mode:auto', 'power=123']")

    def test_simple_list_with_twenty_character_string(self) -> None:
        self.check_render(['abcdefghijklmnopqr'], "['abcdefghijklmnopqr']")

    def test_complex_list_with_long_string(self) -> None:
        self.check_render(
            ['abcdefghijklmnopqrs'],
            '[\n'
            "  1: 'abcdefghijklmnopqrs'\n"
            ']',
        )

    def test_complex_list_with_comma_in_string(self) -> None:
        self.check_render(
            ['a,b', 'x'],
            '[\n'
            "  1: 'a,b'\n"
            "  2: 'x'\n"
            ']',
        )

    def test_complex_list_with_open_bracket_in_string(self) -> None:
        self.check_render(
            ['[hello]', 'x'],
            '[\n'
            "  1: '[hello]'\n"
            "  2: 'x'\n"
            ']',
        )

    def test_complex_list_with_close_bracket_in_string(self) -> None:
        self.check_render(
            ['hello]', 'x'],
            '[\n'
            "  1: 'hello]'\n"
            "  2: 'x'\n"
            ']',
        )

    def test_simple_list_inside_complex_list(self) -> None:
        self.check_render(
            [[1, 2], [3, 4]],
            '[\n'
            '  1: [1, 2]\n'
            '  2: [3, 4]\n'
            ']',
        )

    def test_simple_list_inside_dictionary(self) -> None:
        self.check_render({'values': ['a', 123, True]}, "  values = ['a', 123, true]")

    def test_custom_indent_complex_list(self) -> None:
        self.check_render(
            [{'a': 1}, {'b': 2}],
            '[\n'
            '    1:\n'
            '        a = 1\n'
            '    2:\n'
            '        b = 2\n'
            ']',
            indent=4,
        )

