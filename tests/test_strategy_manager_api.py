"""
복합 전략 매니저 API 엔드포인트 테스트

/api/v1/strategies/* 엔드포인트의 요청/응답을 검증합니다.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# 테스트용 가격 데이터 (50일치, 오래된 순)
PRICES_UP = [
    50000 + i * 100 for i in range(50)
]  # 꾸준히 상승

PRICES_DOWN = [
    55000 - i * 100 for i in range(50)
]  # 꾸준히 하락

DATES = [f"2025-01-{i+1:02d}" for i in range(50)]

# RSI 과매도 탈출 패턴 (급락 후 반등)
PRICES_RSI_OVERSOLD = (
    [50000 - i * 500 for i in range(20)]  # 급락
    + [40000 + i * 300 for i in range(30)]  # 반등
)

HISTORICAL_DATA = [
    {"date": f"2025-01-{i+1:02d}", "close": 50000 + i * 100}
    for i in range(50)
]


# ─────────────────────────────────────────────
# GET /api/v1/strategies/available
# ─────────────────────────────────────────────

class TestAvailableStrategies:
    """사용 가능한 전략 목록 조회"""

    @pytest.mark.anyio
    async def test_list_strategies(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/strategies/available")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 3
        names = {s["name"] for s in data}
        assert names == {"ma", "rsi", "bollinger"}

    @pytest.mark.anyio
    async def test_strategy_has_params(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/strategies/available")
        data = resp.json()

        ma = next(s for s in data if s["name"] == "ma")
        assert "short_window" in ma["params"]
        assert "long_window" in ma["params"]

        rsi = next(s for s in data if s["name"] == "rsi")
        assert "period" in rsi["params"]
        assert "overbought" in rsi["params"]


# ─────────────────────────────────────────────
# POST /api/v1/strategies/signal
# ─────────────────────────────────────────────

class TestCombinedSignal:
    """복합 신호 생성 엔드포인트"""

    @pytest.mark.anyio
    async def test_single_ma_strategy(self, client: AsyncClient) -> None:
        """MA 전략 1개로 신호 생성"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "dates": DATES,
                "stock_code": "005930",
                "strategies": [
                    {"name": "ma", "weight": 1.0, "params": {"short_window": 5, "long_window": 20}},
                ],
                "voting_method": "majority",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["signal"] in ("buy", "sell", "hold")
        assert "confidence" in data
        assert data["voting_method"] == "majority"
        assert len(data["individual_signals"]) == 1

    @pytest.mark.anyio
    async def test_multi_strategy_majority(self, client: AsyncClient) -> None:
        """여러 전략으로 다수결 투표"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "dates": DATES,
                "strategies": [
                    {"name": "ma", "weight": 1.0, "params": {"short_window": 5, "long_window": 20}},
                    {"name": "rsi", "weight": 1.0, "params": {"period": 14}},
                    {"name": "bollinger", "weight": 1.0, "params": {"period": 20}},
                ],
                "voting_method": "majority",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["signal"] in ("buy", "sell", "hold")
        assert len(data["individual_signals"]) == 3

    @pytest.mark.anyio
    async def test_weighted_voting(self, client: AsyncClient) -> None:
        """가중 투표 방식"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "strategies": [
                    {"name": "ma", "weight": 3.0, "params": {}},
                    {"name": "rsi", "weight": 1.0, "params": {}},
                ],
                "voting_method": "weighted",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["voting_method"] == "weighted"

    @pytest.mark.anyio
    async def test_unanimous_voting(self, client: AsyncClient) -> None:
        """만장일치 투표 방식"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "strategies": [
                    {"name": "ma", "weight": 1.0, "params": {}},
                    {"name": "rsi", "weight": 1.0, "params": {}},
                ],
                "voting_method": "unanimous",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["voting_method"] == "unanimous"

    @pytest.mark.anyio
    async def test_min_confidence(self, client: AsyncClient) -> None:
        """최소 확신도 설정"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "strategies": [
                    {"name": "ma", "weight": 1.0, "params": {}},
                ],
                "voting_method": "majority",
                "min_confidence": 0.99,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # 확신도 0.99 이상이 아니면 hold
        assert data["signal"] in ("buy", "sell", "hold")

    @pytest.mark.anyio
    async def test_invalid_strategy_name(self, client: AsyncClient) -> None:
        """잘못된 전략 이름"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "strategies": [
                    {"name": "nonexistent", "weight": 1.0, "params": {}},
                ],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_empty_prices_rejected(self, client: AsyncClient) -> None:
        """빈 가격 리스트 → 422"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": [],
                "strategies": [
                    {"name": "ma", "weight": 1.0, "params": {}},
                ],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_empty_strategies_rejected(self, client: AsyncClient) -> None:
        """빈 전략 리스트 → 422"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "strategies": [],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_response_has_timestamp(self, client: AsyncClient) -> None:
        """응답에 timestamp 포함"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "strategies": [
                    {"name": "ma", "weight": 1.0, "params": {}},
                ],
            },
        )
        data = resp.json()
        assert "timestamp" in data
        assert len(data["timestamp"]) > 0

    @pytest.mark.anyio
    async def test_individual_signals_have_weight(self, client: AsyncClient) -> None:
        """개별 신호에 weight 필드 포함"""
        resp = await client.post(
            "/api/v1/strategies/signal",
            json={
                "prices": PRICES_UP,
                "strategies": [
                    {"name": "ma", "weight": 2.5, "params": {}},
                    {"name": "rsi", "weight": 1.5, "params": {}},
                ],
            },
        )
        data = resp.json()
        weights = [s["weight"] for s in data["individual_signals"]]
        assert 2.5 in weights
        assert 1.5 in weights


# ─────────────────────────────────────────────
# POST /api/v1/strategies/compare
# ─────────────────────────────────────────────

class TestBacktestCompare:
    """전략 성과 비교 엔드포인트"""

    @pytest.mark.anyio
    async def test_compare_two_strategies(self, client: AsyncClient) -> None:
        """두 전략 비교"""
        resp = await client.post(
            "/api/v1/strategies/compare",
            json={
                "historical_data": HISTORICAL_DATA,
                "initial_capital": 10_000_000,
                "strategies": [
                    {"name": "ma", "weight": 1.0, "params": {"short_window": 5, "long_window": 20}},
                    {"name": "rsi", "weight": 1.0, "params": {"period": 14}},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["ranking"]) == 2
        assert data["ranking"][0]["rank"] == 1
        assert data["ranking"][1]["rank"] == 2
        assert data["best_strategy"] is not None

    @pytest.mark.anyio
    async def test_compare_three_strategies(self, client: AsyncClient) -> None:
        """세 전략 비교"""
        resp = await client.post(
            "/api/v1/strategies/compare",
            json={
                "historical_data": HISTORICAL_DATA,
                "initial_capital": 10_000_000,
                "strategies": [
                    {"name": "ma", "params": {"short_window": 5, "long_window": 20}},
                    {"name": "rsi", "params": {"period": 14}},
                    {"name": "bollinger", "params": {"period": 20}},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["ranking"]) == 3

    @pytest.mark.anyio
    async def test_compare_summary(self, client: AsyncClient) -> None:
        """요약 필드 확인"""
        resp = await client.post(
            "/api/v1/strategies/compare",
            json={
                "historical_data": HISTORICAL_DATA,
                "initial_capital": 5_000_000,
                "strategies": [
                    {"name": "ma", "params": {}},
                    {"name": "rsi", "params": {}},
                ],
            },
        )
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["total_strategies"] == 2
        assert summary["initial_capital"] == 5_000_000
        assert "best_return" in summary
        assert "worst_return" in summary
        assert "average_return" in summary

    @pytest.mark.anyio
    async def test_compare_ranking_sorted(self, client: AsyncClient) -> None:
        """랭킹이 수익률 내림차순인지 확인"""
        resp = await client.post(
            "/api/v1/strategies/compare",
            json={
                "historical_data": HISTORICAL_DATA,
                "initial_capital": 10_000_000,
                "strategies": [
                    {"name": "ma", "params": {"short_window": 3, "long_window": 10}},
                    {"name": "ma", "params": {"short_window": 5, "long_window": 20}},
                    {"name": "rsi", "params": {}},
                ],
            },
        )
        assert resp.status_code == 200
        ranking = resp.json()["ranking"]
        returns = [r["total_return"] for r in ranking]
        assert returns == sorted(returns, reverse=True)

    @pytest.mark.anyio
    async def test_compare_insufficient_data(self, client: AsyncClient) -> None:
        """데이터 부족 (10개 미만) → 422"""
        resp = await client.post(
            "/api/v1/strategies/compare",
            json={
                "historical_data": [
                    {"date": "2025-01-01", "close": 50000},
                ],
                "initial_capital": 10_000_000,
                "strategies": [{"name": "ma", "params": {}}],
            },
        )
        assert resp.status_code == 422

    @pytest.mark.anyio
    async def test_compare_ranking_has_all_fields(self, client: AsyncClient) -> None:
        """랭킹 항목에 필수 필드 존재"""
        resp = await client.post(
            "/api/v1/strategies/compare",
            json={
                "historical_data": HISTORICAL_DATA,
                "initial_capital": 10_000_000,
                "strategies": [{"name": "ma", "params": {}}],
            },
        )
        assert resp.status_code == 200
        item = resp.json()["ranking"][0]
        required_fields = [
            "rank", "strategy_name", "total_return", "win_rate",
            "max_drawdown", "sharpe_ratio", "total_trades",
        ]
        for field in required_fields:
            assert field in item, f"Missing field: {field}"
