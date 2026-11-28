# Testing protocol

## Framework and layout

- Write unit tests with Python's standard-library `unittest` package.
- Place test modules under `tests/`. Use subfolders when they make the
  tests easier to understand.
- Name each module `test_XXXX.py`, where `XXXX` identifies the package,
  module, or other unit under test.

## Test-driven development

Prefer test-driven development (TDD). Before changing behaviour, write and run
a test for the intended result. For a bug fix, confirm that the regression test
fails for the expected reason before implementing the fix. If the test passes
before the fix, investigate why and discuss the result before proceeding.
After applying the fix, rerun the test and confirm that it passes.

## Test isolation

- Keep test inputs and fixtures under `src/` or `tests/`.
- Keep generated fixtures in a temporary directory under `tests/` and clean them up after the test.
- Never read or write files to any other directory in a unit test.
- Unit tests and the code they exercise must neither write to stdout or
  stderr nor require input from stdin. The one exception is that the test runner may report results.
- Unit tests must run without network operations.
- Unit tests should never depend on files covered by `.gitignore`.

## Running the suite

Install the test dependencies with `poetry install --with test`. Run the full
suite from the project root in PowerShell with the project environment
active. The project runner honours module-level `suite()`
functions.

```powershell
$env:PYTHONPATH = 'src'
python -m tests.all_tests
```

To run a single regression during development, use its qualified test name
with the same environment:

```powershell
python -m unittest tests.test_unittest_fixture.DictionaryComparisonTests.test_rejects_different_keys_at_equal_length
```
