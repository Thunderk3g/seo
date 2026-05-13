"""Logger factory — delegates to Django's stdlib logging.

Port of ``crawler-engine/app/core/logger.py``. Returns named loggers that
inherit Django's configured handlers/formatters (see settings.LOGGING) so
crawler output shows up alongside Django logs without extra wiring.
"""
from __future__ import annotations

import logging
from logging import Logger


def get_logger(name: str) -> Logger:
    return logging.getLogger(name)
