import logging

from solala.constants import APP_NAME

SOLALA_LOG_NAME: str = APP_NAME.lower()
LOGGER = logging.getLogger(SOLALA_LOG_NAME)
SOLALA_LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
