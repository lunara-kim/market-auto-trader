"""
에러 재시도 유틸리티 — Exponential Backoff + Jitter

외부 API 호출 (한투 OpenAPI, DB 연결 등) 시 일시적 오류에 대해
자동으로 재시도하는 데코레이터와 컨텍스트 매니저를 제공합니다.

Usage::

    # 데코레이터 방식
    @retry(max_retries=3, base_delay=0.5, retryable=(BrokerError, ConnectionError))
    def call_api():
        ...

    # 비동기 데코레이터
    @async_retry(max_retries=3, base_delay=0.5, retryable=(BrokerError,))
    async def call_api_async():
        ...

    # 명시적 호출
    result = retry_call(call_api, max_retries=3, base_delay=0.5)
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

from src.utils.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class RetryExhaustedError(Exception):
    """모든 재시도가 소진된 경우 발생하는 예외

    Attributes:
        attempts: 총 시도 횟수
        last_exception: 마지막으로 발생한 예외
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: int,
        last_exception: Exception | None = None,
    ) -> None:
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(message)


def _calculate_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    jitter: bool,
) -> float:
    """Exponential backoff + optional jitter 지연 시간 계산

    Args:
        attempt: 현재 시도 횟수 (0-indexed)
        base_delay: 기본 지연 시간 (초)
        max_delay: 최대 지연 시간 (초)
        jitter: True이면 랜덤 jitter 추가

    Returns:
        실제 대기할 시간 (초)
    """
    # Exponential: base_delay * 2^attempt
    delay = base_delay * (2 ** attempt)
    delay = min(delay, max_delay)

    if jitter:
        # Full jitter: [0, delay] 범위에서 랜덤 선택
        delay = random.uniform(0, delay)  # noqa: S311

    return delay


def retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    jitter: bool = True,
    retryable: tuple[type[Exception], ...] = (Exception,),
    non_retryable: tuple[type[Exception], ...] = (),
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> Callable[[F], F]:
    """동기 함수용 재시도 데코레이터

    Args:
        max_retries: 최대 재시도 횟수 (0이면 재시도 안 함)
        base_delay: 기본 지연 시간 (초)
        max_delay: 최대 지연 시간 (초)
        jitter: True이면 랜덤 jitter 추가 (thundering herd 방지)
        retryable: 재시도할 예외 타입 튜플
        non_retryable: 재시도하지 않을 예외 타입 (retryable보다 우선)
        on_retry: 재시도 시 호출할 콜백 (attempt, exception, delay)

    Returns:
        데코레이터 함수
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except non_retryable:
                    raise
                except retryable as e:
                    last_exc = e

                    if attempt >= max_retries:
                        logger.warning(
                            "재시도 소진: %s (총 %d회 시도, 마지막 에러: %s)",
                            func.__name__,
                            attempt + 1,
                            e,
                        )
                        raise RetryExhaustedError(
                            f"{func.__name__}: {max_retries}회 재시도 후에도 실패",
                            attempts=attempt + 1,
                            last_exception=e,
                        ) from e

                    delay = _calculate_delay(attempt, base_delay, max_delay, jitter)
                    logger.info(
                        "재시도 %d/%d: %s (에러: %s, %.2f초 후 재시도)",
                        attempt + 1,
                        max_retries,
                        func.__name__,
                        e,
                        delay,
                    )

                    if on_retry is not None:
                        on_retry(attempt + 1, e, delay)

                    time.sleep(delay)

            # 이론상 도달 불가능하지만 방어적 코드
            raise RetryExhaustedError(  # pragma: no cover
                f"{func.__name__}: 재시도 소진",
                attempts=max_retries + 1,
                last_exception=last_exc,
            )

        return wrapper  # type: ignore[return-value]

    return decorator


def async_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    jitter: bool = True,
    retryable: tuple[type[Exception], ...] = (Exception,),
    non_retryable: tuple[type[Exception], ...] = (),
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> Callable[[F], F]:
    """비동기 함수용 재시도 데코레이터

    Args:
        max_retries: 최대 재시도 횟수
        base_delay: 기본 지연 시간 (초)
        max_delay: 최대 지연 시간 (초)
        jitter: True이면 랜덤 jitter 추가
        retryable: 재시도할 예외 타입 튜플
        non_retryable: 재시도하지 않을 예외 타입 (retryable보다 우선)
        on_retry: 재시도 시 호출할 콜백 (attempt, exception, delay)

    Returns:
        데코레이터 함수
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except non_retryable:
                    raise
                except retryable as e:
                    last_exc = e

                    if attempt >= max_retries:
                        logger.warning(
                            "재시도 소진: %s (총 %d회 시도, 마지막 에러: %s)",
                            func.__name__,
                            attempt + 1,
                            e,
                        )
                        raise RetryExhaustedError(
                            f"{func.__name__}: {max_retries}회 재시도 후에도 실패",
                            attempts=attempt + 1,
                            last_exception=e,
                        ) from e

                    delay = _calculate_delay(attempt, base_delay, max_delay, jitter)
                    logger.info(
                        "재시도 %d/%d: %s (에러: %s, %.2f초 후 재시도)",
                        attempt + 1,
                        max_retries,
                        func.__name__,
                        e,
                        delay,
                    )

                    if on_retry is not None:
                        on_retry(attempt + 1, e, delay)

                    await asyncio.sleep(delay)

            raise RetryExhaustedError(  # pragma: no cover
                f"{func.__name__}: 재시도 소진",
                attempts=max_retries + 1,
                last_exception=last_exc,
            )

        return wrapper  # type: ignore[return-value]

    return decorator


def retry_call(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    jitter: bool = True,
    retryable: tuple[type[Exception], ...] = (Exception,),
    non_retryable: tuple[type[Exception], ...] = (),
    **kwargs: Any,
) -> Any:
    """함수를 재시도 로직과 함께 명시적으로 호출

    데코레이터를 붙일 수 없는 외부 함수나 람다에 유용합니다.

    Args:
        func: 실행할 함수
        *args: 함수에 전달할 위치 인자
        max_retries: 최대 재시도 횟수
        base_delay: 기본 지연 시간 (초)
        max_delay: 최대 지연 시간 (초)
        jitter: True이면 랜덤 jitter 추가
        retryable: 재시도할 예외 타입 튜플
        non_retryable: 재시도하지 않을 예외 타입
        **kwargs: 함수에 전달할 키워드 인자

    Returns:
        함수의 반환값

    Raises:
        RetryExhaustedError: 모든 재시도가 소진된 경우
    """

    @retry(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        jitter=jitter,
        retryable=retryable,
        non_retryable=non_retryable,
    )
    def _wrapped() -> Any:
        return func(*args, **kwargs)

    return _wrapped()
