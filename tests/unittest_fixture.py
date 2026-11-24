"""
Provide suite assembly and additional assertions for unittest tests.
"""

import math
from collections.abc import Collection, Iterable, Iterator, Mapping, Sized
from importlib import import_module as _import
from itertools import zip_longest
from typing import Any, SupportsFloat, SupportsIndex
from unittest import \
    TestCase, \
    main as _unittest_main, \
    defaultTestLoader as _testLoader, \
    TestSuite as _TestSuite
from unittest.main import TestProgram

import numpy as np


def test_main() -> TestProgram:
    """
    Execute unittest.main().
    """
    return _unittest_main()


def make_suit(test_modules: Iterable[str], package: str | None = None) -> _TestSuite:
    """
    Build a test suite from the named modules.

    Args:
        test_modules: Module names to load.
        package: Optional package prefix for the module names.

    Returns:
        The combined suite of custom or discovered tests.
    """
    suite = _TestSuite()
    for name in test_modules:
        module_name = name if package is None else f'{package}.{name}'
        module = _import(module_name)
        try:
            custom_suite = getattr(module, 'suite')
        except AttributeError:
            suite.addTest(_testLoader.loadTestsFromModule(module))
        else:
            suite.addTest(custom_suite())
    return suite


class Fixture(TestCase):
    """
    Extend unittest with assertions for collections, NumPy arrays, and iterators.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """
        Register NumPy array equality alongside the standard assertions.
        """
        super().__init__(*args, **kwargs)
        self.addTypeEqualityFunc(np.ndarray, self.assertNDArrayEqual)

    def assertEmpty(self, got: Sized, *, msg: str | None = None) -> None:
        """
        Assert that the value has length zero.
        """
        self.assertEqual(len(got), 0, msg=msg)

    def assertNotEmpty(self, got: Sized, *, msg: str | None = None) -> None:
        """
        Assert that the value has a nonzero length.
        """
        self.assertNotEqual(len(got), 0, msg=msg)

    def assertNan(self, got: SupportsFloat | SupportsIndex, *, msg: str | None = None) -> None:
        """
        Assert that the numeric value is NaN.
        """
        self.assertTrue(math.isnan(got), msg=msg)

    def assertArrayEqual(
        self, got: Collection[Any], expect: Collection[Any], *,
        msg: str | None = None, nan_equality: bool = False,
    ) -> None:
        """
        Compare the positions and values of elements in nested collections.
        """
        self.assertEqual(len(got), len(expect), msg=msg)
        for got_pair, expect_pair in zip_longest(_iter_index_value(got), _iter_index_value(expect)):
            if got_pair is None or expect_pair is None:
                self.fail(_make_msg(msg, 'unmatched array element: got ', got_pair, ', expected ', expect_pair))
            got_idx, got_item = got_pair
            expect_idx, expect_item = expect_pair
            self.assertEqual(
                got_idx,
                expect_idx,
                msg=_make_msg(msg, 'shapes diverge: expected index ', expect_idx, ', got index: ', got_idx)
            )
            if nan_equality and math.isnan(got_item) and math.isnan(expect_item):
                continue
            idx_str = str(expect_idx[0]) if len(expect_idx) == 1 else str(expect_idx)
            self.assertEqual(
                got_item,
                expect_item,
                msg=_make_msg(msg, "at index ", idx_str, ": expected ", expect_item, ", got: ", got_item)
            )

    def assertArrayAlmostEqual(
        self, got: Collection[Any], expect: Collection[Any], *,
        places: int | None = None, delta: Any = None,
        msg: str | None = None, nan_equality: bool = False,
    ) -> None:
        """
        Compare nested collections using unittest's numeric tolerance.
        """
        self.assertEqual(len(got), len(expect), msg=msg)
        for got_pair, expect_pair in zip_longest(_iter_index_value(got), _iter_index_value(expect)):
            if got_pair is None or expect_pair is None:
                self.fail(_make_msg(msg, 'unmatched array element: got ', got_pair, ', expected ', expect_pair))
            got_idx, got_item = got_pair
            expect_idx, expect_item = expect_pair
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

    def assertNDArrayEqual(
        self, got: np.ndarray, expect: np.ndarray, *,
        msg: str | None = None, nan_equality: bool = False,
    ) -> None:
        """
        Compare NumPy array shapes and corresponding values exactly.
        """
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
            places: int | None = None,
            delta: Any = None,
            msg: str | None = None,
            nan_equality: bool = False,
    ) -> None:
        """
        Compare NumPy array shapes and values using unittest's numeric tolerance.
        """
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

    def assertArraySetEqual(
        self, got: Collection[Any], expect: Collection[Any], *, msg: str | None = None,
    ) -> None:
        """
        Compare collection lengths and unique elements, ignoring order.
        """
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
            places: int | None = None,
            delta: Any = None,
            msg: str | None = None,
    ) -> None:
        """
        Compare mapping keys and values using unittest's numeric tolerance.
        """
        self.assertEqual(set(a), set(b), msg=msg)
        for key, value in a.items():
            self.assertAlmostEqual(value, b[key], places=places, delta=delta, msg=msg)

    def assertIterFinished(self, it: Iterator[Any], *, msg: str | None = None) -> None:
        """
        Assert that the next call to the iterator raises StopIteration.

        Args:
            it: an iterator which is expected to throw StopIteration
                when next(it) is called.
            msg: an optional message to pass to `assertRaises`.
        """
        with self.assertRaises(StopIteration, msg=msg):
            next(it)


def _make_msg(orig_msg: str | None, *parts: object) -> str:
    """
    Construct an error message.
    """
    msg = ''.join(str(part) for part in parts)
    if orig_msg is not None:
        msg += ", "
        msg += str(orig_msg)
    return msg


def _iter_index_value(iterable: Any) -> Iterator[tuple[tuple[int, ...], Any]]:
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
