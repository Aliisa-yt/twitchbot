"""Shared, privacy-safe Google API error classification."""

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum, auto
from math import isfinite
from typing import Any

from google.api_core.exceptions import GoogleAPIError, ResourceExhausted, RetryError, TooManyRequests
from grpc import StatusCode

__all__: list[str] = ["APIErrorInfo", "APIErrorType", "APITransport", "classify_google_api_error"]


class APITransport(Enum):
    HTTP = auto()
    GRPC = auto()
    UNKNOWN = auto()


class APIErrorType(Enum):
    RATE_LIMIT = auto()
    DAILY_QUOTA = auto()
    QUOTA_UNKNOWN = auto()
    INVALID_REQUEST = auto()
    AUTHENTICATION = auto()
    PERMISSION_DENIED = auto()
    SERVICE_UNAVAILABLE = auto()
    TIMEOUT = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class APIErrorInfo:
    """Safe subset of a Google API error used for classification."""

    error_type: APIErrorType
    transport: APITransport
    http_status: int | None
    grpc_status: str | None
    reason: str | None
    detail_types: tuple[str, ...]
    retry_after_seconds: float | None
    retry_after_source: str | None
    transient: bool | None


def _detail_types(details: tuple[Any, ...]) -> tuple[str, ...]:
    allowed: set[str] = {"ErrorInfo", "RetryInfo", "QuotaFailure", "PreconditionFailure", "BadRequest"}
    return tuple[str, ...](sorted({type(detail).__name__ for detail in details if type(detail).__name__ in allowed}))


def _structured_reason(exc: Exception) -> tuple[str | None, tuple[Any, ...]]:  # noqa: C901
    reason: str | None = None
    details: tuple[Any, ...] = ()

    error_info = getattr(exc, "error_info", None)
    if error_info is not None:
        candidate = getattr(error_info, "reason", None)
        if isinstance(candidate, str) and candidate:
            reason = candidate

    raw_details = getattr(exc, "details", None)
    if isinstance(raw_details, tuple):
        details = raw_details
    elif isinstance(raw_details, list):
        details = tuple(raw_details)
    elif callable(raw_details):
        try:
            result = raw_details()
            if isinstance(result, tuple):
                details = result
            elif isinstance(result, list):
                details = tuple(result)
        except (TypeError, AttributeError, ValueError, RuntimeError):
            pass

    if reason is None:
        for detail in details:
            candidate = getattr(detail, "reason", None)
            if isinstance(candidate, str) and candidate:
                reason = candidate
                break
    return reason, details


def _http_retry_after(value: Any) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            seconds = max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
        except (OverflowError, TypeError, ValueError):
            return None

    return seconds if isfinite(seconds) and seconds >= 0 else None


def _retry_after(exc: Exception) -> tuple[float | None, str | None]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get("Retry-After")
        if value is not None:
            seconds = _http_retry_after(value)
            if seconds is not None:
                return seconds, "HTTP Retry-After"

    _, details = _structured_reason(exc)
    for detail in details:
        retry_delay = getattr(detail, "retry_delay", None)
        if retry_delay is not None:
            seconds = getattr(retry_delay, "seconds", None)
            nanos = getattr(retry_delay, "nanos", 0)
            if isinstance(seconds, int):
                total = float(seconds) + (float(nanos) / 1_000_000_000)
                if total >= 0:
                    return total, "gRPC RetryInfo"
    return None, None


def classify_google_api_error(exc: Exception) -> APIErrorInfo:  # noqa: C901, PLR0912, PLR0915
    """Classify an exception using transport status and allowlisted structured detail."""
    if isinstance(exc, RetryError):
        cause: Exception | None = getattr(exc, "cause", None)
        if cause is not None:
            return classify_google_api_error(cause)

    reason, details = _structured_reason(exc)
    detail_types = _detail_types(details)
    retry_after, retry_source = _retry_after(exc)

    http_status: int | None = None
    grpc_status: str | None = None
    transport = APITransport.UNKNOWN
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    has_http_response_status = isinstance(response_status, int)

    status_code_attr = getattr(exc, "code", None)
    if isinstance(status_code_attr, int):
        http_status = status_code_attr
        transport = APITransport.HTTP

    if has_http_response_status:
        http_status = response_status
        transport = APITransport.HTTP

    grpc_status_code = getattr(exc, "grpc_status_code", None)
    if grpc_status_code is not None:
        grpc_status = getattr(grpc_status_code, "name", str(grpc_status_code))
        if not has_http_response_status:
            transport = APITransport.GRPC

    code = getattr(exc, "code", None)
    if isinstance(code, StatusCode) and grpc_status is None:
        grpc_status = code.name
        transport = APITransport.GRPC

    reason_upper = reason.upper() if reason else ""
    type_name = type(exc).__name__.upper()

    if has_http_response_status and response_status == 429:
        error_type = APIErrorType.RATE_LIMIT
        transient = True
    elif isinstance(exc, ResourceExhausted):
        if "RATE_LIMIT" in reason_upper or "USER_RATE_LIMIT" in reason_upper:
            error_type = APIErrorType.RATE_LIMIT
            transient = True
        elif "DAILY_QUOTA" in reason_upper or "QUOTA_EXCEEDED" in reason_upper:
            error_type = APIErrorType.DAILY_QUOTA
            transient = False
        else:
            error_type = APIErrorType.QUOTA_UNKNOWN
            transient = None
    elif (
        isinstance(exc, TooManyRequests)
        or http_status == 429
        or "RATE_LIMIT" in reason_upper
        or "USER_RATE_LIMIT" in reason_upper
    ):
        error_type = APIErrorType.RATE_LIMIT
        transient = True
    elif "DAILY_QUOTA" in reason_upper or "QUOTA_EXCEEDED" in reason_upper:
        error_type = APIErrorType.DAILY_QUOTA
        transient = False
    elif grpc_status == "RESOURCE_EXHAUSTED" or type_name == "RESOURCEEXHAUSTED":
        error_type = APIErrorType.QUOTA_UNKNOWN
        transient = None
    elif http_status in {500, 502, 503, 504} or grpc_status in {"UNAVAILABLE", "INTERNAL", "ABORTED"}:
        error_type = APIErrorType.SERVICE_UNAVAILABLE
        transient = True
    elif http_status == 400 or grpc_status == "INVALID_ARGUMENT":
        error_type = APIErrorType.INVALID_REQUEST
        transient = False
    elif http_status == 401 or grpc_status == "UNAUTHENTICATED":
        error_type = APIErrorType.AUTHENTICATION
        transient = False
    elif http_status == 403:
        error_type = APIErrorType.UNKNOWN
        transient = None
    elif grpc_status in {"PERMISSION_DENIED", "UNAUTHENTICATED"}:
        error_type = APIErrorType.PERMISSION_DENIED
        transient = False
    elif grpc_status == "DEADLINE_EXCEEDED":
        error_type = APIErrorType.TIMEOUT
        transient = True
    elif isinstance(exc, GoogleAPIError):
        error_type = APIErrorType.UNKNOWN
        transient = None
    else:
        error_type = APIErrorType.UNKNOWN
        transient = None

    return APIErrorInfo(
        error_type=error_type,
        transport=transport,
        http_status=http_status,
        grpc_status=grpc_status,
        reason=reason,
        detail_types=detail_types,
        retry_after_seconds=retry_after,
        retry_after_source=retry_source,
        transient=transient,
    )
