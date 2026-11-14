import os
import unittest
from unittest import TestCase, main
from unittest.mock import patch

from solala.utils.local_config_help import Config, update_config, get_params


class TestConfigHelp(TestCase):

    def setUp(self) -> None:
        self.config = Config()


    def test_update(self):
        valid_vars = ['A', 'B', 'C']
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv, valid_vars, local_config=self.config)

        self.assertEqual(self.config.A, 1)
        self.assertEqual(self.config.B, '2')
        self.assertEqual(self.config.C, [3, 4])

    def test_update_invalid_vars(self):
        valid_vars = ['A', 'B', 'C']
        argv = ['D=3']

        with self.assertRaises(KeyError):
            update_config(argv, valid_vars, local_config=self.config)

    def test_update_all_valid_vars(self):
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv, local_config=self.config)

        self.assertEqual(self.config.A, 1)
        self.assertEqual(self.config.B, "2")
        self.assertEqual(self.config.C, [3, 4])

    def test_override(self):
        self.config['A'] = 'totally okay'
        self.assertEqual(self.config.A, 'totally okay')
        self.assertEqual(self.config['A'], 'totally okay')
        self.assertEqual(self.self.config.get('A'), 'totally okay')

        self.config['A'] = 123
        self.assertEqual(self.config.A, 123)
        self.assertEqual(self.config['A'], 123)
        self.assertEqual(self.self.config.get('A'), 123)
        self.assertEqual(self.self.config.get('A', 'B'), 123)

        self.config['A'] = 123.456
        self.assertEqual(self.config.A, 123.456)
        self.assertEqual(self.config['A'], 123.456)
        self.assertEqual(self.self.config.get('A'), 123.456)
        self.assertEqual(self.self.config.get('A', 'B'), 123.456)

        self.config['A'] = True
        self.assertEqual(self.config.A, True)
        self.assertEqual(self.config['A'], True)
        self.assertEqual(self.self.config.get('A'), True)
        self.assertEqual(self.self.config.get('A', 'B'), True)

        self.config['A'] = None
        self.assertEqual(self.config.A, None)
        self.assertEqual(self.config['A'], None)
        self.assertEqual(self.self.config.get('A'), None)
        self.assertEqual(self.self.config.get('A', 'B'), None)

        self.config['A'] = [1, 2, 3, 4]
        self.assertEqual(self.config.A, [1, 2, 3, 4])
        self.assertEqual(self.config['A'], [1, 2, 3, 4])
        self.assertEqual(self.self.config.get('A'), [1, 2, 3, 4])
        self.assertEqual(self.self.config.get('A', 'B'), [1, 2, 3, 4])

        self.config['A'] = (1, 2, 3, 4)
        self.assertEqual(self.config.A, (1, 2, 3, 4))
        self.assertEqual(self.config['A'], (1, 2, 3, 4))
        self.assertEqual(self.self.config.get('A'), (1, 2, 3, 4))
        self.assertEqual(self.self.config.get('A', 'B'), (1, 2, 3, 4))

        self.config['A'] = {1, 2, 3, 4}
        self.assertEqual(self.config.A, {1, 2, 3, 4})
        self.assertEqual(self.config['A'], {1, 2, 3, 4})
        self.assertEqual(self.self.config.get('A'), {1, 2, 3, 4})
        self.assertEqual(self.self.config.get('A', 'B'), {1, 2, 3, 4})

        self.config['A'] = {'1': 1, '2': 2, '3': 3, '4': 4}
        self.assertEqual(self.config.A, {'1': 1, '2': 2, '3': 3, '4': 4})
        self.assertEqual(self.config['A'], {'1': 1, '2': 2, '3': 3, '4': 4})
        self.assertEqual(self.self.config.get('A'), {'1': 1, '2': 2, '3': 3, '4': 4})
        self.assertEqual(self.self.config.get('A', 'B'), {'1': 1, '2': 2, '3': 3, '4': 4})

    def test_missing(self):
        # Note: We have no idea what is already in the configuration,
        # but we assume this key is not in it.
        key = '_ck_valid_test_key_that_should_not_exist__test_missing_'
        self.assertNotIn(key, self.config)

        with self.assertRaises(KeyError):
            _ = self.config[key]

        with self.assertRaises(AttributeError):
            getattr(self.config, key)

        self.assertIsNone(self.self.config.get(key))
        self.assertEqual(self.self.config.get(key, 'abc'), 'abc')

        # Just confirm we can actually use that key.
        self.config[key] = 123
        self.assertEqual(self.config[key], 123)
        self.assertEqual(getattr(self.config, key), 123)
        self.assertEqual(self.self.config.get(key), 123)
        self.assertEqual(self.self.config.get(key, 'abc'), 123)

    def test_os_environ(self):
        # Note: We have no idea what is already in the configuration,
        # but we assume this key is not in it.
        key = '_ck_valid_test_key_that_should_not_exist__test_os_environ_'
        assert key not in self.config, 'test assumption'

        with patch.dict(os.environ, {key: 'abc'}):
            self.assertEqual(self.config[key], 'abc')

    def test_invalid_key(self):
        bad_key = 'ck:test_bad_key:my really bad key'

        with self.assertRaises(KeyError):
            _ = self.config[bad_key]

        with self.assertRaises(AttributeError):
            getattr(self.config, bad_key)

        with self.assertRaises(KeyError):
            self.config[bad_key] = 'a value'

    def test_invalid_value(self):
        with self.assertRaises(ValueError):
            self.config['A'] = unittest

        with self.assertRaises(ValueError):
            self.config['A'] = lambda x: x + x

        with self.assertRaises(ValueError):
            self.config['A'] = TestConfigHelp

        with self.assertRaises(ValueError):
            self.config['A'] = TestConfigHelp.test_invalid_value

        with self.assertRaises(ValueError):
            self.config['A'] = main

    def test_strip_whitespace(self):
        argv = ['B =  what   ']

        update_config(argv, strip_whitespace=False, local_config=self.config)
        self.assertEqual(self.config.B, '  what   ')

        update_config(argv, strip_whitespace=True, local_config=self.config)
        self.assertEqual(self.config.B, 'what')

    def test_get_params(self, local_config=self.config):
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv, local_config=self.config)

        self.assertEqual(get_params('A'), ('A', 1), local_config=self.config)
        self.assertEqual(get_params('B'), ('B', '2'), local_config=self.config)
        self.assertEqual(get_params('C'), ('C', [3, 4]), local_config=self.config)
        self.assertEqual(get_params('A', 'B'), (('A', 1), ('B', '2')), local_config=self.config)

    def test_get_params_with_sep(self):
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv, local_config=self.config)

        self.assertEqual(get_params('A', sep='='), 'A=1', local_config=self.config)
        self.assertEqual(get_params('B', sep='='), "B='2'", local_config=self.config)
        self.assertEqual(get_params('C', sep='='), "C=[3, 4]", local_config=self.config)
        self.assertEqual(get_params('A', 'B', sep='='), ('A=1', "B='2'"), local_config=self.config)

    def test_get_params_with_delim(self):
        argv = ['A=1', 'B="2"', 'C=[3,4]']
        update_config(argv, local_config=self.config)

        self.assertEqual(get_params('A', 'B', 'C', delim=';'), "A=1;B='2';C=[3, 4]", local_config=self.config)
        self.assertEqual(get_params('A;B;C', delim=';'), "A=1;B='2';C=[3, 4]", local_config=self.config)
        self.assertEqual(get_params('A;B;C', delim=';', sep='=='), "A==1;B=='2';C==[3, 4]", local_config=self.config)

    def test_missing_attribute_and_hasattr(self):
        self.assertFalse(hasattr(self.config, 'NOT_DEFINED'))
        with self.assertRaises(AttributeError):
            _ = self.config.NOT_DEFINED
        with self.assertRaises(KeyError):
            _ = self.config['NOT_DEFINED']

        self.config['DEFINED'] = None
        self.assertTrue(hasattr(self.config, 'DEFINED'))
        self.assertIsNone(self.config.DEFINED)

    def test_get_params_empty_keys(self):
        self.assertEqual(get_params(local_config=self.config), ())
        self.assertEqual(get_params(sep='=', local_config=self.config), ())
        self.assertEqual(get_params(delim=';', local_config=self.config), '')

    def test_get_params_missing_key(self):
        with self.assertRaises(KeyError):
            get_params('NOT_DEFINED', local_config=self.config)
        with self.assertRaises(KeyError):
            get_params('NOT_DEFINED', sep='=', local_config=self.config)

    def test_get_params_empty_split_key(self):
        self.config['A'] = 1
        with self.assertRaises(KeyError):
            get_params('A;', delim=';', local_config=self.config)

    def test_bad_params_cannot_split(self):
        argv = ['A=1', 'B', 'C=[3,4]']
        with self.assertRaises(ValueError):
            update_config(argv, local_config=self.config)


if __name__ == '__main__':
    main()
