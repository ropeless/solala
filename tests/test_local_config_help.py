import os
import unittest
from unittest import TestCase, main

from solala.utils.local_config_help import config, update_config, get_params


class TestConfigHelp(TestCase):

    def test_update(self):
        valid_vars = ['A', 'B', 'C']
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv, valid_vars)

        self.assertEqual(config.A, 1)
        self.assertEqual(config.B, '2')
        self.assertEqual(config.C, [3, 4])

    def test_update_invalid_vars(self):
        valid_vars = ['A', 'B', 'C']
        argv = ['D=3']

        with self.assertRaises(KeyError):
            update_config(argv, valid_vars)

    def test_update_all_valid_vars(self):
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv)

        self.assertEqual(config.A, 1)
        self.assertEqual(config.B, "2")
        self.assertEqual(config.C, [3, 4])

    def test_override(self):
        config['A'] = 'totally okay'
        self.assertEqual(config.A, 'totally okay')
        self.assertEqual(config['A'], 'totally okay')
        self.assertEqual(config.get('A'), 'totally okay')

        config['A'] = 123
        self.assertEqual(config.A, 123)
        self.assertEqual(config['A'], 123)
        self.assertEqual(config.get('A'), 123)
        self.assertEqual(config.get('A', 'B'), 123)

        config['A'] = 123.456
        self.assertEqual(config.A, 123.456)
        self.assertEqual(config['A'], 123.456)
        self.assertEqual(config.get('A'), 123.456)
        self.assertEqual(config.get('A', 'B'), 123.456)

        config['A'] = True
        self.assertEqual(config.A, True)
        self.assertEqual(config['A'], True)
        self.assertEqual(config.get('A'), True)
        self.assertEqual(config.get('A', 'B'), True)

        config['A'] = None
        self.assertEqual(config.A, None)
        self.assertEqual(config['A'], None)
        self.assertEqual(config.get('A'), None)
        self.assertEqual(config.get('A', 'B'), None)

        config['A'] = [1, 2, 3, 4]
        self.assertEqual(config.A, [1, 2, 3, 4])
        self.assertEqual(config['A'], [1, 2, 3, 4])
        self.assertEqual(config.get('A'), [1, 2, 3, 4])
        self.assertEqual(config.get('A', 'B'), [1, 2, 3, 4])

        config['A'] = (1, 2, 3, 4)
        self.assertEqual(config.A, (1, 2, 3, 4))
        self.assertEqual(config['A'], (1, 2, 3, 4))
        self.assertEqual(config.get('A'), (1, 2, 3, 4))
        self.assertEqual(config.get('A', 'B'), (1, 2, 3, 4))

        config['A'] = {1, 2, 3, 4}
        self.assertEqual(config.A, {1, 2, 3, 4})
        self.assertEqual(config['A'], {1, 2, 3, 4})
        self.assertEqual(config.get('A'), {1, 2, 3, 4})
        self.assertEqual(config.get('A', 'B'), {1, 2, 3, 4})

        config['A'] = {'1': 1, '2': 2, '3': 3, '4': 4}
        self.assertEqual(config.A, {'1': 1, '2': 2, '3': 3, '4': 4})
        self.assertEqual(config['A'], {'1': 1, '2': 2, '3': 3, '4': 4})
        self.assertEqual(config.get('A'), {'1': 1, '2': 2, '3': 3, '4': 4})
        self.assertEqual(config.get('A', 'B'), {'1': 1, '2': 2, '3': 3, '4': 4})

    def test_missing(self):
        # Note: We have no idea what is already in the configuration,
        # but we assume this key is not in it.
        key = '_ck_valid_test_key_that_should_not_exist__test_missing_'
        assert key not in config, 'test assumption'

        with self.assertRaises(KeyError):
            _ = config[key]

        with self.assertRaises(KeyError):
            getattr(config, key)

        self.assertIsNone(config.get(key))
        self.assertEqual(config.get(key, 'abc'), 'abc')

        # Just confirm we can actually use that key.
        config[key] = 123
        self.assertEqual(config[key], 123)
        self.assertEqual(getattr(config, key), 123)
        self.assertEqual(config.get(key), 123)
        self.assertEqual(config.get(key, 'abc'), 123)

    def test_os_environ(self):
        # Note: We have no idea what is already in the configuration,
        # but we assume this key is not in it.
        key = '_ck_valid_test_key_that_should_not_exist__test_os_environ_'
        assert key not in config, 'test assumption'

        os.environ[key] = 'abc'
        self.assertEqual(config[key], 'abc')

    def test_invalid_key(self):
        bad_key = 'ck:test_bad_key:my really bad key'

        with self.assertRaises(KeyError):
            _ = config[bad_key]

        with self.assertRaises(KeyError):
            config[bad_key] = 'a value'

    def test_invalid_value(self):
        with self.assertRaises(ValueError):
            config['A'] = unittest

        with self.assertRaises(ValueError):
            config['A'] = lambda x: x + x

        with self.assertRaises(ValueError):
            config['A'] = TestConfigHelp

        with self.assertRaises(ValueError):
            config['A'] = TestConfigHelp.test_invalid_value

        with self.assertRaises(ValueError):
            config['A'] = main

    def test_strip_whitespace(self):
        argv = ['B =  what   ']

        update_config(argv, strip_whitespace=False)
        self.assertEqual(config.B, '  what   ')

        update_config(argv, strip_whitespace=True)
        self.assertEqual(config.B, 'what')

    def test_get_params(self):
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv)

        self.assertEqual(get_params('A'), ('A', 1))
        self.assertEqual(get_params('B'), ('B', '2'))
        self.assertEqual(get_params('C'), ('C', [3, 4]))
        self.assertEqual(get_params('A', 'B'), (('A', 1), ('B', '2')))

    def test_get_params_with_sep(self):
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv)

        self.assertEqual(get_params('A', sep='='), 'A=1')
        self.assertEqual(get_params('B', sep='='), "B='2'")
        self.assertEqual(get_params('C', sep='='), "C=[3, 4]")
        self.assertEqual(get_params('A', 'B', sep='='), ('A=1', "B='2'"))

    def test_get_params_with_delim(self):
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv)

        self.assertEqual(get_params('A', 'B', 'C', delim=';'), "A=1;B='2';C=[3, 4]")
        self.assertEqual(get_params('A;B;C', delim=';'), "A=1;B='2';C=[3, 4]")
        self.assertEqual(get_params('A;B;C', delim=';', sep='=='), "A==1;B=='2';C==[3, 4]")

    def test_bad_params_cannot_split(self):
        argv = ['A=1', 'B', 'C=[3,4]']
        with self.assertRaises(ValueError):
            update_config(argv)


if __name__ == '__main__':
    main()
