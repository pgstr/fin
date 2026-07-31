from __future__ import annotations

from typing import Any


class AppError(Exception):
    def __init__(self, code: str, message_key: str, *, status_code: int = 400, details: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.message_key = message_key
        self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("not_found", "error.not_found", status_code=404)


class PermissionDeniedError(AppError):
    def __init__(self) -> None:
        super().__init__("permission_denied", "error.permission_denied", status_code=403)


class ConflictError(AppError):
    def __init__(self, code: str = "conflict", message_key: str = "error.conflict") -> None:
        super().__init__(code, message_key, status_code=409)


class ValidationError(AppError):
    def __init__(self, code: str, message_key: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message_key, status_code=422, details=details)

