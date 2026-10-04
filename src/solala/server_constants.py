import logging

APP_NAME: str = 'Solala'

DATE_FORMAT = '%Y-%m-%d %H:%M:%S (%Z)'  # format for human-readable timestamps

SOLALA_LOG_NAME: str = APP_NAME.lower()
LOGGER = logging.getLogger(SOLALA_LOG_NAME)
SOLALA_LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

MAX_LOG_HISTORY: int = 1000
