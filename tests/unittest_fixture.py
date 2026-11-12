import math
from importlib import import_module as _import
from typing import Iterable, Optional, Mapping, Any, Iterator, Tuple
from unittest import \
    TestCase, \
    main as _unittest_main, \
    defaultTestLoader as _testLoader, \
    TestSuite as _TestSuite

import numpy as np


def test_main():
    """
    Execute unittest.main().
    """
    return _unittest_main()


def make_suit(test_modules: Iterable[str], package: Optional[str] = None):
    """
        Construct a `unittest.TestSuite` object containing all the unit test in the named test modules.

        Args:
            test_modules: a collection of strings, each naming a test module.
            package: optional argument for prefixing each test module.

        Returns:
            a `unittest.TestSuite` object.
        """
    suite = _TestSuite()
    for t in test_modules:
        test_module = t if package is None else f'{package}.{t}'
        try:
            # if the module defines a suite() function, call it to get the suite.
            module_t = _import(test_module)
            suite_t = getattr(module_t, 'suite')
            suite.addTest(suite_t())
        except (ImportError, AttributeError):
            # load all the test cases from the module
            suite.addTest(_testLoader.loadTestsFromName(t))
    return suite


class Fixture(TestCase):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.addTypeEqualityFunc(np.ndarray, self.assertNDArrayEqual)

    def assertEmpty(self, got, *, msg=None):
        self.assertEqual(len(got), 0, msg=msg)

    def assertNotEmpty(self, got, *, msg=None):
        self.assertNotEqual(len(got), 0, msg=msg)

    def assertNan(self, got, *, msg=None):
        self.assertTrue(math.isnan(got), msg=msg)

    def assertArrayEqual(self, got, expect, *, msg=None, nan_equality: bool = False):
        self.assertEqual(len(got), len(expect), msg=msg)
        for (got_idx, got_item), (expect_idx, expect_item) in zip(_iter_index_value(got), _iter_index_value(expect)):
            self.assertEqual(
                got_idx,
                expect_idx,
                msg=_make_msg(msg, "shapes diverge: expected index", expect_idx, ", got index: ", expect_idx)
            )
            if nan_equality and math.isnan(got_item) and math.isnan(expect_item):
                continue
            idx_str = str(expect_idx[0]) if len(expect_idx) == 1 else str(expect_idx)
            self.assertEqual(
                got_item,
                expect_item,
                msg=_make_msg(msg, "at index ", idx_str, ": expected ", expect_item, ", got: ", got_item)
            )

    def assertArrayAlmostEqual(self, got, expect, *, places=None, delta=None, msg=None, nan_equality: bool = False):
        self.assertEqual(len(got), len(expect), msg=msg)
        for (got_idx, got_item), (expect_idx, expect_item) in zip(_iter_index_value(got), _iter_index_value(expect)):
            self.assertEqual(
                got_idx,
                expect_idx,
                msg=_make_msg(msg, "shapes diverge: expected index", expect_idx, ", got index: ", expect_idx)
            )
            if nan_equality and math.isnan(got_item) and math.isnan(expect_item):
                continue
            idx_str = str(expect_idx[0]) if len(expect_idx) == 1 else str(expect_idx)
            self.assertAlmostEqual(
                got_item,
                expect_item,
                places=places,
                delta=delta,
                msg=_make_msg(msg, "at index ", idx_str, ": expected ", expect_item, ", got: ", got_item)
            )

    def assertNDArrayEqual(self, got: np.ndarray, expect: np.ndarray, *, msg=None, nan_equality: bool = False):
        self.assertEqual(got.shape, expect.shape, msg=_make_msg(msg, "shape: expected ", expect, ", got: ", got))
        for idx in np.ndindex(expect.shape):
            got_i = got.item(idx)
            expect_i = expect.item(idx)
            if nan_equality and np.isnan(got_i) and np.isnan(expect_i):
                continue
            idx_str = str(idx[0]) if len(idx) == 1 else str(idx)
            self.assertEqual(
                got_i,
                expect_i,
                msg=_make_msg(msg, "at index ", idx_str, ": expected ", expect_i, ", got: ", got_i)
            )

    def assertNDArrayAlmostEqual(
            self,
            got: np.ndarray,
            expect: np.ndarray,
            *,
            places=None,
            delta=None,
            msg=None,
            nan_equality: bool = False,
    ):
        self.assertEqual(got.shape, expect.shape, msg=_make_msg(msg, "shape: expected ", expect, ", got: ", got))
        for idx in np.ndindex(expect.shape):
            got_i = got.item(idx)
            expect_i = expect.item(idx)
            if nan_equality and np.isnan(got_i) and np.isnan(expect_i):
                continue
            idx_str = str(idx[0]) if len(idx) == 1 else str(idx)
            self.assertAlmostEqual(
                got_i,
                expect_i,
                places=places,
                delta=delta,
                msg=_make_msg(msg, "at index ", idx_str, ": expected ", expect_i, ", got: ", got_i)
            )

    def assertArraySetEqual(self, got, expect, *, msg=None):
        len_expect = len(expect)
        self.assertEqual(len(got), len(expect), msg=msg)
        expect = set(expect)
        got = set(got)
        self.assertEqual(len(expect), len_expect, msg=msg)
        self.assertEqual(len(expect), len(got), msg=msg)
        for elem in expect:
            self.assertIn(
                elem,
                got,
                msg=_make_msg(msg, "expected ", expect, ", got: ", got)
            )

    def assertDictAlmostEqual(
            self,
            a: Mapping[Any, float],
            b: Mapping[Any, float],
            *,
            places=None,
            delta=None,
            msg=None,
    ):
        self.assertEqual(len(a), len(b), msg=msg)
        for key, value in a.items():
            self.assertAlmostEqual(value, b[key], places=places, delta=delta, msg=msg)

    def assertIterFinished(self, it, *, msg=None):
        """
        Args:
            it: an iterator which is expected to throw StopIteration
                when next(it) is called.
            msg: an optional message to pass to `assertRaises`.
        """
        with self.assertRaises(StopIteration, msg=msg):
            next(it)


def _make_msg(orig_msg, *parts):
    """
    Construct an error message.
    """
    msg = ''.join(str(part) for part in parts)
    if orig_msg is not None:
        msg += ", "
        msg += str(orig_msg)
    return msg


def _iter_index_value(iterable: Any) -> Iterator[Tuple[Tuple[int, ...], Any]]:
    """
    Iterate over (index, value) pairs, where index is a multidimensional
    index into the given iterable.

    This enables testing of arbitrarily nested iterables.
    """
    if isinstance(iterable, np.ndarray):
        # Treat numpy arrays specially
        for idx in np.ndindex(iterable.shape):
            yield idx, iterable.item(idx)
    elif isinstance(iterable, (str, bytes)):
        # Treat strings specially
        yield (), iterable
    elif hasattr(iterable, '__iter__'):
        for idx, item in enumerate(iterable):
            for c_idx, c_item in _iter_index_value(item):
                yield (idx,) + c_idx, c_item
    else:
        yield (), iterable
