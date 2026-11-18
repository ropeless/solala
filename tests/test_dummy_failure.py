import unittest

from pydantic import BaseModel, ValidationError

from solala.utils.dummy_failure import SerializableException


class _FailureSettings(BaseModel):
    exception: SerializableException | None = None


class SerializableExceptionTestCase(unittest.TestCase):
    """
    Verify supported exceptions round-trip through Pydantic JSON.
    """

    def test_supported_exceptions_round_trip(self):
        for exception_type in (RuntimeError, TimeoutError, ConnectionError, OSError, ValueError):
            for args in ((), ('simulated failure',)):
                with self.subTest(exception_type=exception_type, args=args):
                    settings = _FailureSettings(exception=exception_type(*args))
                    restored = _FailureSettings.model_validate_json(settings.model_dump_json())
                    self.assertIs(type(restored.exception), exception_type)
                    self.assertEqual(restored.exception.args, args)

    def test_python_dump_keeps_exception_instance(self):
        exception = TimeoutError('simulated timeout')
        settings = _FailureSettings(exception=exception)
        self.assertIs(settings.model_dump()['exception'], exception)

    def test_reject_unsupported_exception(self):
        with self.assertRaises(ValidationError):
            _FailureSettings(exception=KeyError('unsupported'))

    def test_reject_multiple_or_non_string_arguments(self):
        for exception in (RuntimeError('first', 'second'), RuntimeError(42)):
            with self.subTest(exception=exception):
                with self.assertRaises(ValidationError):
                    _FailureSettings(exception=exception)

    def test_reject_unknown_exception_name(self):
        with self.assertRaises(ValidationError):
            _FailureSettings.model_validate({'exception': {'type': 'KeyError', 'message': 'bad'}})

    def test_reject_extra_fields(self):
        with self.assertRaises(ValidationError):
            _FailureSettings.model_validate({
                'exception': {'type': 'TimeoutError', 'message': 'bad', 'module': 'builtins'}
            })

    def test_none_round_trip(self):
        self.assertIsNone(_FailureSettings.model_validate_json(_FailureSettings().model_dump_json()).exception)


if __name__ == '__main__':
    unittest.main()
