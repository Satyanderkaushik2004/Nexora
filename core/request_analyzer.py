"""Keyword-based task classification: ``coding``, ``research`` or ``general``."""

from __future__ import annotations

import re

CODING_KEYWORDS = (
    "code", "coding", "program", "programming", "function", "script", "bug",
    "debug", "compile", "algorithm", "python", "javascript", "typescript",
    "java", "sql", "regex", "api", "refactor", "stack trace",
)
RESEARCH_KEYWORDS = (
    "research", "latest", "news", "recent", "current", "sources",
    "citation", "citations", "look up", "up to date",
)


def _compile(keywords: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(k) for k in keywords)
    return re.compile(rf"\b(?:{alternatives})\b")


_CODING = _compile(CODING_KEYWORDS)
_RESEARCH = _compile(RESEARCH_KEYWORDS)


def analyze(query: str) -> str:
    """Classify a query. Whole-word matching avoids hits like "decode"."""
    text = query.lower() if isinstance(query, str) else ""
    if _CODING.search(text):
        return "coding"
    if _RESEARCH.search(text):
        return "research"
    return "general"
