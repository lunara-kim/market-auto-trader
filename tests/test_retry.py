"""
에러 재시도 유틸리티 (retry.py) 테스트

동기/비동기 재시도, exponential backoff, jitter,
non_retryable, on_retry 콜백, retry_call 등을 검증합니다.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from src.utils.retry import (
    RetryExhaustedError,
    _calculate_delay,
    async_retry,
    retry,
    retry_call,
)


# ────────────────── _calculate_delay ──────────────────


class TestCalculateDelay:
    """backoff 지연 시간 계산 테스트"""

    def test_exponential_growth(self) -> None:
        """지수적으로 증가하는지 확인 (jitter 없이)"""
        d0 = _calculate_delay(0, base_delay=1.0, max_delay=60.0, jitter=False)
        d1 = _calculate_delay(1, base_delay=1.0, max_delay=60.0, jitter=False)
        d2 = _calculate_delay(2, base_delay=1.0, max_delay=60.0, jitter=False)

        assert d0 == 1.0
        assert d1 == 2.0
        assert d2 == 4.0

    def test_max_delay_cap(self) -> None:
        """max_delay를 넘지 않는지 확인"""
        d = _calculate_delay(10, base_delay=1.0, max_delay=5.0, jitter=False)
        assert d == 5.0

    def test_jitter_within_range(self) -> None:
        """jitter가 [0, delay] 범위 내인지 확인"""
        results = [
            _calculate_delay(2, base_delay=1.0, max_delay=60.0, jitter=True)
            for _ in range(100)
        ]
        assert all(0 <= r <= 4.0 for r in results)
        # jitter로 인해 모든 값이 같지 않아야 함
        assert len(set(results)) > 1

    def test_zero_base_delay(self) -> None:
        """base_delay=0이면 항상 0"""
        d = _calculate_delay(5, base_delay=0.0, max_delay=60.0, jitter=False)
        assert d == 0.0


# ────────────────── @retry (동기) ──────────────────


class TestSyncRetry:
    """동기 retry 데코레이터 테스트"""

    def test_success_no_retry(self) -> None:
        """성공 시 재시도 없이 바로 반환"""
        call_count = 0

        @retry(max_retries=3, base_delay=0.01, retryable=(ValueError,))
        def succeed() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeed()
        assert result == "ok"
        assert call_count == 1

    def test_retry_then_success(self) -> None:
        """첫 시도 실패 → 재시도 시 성공"""
        call_count = 0

        @retry(max_retries=3, base_delay=0.01, retryable=(ValueError,))
        def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("일시 오류")
            return "ok"

        result = fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    def test_retry_exhausted(self) -> None:
        """모든 재시도 소진 시 RetryExhaustedError"""
        @retry(max_retries=2, base_delay=0.01, retryable=(ValueError,))
        def always_fail() -> None:
            raise ValueError("항상 실패")

        with pytest.raises(RetryExhaustedError) as exc_info:
            always_fail()

        assert exc_info.value.attempts == 3  # 초기 1회 + 재시도 2회
        assert isinstance(exc_info.value.last_exception, ValueError)

    def test_non_retryable_raises_immediately(self) -> None:
        """non_retryable 예외는 즉시 전파"""
        call_count = 0

        @retry(
            max_retries=3,
            base_delay=0.01,
            retryable=(Exception,),
            non_retryable=(TypeError,),
        )
        def raise_type_error() -> None:
            nonlocal call_count
            call_count += 1
            raise TypeError("즉시 전파")

        with pytest.raises(TypeError):
            raise_type_error()

        assert call_count == 1  # 재시도 없이 즉시 종료

    def test_unmatched_exception_propagates(self) -> None:
        """retryable에 포함되지 않은 예외는 즉시 전파"""
        call_count = 0

        @retry(max_retries=3, base_delay=0.01, retryable=(ValueError,))
        def raise_runtime() -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("다른 예외")

        with pytest.raises(RuntimeError):
            raise_runtime()

        assert call_count == 1

    def test_on_retry_callback(self) -> None:
        """재시도 시 on_retry 콜백 호출 확인"""
        callback = MagicMock()
        call_count = 0

        @retry(
            max_retries=2,
            base_delay=0.01,
            retryable=(ValueError,),
            on_retry=callback,
        )
        def fail_twice() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("실패")
            return "ok"

        result = fail_twice()
        assert result == "ok"
        assert callback.call_count == 2

        # 콜백 인자 확인: (attempt_number, exception, delay)
        first_call_args = callback.call_args_list[0][0]
        assert first_call_args[0] == 1  # attempt
        assert isinstance(first_call_args[1], ValueError)
        assert isinstance(first_call_args[2], float)

    def test_max_retries_zero_no_retry(self) -> None:
        """max_retries=0이면 재시도 없이 바로 실패"""
        @retry(max_retries=0, base_delay=0.01, retryable=(ValueError,))
        def fail_once() -> None:
            raise ValueError("한 번 실패")

        with pytest.raises(RetryExhaustedError) as exc_info:
            fail_once()
        assert exc_info.value.attempts == 1

    def test_delay_actually_waits(self) -> None:
        """실제로 대기하는지 확인 (최소한의 시간 검증)"""
        call_count = 0

        @retry(max_retries=1, base_delay=0.05, jitter=False, retryable=(ValueError,))
        def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first fail")
            return "ok"

        start = time.monotonic()
        result = fail_then_succeed()
        elapsed = time.monotonic() - start

        assert result == "ok"
        assert elapsed >= 0.04  # 약간의 여유를 두고 검증

    def test_preserves_return_value(self) -> None:
        """다양한 반환 타입이 보존되는지 확인"""
        @retry(max_retries=1, base_delay=0.01, retryable=(ValueError,))
        def return_dict() -> dict:
            return {"key": "value", "list": [1, 2, 3]}

        result = return_dict()
        assert result == {"key": "value", "list": [1, 2, 3]}

    def test_preserves_function_metadata(self) -> None:
        """functools.wraps로 원본 함수 메타데이터 보존"""
        @retry(max_retries=1, base_delay=0.01, retryable=(ValueError,))
        def my_function() -> None:
            """함수 docstring"""

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "함수 docstring"


# ────────────────── @async_retry ──────────────────


class TestAsyncRetry:
    """비동기 async_retry 데코레이터 테스트"""

    @pytest.mark.asyncio
    async def test_async_success(self) -> None:
        """비동기 성공 시 바로 반환"""
        @async_retry(max_retries=3, base_delay=0.01, retryable=(ValueError,))
        async def succeed() -> str:
            return "async ok"

        result = await succeed()
        assert result == "async ok"

    @pytest.mark.asyncio
    async def test_async_retry_then_success(self) -> None:
        """비동기 재시도 후 성공"""
        call_count = 0

        @async_retry(max_retries=3, base_delay=0.01, retryable=(ValueError,))
        async def fail_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("일시 오류")
            return "ok"

        result = await fail_then_succeed()
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_async_retry_exhausted(self) -> None:
        """비동기 모든 재시도 소진"""
        @async_retry(max_retries=2, base_delay=0.01, retryable=(ValueError,))
        async def always_fail() -> None:
            raise ValueError("항상 실패")

        with pytest.raises(RetryExhaustedError) as exc_info:
            await always_fail()

        assert exc_info.value.attempts == 3

    @pytest.mark.asyncio
    async def test_async_non_retryable(self) -> None:
        """비동기 non_retryable 예외 즉시 전파"""
        call_count = 0

        @async_retry(
            max_retries=3,
            base_delay=0.01,
            retryable=(Exception,),
            non_retryable=(TypeError,),
        )
        async def raise_type_error() -> None:
            nonlocal call_count
            call_count += 1
            raise TypeError("즉시 전파")

        with pytest.raises(TypeError):
            await raise_type_error()

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_async_on_retry_callback(self) -> None:
        """비동기 on_retry 콜백 호출"""
        callback = MagicMock()
        call_count = 0

        @async_retry(
            max_retries=2,
            base_delay=0.01,
            retryable=(ValueError,),
            on_retry=callback,
        )
        async def fail_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("실패")
            return "ok"

        result = await fail_once()
        assert result == "ok"
        assert callback.call_count == 1

    @pytest.mark.asyncio
    async def test_async_preserves_metadata(self) -> None:
        """비동기 함수 메타데이터 보존"""
        @async_retry(max_retries=1, base_delay=0.01, retryable=(ValueError,))
        async def my_async_func() -> None:
            """비동기 docstring"""

        assert my_async_func.__name__ == "my_async_func"
        assert my_async_func.__doc__ == "비동기 docstring"


# ────────────────── retry_call ──────────────────


class TestRetryCall:
    """명시적 retry_call 테스트"""

    def test_retry_call_success(self) -> None:
        """retry_call 성공"""
        result = retry_call(
            lambda: 42,
            max_retries=3,
            base_delay=0.01,
        )
        assert result == 42

    def test_retry_call_with_retries(self) -> None:
        """retry_call 재시도 후 성공"""
        counter = {"n": 0}

        def flaky() -> str:
            counter["n"] += 1
            if counter["n"] < 3:
                raise ConnectionError("임시 오류")
            return "recovered"

        result = retry_call(
            flaky,
            max_retries=3,
            base_delay=0.01,
            retryable=(ConnectionError,),
        )
        assert result == "recovered"
        assert counter["n"] == 3

    def test_retry_call_exhausted(self) -> None:
        """retry_call 재시도 소진"""
        def always_fail() -> None:
            raise IOError("항상 실패")

        with pytest.raises(RetryExhaustedError):
            retry_call(
                always_fail,
                max_retries=1,
                base_delay=0.01,
                retryable=(IOError,),
            )

    def test_retry_call_with_args(self) -> None:
        """retry_call에 인자 전달"""
        def add(a: int, b: int) -> int:
            return a + b

        result = retry_call(add, 3, 7, max_retries=1, base_delay=0.01)
        assert result == 10


# ────────────────── RetryExhaustedError ──────────────────


class TestRetryExhaustedError:
    """RetryExhaustedError 예외 속성 테스트"""

    def test_attributes(self) -> None:
        """예외 속성 접근"""
        original = ValueError("원본 에러")
        err = RetryExhaustedError(
            "재시도 소진",
            attempts=4,
            last_exception=original,
        )
        assert err.attempts == 4
        assert err.last_exception is original
        assert "재시도 소진" in str(err)

    def test_none_last_exception(self) -> None:
        """last_exception이 None일 수 있음"""
        err = RetryExhaustedError("test", attempts=1, last_exception=None)
        assert err.last_exception is None


# ────────────────── 실전 시나리오 ──────────────────


class TestRealWorldScenarios:
    """실전 사용 시나리오 테스트"""

    def test_network_timeout_retry(self) -> None:
        """네트워크 타임아웃 → 재시도 → 성공 시나리오"""
        attempts = {"count": 0}

        @retry(
            max_retries=3,
            base_delay=0.01,
            retryable=(ConnectionError, TimeoutError),
            non_retryable=(ValueError,),
        )
        def api_call() -> dict:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise TimeoutError("timeout")
            if attempts["count"] == 2:
                raise ConnectionError("connection reset")
            return {"data": "success"}

        result = api_call()
        assert result == {"data": "success"}
        assert attempts["count"] == 3

    def test_auth_error_no_retry(self) -> None:
        """인증 에러는 재시도하지 않음"""
        @retry(
            max_retries=3,
            base_delay=0.01,
            retryable=(ConnectionError, TimeoutError),
            non_retryable=(PermissionError,),
        )
        def protected_call() -> None:
            raise PermissionError("인증 실패")

        with pytest.raises(PermissionError):
            protected_call()

    def test_multiple_decorators(self) -> None:
        """여러 함수에 각각 다른 설정으로 데코레이터 적용"""
        fast_count = 0
        slow_count = 0

        @retry(max_retries=1, base_delay=0.01, retryable=(ValueError,))
        def fast_retry() -> str:
            nonlocal fast_count
            fast_count += 1
            if fast_count == 1:
                raise ValueError("빠른 실패")
            return "fast"

        @retry(max_retries=2, base_delay=0.01, retryable=(ValueError,))
        def slow_retry() -> str:
            nonlocal slow_count
            slow_count += 1
            if slow_count <= 2:
                raise ValueError("느린 실패")
            return "slow"

        assert fast_retry() == "fast"
        assert slow_retry() == "slow"
        assert fast_count == 2
        assert slow_count == 3
