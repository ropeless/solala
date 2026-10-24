import logging

from solala.constants import APP_NAME

SOLALA_LOG_NAME: str = APP_NAME.lower()
LOGGER = logging.getLogger(SOLALA_LOG_NAME)
SOLALA_LOG_FORMAT: str = '%(levelname)s: %(name)s %(message)s'
