import importlib.resources as resources
from importlib.resources.abc import Traversable

# Where to find data files
ROOT_DIR: Traversable = resources.files('solala.resources')
HTML_FILES: Traversable = ROOT_DIR / 'html'
