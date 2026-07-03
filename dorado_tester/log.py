"""Central logging setup for the harness's own operational messages (which
test case is running, warnings, errors) — distinct from each case's raw
Dorado stdout/stderr capture in results/<version>/logs/<test_name>.log."""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "dorado_tester"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
