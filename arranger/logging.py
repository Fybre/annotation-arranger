"""Application-only diagnostic logging; never enable HTTP wire/payload logging."""

import logging
import sys
from contextvars import ContextVar

request_id = ContextVar("request_id", default="-")
logger = logging.getLogger("arranger")


class RequestContext(logging.Filter):
    def filter(self, record):
        record.request_id = request_id.get()
        return True


def configure_logging(enabled):
    # Keep dependency loggers at their normal levels: HTTP wire logs can expose tokens.
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestContext())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s request=%(request_id)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if enabled else logging.CRITICAL + 1)
    logger.propagate = False
    logger.debug("Debug logging enabled")
