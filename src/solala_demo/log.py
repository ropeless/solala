import logging
import sys

from solala.utils.local_config_help import config
from solala.logger import LOGGER


def configure_logger(level: int | str = logging.INFO):
    """
    Set up the stdout log handler for the Solala logger
    """
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    formatter = logging.Formatter(config.DEMO_LOG_FORMAT)
    stdout_handler.setFormatter(formatter)
    LOGGER.addHandler(stdout_handler)
    LOGGER.setLevel(level)
    LOGGER.propagate = False
