import logging

from constants import LOGGING_LEVEL

logger = logging.getLogger(__name__)

logger.setLevel(LOGGING_LEVEL)

logging_format = "%(asctime)s: %(message)s"
formatter = logging.Formatter(logging_format, datefmt="%H:%M:%S")

handler = logging.StreamHandler()

handler.setFormatter(formatter)

logger.addHandler(handler)
