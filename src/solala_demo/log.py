import logging
import sys

from solala.logger import LOGGER
from local_config import DEMO_LOG_FORMAT


def configure_logger():
    """
    Set up the stdout log handler for the Solala logger
    """
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(DEMO_LOG_FORMAT)
    stdout_handler.setFormatter(formatter)
    LOGGER.addHandler(stdout_handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
