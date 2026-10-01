"""Structured, credential-safe logging for NEXORA AI Router.

Design rules:
  * User prompts are never logged -- only metadata such as length.
  * Every formatted record (including tracebacks) passes through a redactor
    that masks API-key-shaped strings, bearer tokens, and any secret values
    registered at startup.
"""

from __future__ import annotations

import logging
import re
import sys

_LOGGER_NAME = "nexora"

_PATTERNS = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;'\"]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [REDACTED]"),
    (re.compile(r"\b(?:sk|pplx|key)-[A-Za-z0-9_-]{8,}"), "[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;'\"]+"), r"\1[REDACTED]"),
]

_registered_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Mask an exact secret value everywhere it might appear in a log line."""
    if value and len(value) >= 6:
        _registered_secrets.add(value)


def redact(text: str) -> str:
    for secret in _registered_secrets:
        text = text.replace(secret, "[REDACTED]")
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            _RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)


def log_event(event: str, level: int = logging.INFO, **fields: object) -> None:
    """Emit ``event key=value ...``. Callers must never pass prompt text."""
    parts = [event] + [f"{key}={value}" for key, value in fields.items()]
    get_logger().log(level, " ".join(parts))
