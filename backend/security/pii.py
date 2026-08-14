"""PII masking.

Masks sensitive column names and values before results reach the browser or
the LLM. Two layers:

- column-name patterns (ssn, credit_card, phone, email, pan, aadhaar, dob...)
- value content regexes for common sensitive formats
"""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_COLUMN_PATTERNS = [
    r"ssn",
    r"social\s*security",
    r"credit\s*card",
    r"card\s*number",
    r"ccv",
    r"cvv",
    r"pan\b",
    r"aadhaar",
    r"password",
    r"passwd",
    r"pwd",
    r"secret",
    r"token",
    r"api\s*key",
    r"access\s*key",
    r"phone",
    r"mobile",
    r"contact\s*number",
    r"email",
    r"dob",
    r"date\s*of\s*birth",
    r"bank\s*account",
    r"account\s*number",
    r"ifsc",
    r"driving\s*license",
    r"passport",
    r"blood\s*group",
]

VALUE_PATTERNS = [
    re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"),  # generic card
    re.compile(r"\b\d{3}[- ]?\d{2}[- ]?\d{4}\b"),  # SSN-like
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"),  # PAN-like
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),  # email
    re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # phone
]


def is_sensitive_column(name: str) -> bool:
    lowered = name.lower()
    return any(re.search(p, lowered) for p in SENSITIVE_COLUMN_PATTERNS)


def mask_value(value: Any) -> Any:
    if value is None:
        return None
    text = str(value)
    for pattern in VALUE_PATTERNS:
        if pattern.search(text):
            return "***"
    return value


def redact_columns(column_names: list[str]) -> dict[str, str]:
    """Return a mapping of original->redacted column names for sensitive ones."""
    mapping: dict[str, str] = {}
    for col in column_names:
        if is_sensitive_column(col):
            mapping[col] = col + "_redacted"
    return mapping


def redact_rows(columns: list[str], rows: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    """Redact sensitive values in place-aware fashion.

    Returns (display_columns, redacted_rows). Sensitive columns are renamed
    with a `_redacted` suffix and their values masked.
    """
    rename = redact_columns(columns)
    display_cols = [rename.get(c, c) for c in columns]
    sensitive_idx = [i for i, c in enumerate(columns) if c in rename]
    out_rows: list[list[Any]] = []
    for row in rows:
        new_row = list(row)
        for idx in sensitive_idx:
            if idx < len(new_row):
                new_row[idx] = mask_value(new_row[idx])
        out_rows.append(new_row)
    return display_cols, out_rows