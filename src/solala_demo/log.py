import logging
import sys

from solala.server_constants import SOLALA_LOG_FORMAT, LOGGER


def configure_logger():
    """
    Set up the stdout log handler for the Solala logger
    """
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    formatter = logging.Formatter(SOLALA_LOG_FORMAT)
    stdout_handler.setFormatter(formatter)
    LOGGER.addHandler(stdout_handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
