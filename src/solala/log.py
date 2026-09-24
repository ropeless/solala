import logging
import sys

LOGGER = logging.getLogger('solala')


def configure_logger():
    """
    Set up the stand log handler
    """
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    stdout_handler.setFormatter(formatter)
    LOGGER.addHandler(stdout_handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
