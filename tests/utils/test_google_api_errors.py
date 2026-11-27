from datetime import UTC, datetime, tzinfo
from types import SimpleNamespace
from typing import NoReturn

import pytest
from google.api_core.exceptions import GoogleAPIError, ResourceExhausted, ServiceUnavailable, TooManyRequests
from grpc import StatusCode

from utils import google_api_errors
from utils.google_api_errors import APIErrorType, APITransport, classify_google_api_error


def _http_response(status_code: int, retry_after: str | None = None) -> SimpleNamespace:
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    return SimpleNamespace(status_code=status_code, headers=headers)


def test_classify_http_rate_limit_keeps_http_transport() -> None:
    info = classify_google_api_error(TooManyRequests("limited"))

    assert info.error_type == APIErrorType.RATE_LIMIT
    assert info.transport == APITransport.HTTP
    assert info.http_status == 429
    assert info.grpc_status is None


def test_classify_http_resource_exhausted_429_as_rate_limit() -> None:
    error = ResourceExhausted("limited", response=_http_response(429))

    info = classify_google_api_error(error)

    assert info.error_type == APIErrorType.RATE_LIMIT
    assert info.transport == APITransport.HTTP


def test_classify_resource_exhausted_without_reason_as_unknown_quota() -> None:
    info = classify_google_api_error(ResourceExhausted("resource exhausted"))

    assert info.error_type == APIErrorType.QUOTA_UNKNOWN
    assert info.transient is None


def test_classify_http_service_unavailable_keeps_http_transport() -> None:
    error = ServiceUnavailable("unavailable", response=_http_response(503))

    info = classify_google_api_error(error)

    assert info.error_type == APIErrorType.SERVICE_UNAVAILABLE
    assert info.transport == APITransport.HTTP
    assert info.http_status == 503


def test_classify_grpc_deadline_exceeded() -> None:
    error = GoogleAPIError("deadline exceeded")
    error.grpc_status_code = StatusCode.DEADLINE_EXCEEDED

    info = classify_google_api_error(error)

    assert info.error_type == APIErrorType.TIMEOUT
    assert info.transport == APITransport.GRPC
    assert info.grpc_status == "DEADLINE_EXCEEDED"


def test_classify_uses_status_when_structured_details_raise() -> None:
    class BrokenDetailsError(Exception):
        code = 429

        def details(self) -> NoReturn:
            raise RuntimeError

    info = classify_google_api_error(BrokenDetailsError("limited"))

    assert info.error_type == APIErrorType.RATE_LIMIT
    assert info.http_status == 429


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [
        pytest.param("12.5", 12.5, id="numeric"),
        pytest.param("NaN", None, id="nan"),
        pytest.param("inf", None, id="infinite"),
        pytest.param("-1", None, id="negative"),
        pytest.param("not a date", None, id="invalid"),
    ],
)
def test_retry_after_accepts_only_finite_nonnegative_seconds(retry_after: str, expected: float | None) -> None:
    error = TooManyRequests("limited", response=_http_response(429, retry_after))

    info = classify_google_api_error(error)

    assert info.retry_after_seconds == expected


def test_retry_after_parses_http_date(monkeypatch: pytest.MonkeyPatch) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, _tz: tzinfo | None = None) -> datetime:
            return cls(2030, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(google_api_errors, "datetime", FrozenDateTime)
    error = TooManyRequests(
        "limited",
        response=_http_response(429, "Tue, 01 Jan 2030 00:01:00 GMT"),
    )

    info = classify_google_api_error(error)

    assert info.retry_after_seconds == 60.0
    assert info.retry_after_source == "HTTP Retry-After"


def test_retry_after_http_date_in_the_past_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, _tz: tzinfo | None = None) -> datetime:
            return cls(2030, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(google_api_errors, "datetime", FrozenDateTime)
    error = TooManyRequests(
        "limited",
        response=_http_response(429, "Mon, 31 Dec 2029 23:59:00 GMT"),
    )

    info = classify_google_api_error(error)

    assert info.retry_after_seconds == 0.0
