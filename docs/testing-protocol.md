# Testing protocol

## Framework and layout

- Write unit tests with Python's standard-library `unittest` package.
- Place test modules under `tests/`. Use subfolders when they make the suite
  easier to navigate.
- Name each module `test_XXXX.py`, where `XXXX` identifies the package,
  module, or other unit under test.

## Test-driven development

Prefer test-driven development (TDD). Before changing behaviour, write and run
a test for the intended result. For a bug fix, confirm the regression test
fails for the expected reason, then implement the fix and rerun the test.

To be specific. When a bug is suspected: (1) write a failing regressions test,
(2) run the regression test and see it fail, (3) correct the bug, (4) run the
regression test and see it pass. If at step (2) an AI agent sees the regression
test pass, then do not continue but start a discussion.

## Test isolation

- Keep every project's test input and fixture under `src/` or `tests/`,
  including temporary files created by tests. Keep generated fixtures in a
  temporary directory under `tests/` and clean them up after the test.
- Never read or write files under `data/` or `private/` in a unit test.
- Unit tests and the code they exercise must neither write to stdout or
  stderr nor require input from stdin. The test runner may report results.
- Unit tests must run without network operations.

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
