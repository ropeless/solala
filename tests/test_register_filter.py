import unittest

from solala.server.register_filter import compile_register_filter


class RegisterFilterTestCase(unittest.TestCase):
    """
    Verify register-name pattern syntax.
    """

    def test_substring_and_empty(self) -> None:
        self.assertIsNotNone(compile_register_filter('abc/ef').match('cbaabc/efg/xyz'))
        self.assertIsNone(compile_register_filter('abc/ef').match('xyz'))
        self.assertIsNotNone(compile_register_filter('').match('anything'))

    def test_anchors(self) -> None:
        self.assertIsNotNone(compile_register_filter('^abc$').match('abc'))
        self.assertIsNone(compile_register_filter('^abc$').match('xabc'))
        self.assertIsNone(compile_register_filter('^abc$').match('abcd'))
        self.assertIsNotNone(compile_register_filter('abc$').match('xabc'))
        self.assertIsNone(compile_register_filter('abc$').match('abcd'))

    def test_wildcards(self) -> None:
        self.assertIsNotNone(compile_register_filter('a*c').match('abc'))
        self.assertIsNotNone(compile_register_filter('a*c').match('ac'))
        self.assertIsNotNone(compile_register_filter('a?c').match('abc'))
        self.assertIsNone(compile_register_filter('a?c').match('ac'))

    def test_escaped_metacharacters(self) -> None:
        for character in '^$*?\\':
            with self.subTest(character=character):
                matcher = compile_register_filter('\\' + character)
                self.assertIsNotNone(matcher.match('prefix' + character + 'suffix'))
        self.assertIsNotNone(compile_register_filter('a.b').match('xa.by'))
        self.assertIsNone(compile_register_filter('a.b').match('xazby'))

    def test_invalid_patterns(self) -> None:
        for pattern in ('a^b', 'a$b', '\\', '\\a', '^a^', '$a'):
            with self.subTest(pattern=pattern):
                with self.assertRaises(ValueError):
                    compile_register_filter(pattern)


if __name__ == '__main__':
    unittest.main()
