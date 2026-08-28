"""The structured error every CLI failure is reported through."""

from __future__ import annotations

from typing import Any


class CalcCliError(Exception):
    def __init__(self, code: str, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []
