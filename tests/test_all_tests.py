"""
Test module discovery for the custom unittest runner.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tests import all_tests


class TestModuleDiscovery(TestCase):
    """
    Check which files are included in recursive test discovery.
    """

    def test_discovers_python_test_modules_only(self) -> None:
        """
        Include nested Python tests and ignore similarly named data files.
        """
        directory = self.enterContext(TemporaryDirectory(dir=Path(__file__).resolve().parent))
        root = Path(directory)
        nested = root / 'nested'
        nested.mkdir()
        (nested / '__init__.py').touch()
        (nested / 'test_nested.py').touch()
        (root / 'test_example.py').touch()
        (root / 'test_projects.xlsx').touch()
        (root / 'helpers.py').touch()

        with patch.dict(vars(all_tests), {'__file__': str(root / 'all_tests.py')}):
            self.assertCountEqual(
                all_tests.test_modules(),
                [f'{root.name}.test_example', f'{root.name}.nested.test_nested'],
            )
