import importlib.resources as resources
from importlib.resources.abc import Traversable

# Where to find data files
RESOURCES: Traversable = resources.files('solala.resources')
IMAGE_FILES: Traversable = RESOURCES / 'images'
CSS_FILES: Traversable = RESOURCES / 'css'
