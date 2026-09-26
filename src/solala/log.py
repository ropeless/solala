import logging
import sys

SOLALA_LOG_NAME = 'solala'
LOGGER = logging.getLogger(SOLALA_LOG_NAME)
SOLALA_LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


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
