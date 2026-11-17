import asyncio
import re
import unittest
from collections.abc import Mapping

from solala.register import AsyncCallRegister, ConstantRegister
from solala.register_bank import RegisterBank


class RegisterBankTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_mapping_contains_registers(self) -> None:
        register = ConstantRegister(42)
        bank = RegisterBank({'a': register, 'b': 3})

        self.assertIsInstance(bank, Mapping)
        self.assertIs(bank['a'], register)
        self.assertEqual(set(bank), {'a', 'b'})
        self.assertEqual(len(bank), 2)
        self.assertEqual(await bank['b'].get(), 3)
        with self.assertRaises(TypeError):
            bank['c'] = register  # type: ignore[index]

    async def test_bulk_read_captures_errors_and_continues(self) -> None:
        error = OSError('device unavailable')
        calls: list[str] = []

        async def failed() -> int:
            calls.append('failed')
            raise error

        async def succeeded() -> int:
            calls.append('succeeded')
            return 7

        bank = RegisterBank({
            'failed': AsyncCallRegister(failed, int),
            'succeeded': AsyncCallRegister(succeeded, int),
        })
        results = await bank.get_register_values()
        self.assertIs(results['failed'], error)
        self.assertEqual(results['succeeded'], 7)
        self.assertEqual(calls, ['failed', 'succeeded'])

    async def test_bulk_read_pattern(self) -> None:
        bank = RegisterBank({'a/one': 1, 'b/two': 2})
        self.assertEqual(
            await bank.get_register_values(re.compile('a/')),
            {'a/one': 1},
        )

    async def test_cancellation_propagates(self) -> None:
        async def cancelled() -> int:
            raise asyncio.CancelledError()

        bank = RegisterBank({'a': AsyncCallRegister(cancelled, int)})
        with self.assertRaises(asyncio.CancelledError):
            await bank.get_register_values()
