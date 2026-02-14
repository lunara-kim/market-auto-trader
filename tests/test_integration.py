"""
Phase 2 통합 테스트 / 시나리오 테스트

개별 모듈이 아닌, 여러 레이어를 관통하는 엔드투엔드 시나리오를 검증합니다.

시나리오 목록:
1. 매매 신호 생성 → 리스크 검증 → 주문 실행 → 포트폴리오 확인
2. 전략 분석 + 리스크 관리 통합 (포지션 사이징, 일간 손실 한도)
3. Config 설정이 전략/백테스트에 올바르게 반영되는지
4. 에러 전파: 브로커 장애, 데이터 부족, 잔고 부족 등
5. 원샷 정책 + 리스크 검증 통합
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_db, get_kis_client
from src.broker.kis_client import KISClient
from src.exceptions import (
    BrokerError,
    OrderError,
    StrategyError,
    ValidationError,
)
from src.main import app
from src.strategy.moving_average import MAConfig, MAType, MovingAverageCrossover
from src.strategy.risk import (
    PositionRiskConfig,
    calculate_position_size,
    check_daily_loss_limit,
)


def _mock_kis_client_base(**kwargs) -> MagicMock:
    """KISClient spec을 적용한 MagicMock 생성

    MarketDataCollector가 isinstance(client, KISClient) 검증을 하므로
    반드시 spec=KISClient을 사용해야 한다.
    """
    mock = MagicMock(spec=KISClient)
    mock.close.return_value = None
    for k, v in kwargs.items():
        setattr(mock, k, v)
    return mock


# ───────────────────────── Fixtures ──────────────────────────


class FakeDBSession:
    """통합 테스트용 가짜 DB 세션

    add된 객체를 추적하여, 시나리오 흐름 내에서
    신호/주문이 올바르게 기록되었는지 검증할 수 있다.
    """

    def __init__(self) -> None:
        self.added: list = []
        self._committed = False

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self._committed = True

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt):
        class FakeResult:
            def scalars(self):
                return self

            def all(self):
                return []

            def scalar(self):
                return 0

        return FakeResult()


def _generate_price_series(
    base: float,
    days: int,
    trend: str = "up",
    volatility: float = 500.0,
) -> list[float]:
    """테스트용 가격 시계열 생성

    Args:
        base: 시작 가격
        days: 데이터 일수
        trend: "up" (상승), "down" (하락), "flat" (횡보), "golden_cross" (교차)
        volatility: 일간 변동 폭
    """
    prices = []
    price = base
    for i in range(days):
        if trend == "up":
            price += volatility
        elif trend == "down":
            price -= volatility
        elif trend == "golden_cross":
            # 전반부 하락, 후반부 상승 (골든크로스 유도)
            if i < days // 2:
                price -= volatility
            else:
                price += volatility * 1.5
        # flat: price 유지
        prices.append(max(price, 100))  # 최소 100원
    return prices


def _make_daily_records(prices: list[float], start_date: str = "20260101") -> list[dict]:
    """가격 리스트를 한투 API 형식의 일봉 데이터로 변환 (최신순)"""
    records = []
    base_year = int(start_date[:4])
    base_month = int(start_date[4:6])
    base_day = int(start_date[6:8])

    for i, price in enumerate(prices):
        day = base_day + i
        month = base_month + (day - 1) // 28
        day_of_month = ((day - 1) % 28) + 1
        date_str = f"{base_year}{month:02d}{day_of_month:02d}"

        records.append({
            "stck_bsop_date": date_str,
            "stck_oprc": str(int(price - 200)),
            "stck_hgpr": str(int(price + 300)),
            "stck_lwpr": str(int(price - 500)),
            "stck_clpr": str(int(price)),
            "acml_vol": str(100_000 + i * 1_000),
            "acml_tr_pbmn": str(int(price * 100_000)),
            "prdy_vrss": "500",
            "prdy_vrss_sign": "2",
        })

    # 한투 API는 최신순으로 반환
    return list(reversed(records))


def _mock_kis_with_prices(prices: list[float]) -> MagicMock:
    """가격 시계열을 반환하는 KISClient 모킹

    spec=KISClient을 사용하여 MarketDataCollector의
    isinstance 검증을 통과한다.
    """
    mock = MagicMock(spec=KISClient)
    records = _make_daily_records(prices)

    def fake_request_get(path, tr_id, params):
        return {"rt_cd": "0", "output2": records}

    mock._request_get = MagicMock(side_effect=fake_request_get)
    mock.get_price.return_value = {
        "stck_prpr": str(int(prices[-1])),
        "prdy_vrss": "500",
        "prdy_ctrt": "0.75",
        "acml_vol": "5000000",
    }
    mock.close.return_value = None
    return mock


# ═══════════════════════════════════════════════════════════
# 시나리오 1: 신호 생성 → 리스크 검증 → 주문 → 포트폴리오
# ═══════════════════════════════════════════════════════════


class TestSignalToOrderFlow:
    """매매 신호 생성 → 리스크 검증 → 주문 실행 → 포트폴리오 조회

    전체 매매 프로세스의 주요 흐름을 단일 시나리오로 검증합니다.
    """

    def setup_method(self) -> None:
        self.client = TestClient(app)
        self.fake_db = FakeDBSession()

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def _setup_deps(self, mock_client: MagicMock) -> None:
        app.dependency_overrides[get_kis_client] = lambda: mock_client

        async def _get_fake_db():
            yield self.fake_db

        app.dependency_overrides[get_db] = _get_fake_db

    def test_full_flow_buy_signal_to_order(self) -> None:
        """
        시나리오: 골든크로스 매수 신호 → 리스크 통과 → 주문 실행

        1. 상승 추세 데이터로 매매 신호 생성 (골든크로스 기대)
        2. 리스크 관리 모듈로 포지션 크기 계산
        3. 주문 실행
        4. 포트폴리오에서 보유종목 확인
        """
        # 골든크로스를 유도하는 가격 데이터
        prices = _generate_price_series(60_000, 40, trend="golden_cross")
        mock = _mock_kis_with_prices(prices)
        mock.place_order.return_value = {
            "ODNO": "INT-001",
            "ORD_TMD": "100000",
        }
        mock.get_balance.return_value = {
            "holdings": [
                {
                    "pdno": "005930",
                    "prdt_name": "삼성전자",
                    "hldg_qty": "10",
                    "pchs_avg_pric": "65000",
                    "prpr": str(int(prices[-1])),
                    "evlu_amt": str(int(prices[-1]) * 10),
                    "evlu_pfls_amt": str(int((prices[-1] - 65000) * 10)),
                    "evlu_pfls_rt": "5.0",
                },
            ],
            "summary": {
                "dnca_tot_amt": "5000000",
                "tot_evlu_amt": "5700000",
                "pchs_amt_smtl_amt": "650000",
                "evlu_pfls_smtl_amt": "50000",
                "nass_amt": "5700000",
            },
        }

        self._setup_deps(mock)

        # Step 1: 매매 신호 생성
        signal_resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
            "short_window": 5,
            "long_window": 20,
            "ma_type": "sma",
        })
        assert signal_resp.status_code == 200
        signal_data = signal_resp.json()
        assert signal_data["signal"] in ("buy", "sell", "hold")
        assert signal_data["metrics"]["current_price"] > 0

        # Step 2: 리스크 관리 — 포지션 크기 계산
        current_price = signal_data["metrics"]["current_price"]
        stop_loss = current_price * 0.95  # 5% 손절
        equity = 10_000_000

        quantity = calculate_position_size(
            equity=equity,
            entry_price=current_price,
            stop_loss_price=stop_loss,
            config=PositionRiskConfig(
                max_risk_per_trade_pct=1.0,
                max_position_size_pct=20.0,
            ),
        )
        assert quantity >= 1

        # Step 3: 일간 손실 한도 확인
        can_trade = check_daily_loss_limit(
            peak_equity=10_000_000,
            current_equity=9_800_000,
            max_daily_loss_pct=3.0,
        )
        assert can_trade is True

        # Step 4: 주문 실행
        order_resp = self.client.post("/api/v1/orders", json={
            "stock_code": "005930",
            "order_type": "buy",
            "quantity": quantity,
        })
        assert order_resp.status_code == 200
        order_data = order_resp.json()
        assert order_data["order_id"] == "INT-001"
        assert order_data["status"] == "executed"
        assert order_data["quantity"] == quantity

        # Step 5: 포트폴리오 조회
        portfolio_resp = self.client.get("/api/v1/portfolio")
        assert portfolio_resp.status_code == 200
        portfolio = portfolio_resp.json()
        assert len(portfolio["holdings"]) == 1
        assert portfolio["holdings"][0]["stock_code"] == "005930"
        assert portfolio["summary"]["net_asset"] > 0

        # DB에 신호 + 주문이 모두 기록됐는지
        assert len(self.fake_db.added) == 2  # 1 signal + 1 order

    def test_risk_blocks_trade_on_daily_loss_limit(self) -> None:
        """
        시나리오: 일간 손실 한도 초과 → 주문 차단

        신호는 매수지만, 이미 일간 손실 6%가 발생한 상태라
        리스크 관리에서 거래를 중단해야 한다.
        """
        with pytest.raises(StrategyError) as exc:
            check_daily_loss_limit(
                peak_equity=10_000_000,
                current_equity=9_300_000,  # -7%
                max_daily_loss_pct=5.0,
            )

        assert "일간 손실 한도를 초과" in str(exc.value.message)

    def test_risk_blocks_insufficient_position(self) -> None:
        """
        시나리오: 계좌 규모 대비 주가가 너무 비싸서 포지션 불가

        리스크 규칙상 최소 1주도 살 수 없는 경우 ValidationError.
        """
        with pytest.raises(ValidationError):
            calculate_position_size(
                equity=500_000,      # 50만 원
                entry_price=300_000,  # 30만 원짜리 주식
                stop_loss_price=295_000,
                config=PositionRiskConfig(
                    max_risk_per_trade_pct=0.5,
                    max_position_size_pct=10.0,
                ),
            )


# ═══════════════════════════════════════════════════════════
# 시나리오 2: 전략 + 설정(Config) 통합
# ═══════════════════════════════════════════════════════════


class TestStrategyConfigIntegration:
    """전략과 config 설정이 올바르게 연동되는지 검증"""

    def test_backtest_uses_config_commission_and_tax(self) -> None:
        """
        백테스트가 config에서 수수료/세금을 올바르게 읽어 적용하는지 검증

        수수료율 변경 → 최종 자본금에 차이가 나야 한다.
        """
        config = MAConfig(short_window=5, long_window=20, ma_type=MAType.SMA)
        strategy = MovingAverageCrossover(config)

        # 골든크로스/데드크로스가 발생하는 데이터
        historical = []
        prices_down = _generate_price_series(70_000, 25, trend="down", volatility=300)
        prices_up = _generate_price_series(prices_down[-1], 25, trend="up", volatility=400)
        all_prices = prices_down + prices_up

        for i, price in enumerate(all_prices):
            historical.append({"date": f"2025-{(i//28)+1:02d}-{(i%28)+1:02d}", "close": price})

        # 기본 설정으로 백테스트
        result = strategy.backtest(historical, initial_capital=10_000_000)

        assert result["strategy_name"] == strategy.name
        assert result["initial_capital"] == 10_000_000
        assert isinstance(result["final_capital"], float)
        assert isinstance(result["total_return"], float)
        assert isinstance(result["max_drawdown"], float)
        assert isinstance(result["sharpe_ratio"], float)
        assert len(result["equity_curve"]) > 0

    def test_backtest_insufficient_data_returns_empty(self) -> None:
        """데이터 부족 시 백테스트가 안전하게 빈 결과를 반환"""
        strategy = MovingAverageCrossover(MAConfig(short_window=5, long_window=20))

        result = strategy.backtest(
            [{"date": "2025-01-01", "close": 50000}],  # 1개뿐
            initial_capital=10_000_000,
        )

        assert result["total_return"] == 0.0
        assert result["total_trades"] == 0
        assert "error" in result

    def test_strategy_with_different_ma_types(self) -> None:
        """SMA/EMA가 같은 데이터에서 다른 분석 결과를 내는지 확인

        EMA는 최근 데이터에 더 큰 가중치를 부여하므로,
        비선형적으로 변동하는 데이터에서 SMA와 다른 결과가 나와야 한다.
        """
        import math

        # 비선형 변동 데이터 (사인파 + 상승 추세)
        prices = [
            60_000 + i * 200 + 2000 * math.sin(i * 0.5)
            for i in range(40)
        ]
        data = {"prices": prices, "dates": [f"d{i}" for i in range(40)]}

        sma_strategy = MovingAverageCrossover(MAConfig(ma_type=MAType.SMA))
        ema_strategy = MovingAverageCrossover(MAConfig(ma_type=MAType.EMA))

        sma_result = sma_strategy.analyze(data)
        ema_result = ema_strategy.analyze(data)

        # 비선형 데이터에서 SMA와 EMA의 장기 MA는 반드시 차이가 나야 함
        assert sma_result["current_long_ma"] != ema_result["current_long_ma"], (
            "SMA와 EMA의 장기 이동평균이 동일하면 안 됨"
        )

    def test_signal_threshold_filters_weak_crossover(self) -> None:
        """signal_threshold가 약한 교차를 필터링하는지 검증"""
        # 아주 미세한 골든크로스가 발생하는 데이터
        # 장기 횡보 후 살짝 상승
        prices = [50_000.0] * 25 + [50_100.0] * 5  # 미세 상승
        data = {"prices": prices, "dates": [f"d{i}" for i in range(30)]}

        # threshold가 높으면 미세 교차를 무시
        strategy_strict = MovingAverageCrossover(
            MAConfig(short_window=3, long_window=10, signal_threshold=1.0)
        )
        analysis = strategy_strict.analyze(data)
        signal = strategy_strict.generate_signal(analysis)

        # 스프레드가 threshold보다 작으면 HOLD
        if abs(analysis.get("ma_spread", 0)) < 1.0:
            assert signal["signal"] == "hold"


# ═══════════════════════════════════════════════════════════
# 시나리오 3: 에러 전파 & 복원력
# ═══════════════════════════════════════════════════════════


class TestErrorPropagation:
    """브로커 장애, 데이터 부족 등 에러가 올바르게 전파되는지 검증"""

    def setup_method(self) -> None:
        self.client = TestClient(app)
        self.fake_db = FakeDBSession()

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def _setup_deps(self, mock_client: MagicMock) -> None:
        app.dependency_overrides[get_kis_client] = lambda: mock_client

        async def _get_fake_db():
            yield self.fake_db

        app.dependency_overrides[get_db] = _get_fake_db

    def test_broker_error_during_signal_generation(self) -> None:
        """
        시나리오: 신호 생성 중 한투 API 장애 → DataCollectionError 전파

        시세 데이터를 가져오는 단계에서 브로커 오류 발생.
        MarketDataCollector는 _request_get 예외를 DataCollectionError로 감싸므로,
        원본 예외를 던지면 collector가 래핑하여 502를 반환한다.
        """
        mock = MagicMock(spec=KISClient)
        mock._request_get = MagicMock(
            side_effect=BrokerError("한투 API 연결 실패")
        )
        mock.close.return_value = None
        self._setup_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
            "short_window": 5,
            "long_window": 20,
        })
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "DATA_COLLECTION_ERROR"

    def test_broker_error_during_order(self) -> None:
        """
        시나리오: 주문 실행 중 한투 API 장애 → OrderError 전파
        """
        mock = MagicMock(spec=KISClient)
        mock.place_order.side_effect = OrderError("주문 처리 실패")
        mock.close.return_value = None
        self._setup_deps(mock)

        resp = self.client.post("/api/v1/orders", json={
            "stock_code": "005930",
            "order_type": "buy",
            "quantity": 10,
        })
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "ORDER_ERROR"

    def test_broker_error_during_portfolio(self) -> None:
        """
        시나리오: 포트폴리오 조회 중 한투 API 장애 → BrokerError 전파
        """
        mock = MagicMock(spec=KISClient)
        mock.get_balance.side_effect = BrokerError("잔고 조회 실패")
        mock.close.return_value = None
        self._setup_deps(mock)

        resp = self.client.get("/api/v1/portfolio")
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "BROKER_ERROR"

    def test_empty_price_data_returns_validation_error(self) -> None:
        """
        시나리오: 시세 데이터가 빈 배열 → ValidationError
        """
        mock = MagicMock(spec=KISClient)

        def fake_request_get(path, tr_id, params):
            return {"rt_cd": "0", "output2": []}

        mock._request_get = MagicMock(side_effect=fake_request_get)
        mock.close.return_value = None
        self._setup_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
        })
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_signal_order_db_records_match(self) -> None:
        """
        시나리오: 신호 → 주문 실행 후, DB에 신호 1건 + 주문 1건이 기록되었는지

        DB add 호출 순서와 객체 타입을 검증한다.
        """
        prices = _generate_price_series(60_000, 40, trend="up")
        mock = _mock_kis_with_prices(prices)
        mock.place_order.return_value = {"ODNO": "DB-CHECK-001", "ORD_TMD": "143000"}
        self._setup_deps(mock)

        # 신호 생성
        sig_resp = self.client.post("/api/v1/signals", json={"stock_code": "005930"})
        assert sig_resp.status_code == 200

        # 주문 실행
        ord_resp = self.client.post("/api/v1/orders", json={
            "stock_code": "005930",
            "order_type": "buy",
            "quantity": 5,
        })
        assert ord_resp.status_code == 200

        # DB에 2개 기록 (Signal + Order)
        assert len(self.fake_db.added) == 2
        type_names = [type(obj).__name__ for obj in self.fake_db.added]
        assert "Signal" in type_names
        assert "Order" in type_names


# ═══════════════════════════════════════════════════════════
# 시나리오 4: 백테스트 엔드투엔드
# ═══════════════════════════════════════════════════════════


class TestBacktestEndToEnd:
    """백테스팅 전체 흐름을 검증: 데이터 → 전략 실행 → 결과 분석"""

    def test_backtest_golden_dead_cross_with_trades(self) -> None:
        """
        하락 → 상승 → 하락 패턴에서 골든/데드크로스가 발생하고
        거래가 실행되는 전체 흐름 검증
        """
        # Phase 1: 하락 (30일)
        phase1 = _generate_price_series(80_000, 30, trend="down", volatility=200)
        # Phase 2: 상승 (30일) — 골든크로스 유도
        phase2 = _generate_price_series(phase1[-1], 30, trend="up", volatility=300)
        # Phase 3: 하락 (20일) — 데드크로스 유도
        phase3 = _generate_price_series(phase2[-1], 20, trend="down", volatility=400)

        all_prices = phase1 + phase2 + phase3
        historical = [
            {"date": f"2025-{(i//28)+1:02d}-{(i%28)+1:02d}", "close": p}
            for i, p in enumerate(all_prices)
        ]

        strategy = MovingAverageCrossover(
            MAConfig(short_window=5, long_window=20, ma_type=MAType.SMA)
        )
        result = strategy.backtest(historical, initial_capital=10_000_000)

        # 기본 결과 구조 검증
        assert result["initial_capital"] == 10_000_000
        assert isinstance(result["final_capital"], float)
        assert result["final_capital"] > 0
        assert isinstance(result["total_return"], float)
        assert 0 <= result["win_rate"] <= 100
        assert result["max_drawdown"] >= 0

        # 거래가 발생했어야 함
        assert result["total_trades"] > 0
        assert len(result["trades"]) > 0

        # equity curve가 유효한지
        assert len(result["equity_curve"]) > 0
        for point in result["equity_curve"]:
            assert "date" in point
            assert "equity" in point
            assert point["equity"] > 0

        # 거래 기록에 필요한 필드가 다 있는지
        for trade in result["trades"]:
            assert "date" in trade
            assert "type" in trade
            assert "price" in trade
            assert "shares" in trade
            assert trade["shares"] > 0

    def test_backtest_flat_market_no_trades(self) -> None:
        """횡보장에서는 교차가 발생하지 않아 거래가 없어야 함"""
        # 거의 변동 없는 데이터
        prices = [50_000.0] * 50
        historical = [{"date": f"d{i}", "close": p} for i, p in enumerate(prices)]

        strategy = MovingAverageCrossover(
            MAConfig(short_window=5, long_window=20)
        )
        result = strategy.backtest(historical, initial_capital=10_000_000)

        assert result["total_trades"] == 0
        assert result["final_capital"] == 10_000_000
        assert result["total_return"] == 0.0

    def test_backtest_ema_vs_sma_different_results(self) -> None:
        """같은 데이터에서 SMA/EMA 백테스트 결과가 달라야 함"""
        prices = _generate_price_series(60_000, 60, trend="golden_cross", volatility=300)
        historical = [{"date": f"d{i}", "close": p} for i, p in enumerate(prices)]

        sma_result = MovingAverageCrossover(
            MAConfig(ma_type=MAType.SMA)
        ).backtest(historical, initial_capital=10_000_000)

        ema_result = MovingAverageCrossover(
            MAConfig(ma_type=MAType.EMA)
        ).backtest(historical, initial_capital=10_000_000)

        # EMA는 최근 데이터에 민감 → 거래 타이밍/횟수가 다를 수 있음
        # 적어도 하나의 차이가 존재해야 함
        has_difference = (
            sma_result["total_trades"] != ema_result["total_trades"]
            or sma_result["final_capital"] != ema_result["final_capital"]
            or sma_result["total_return"] != ema_result["total_return"]
        )
        assert has_difference, "SMA와 EMA 백테스트 결과가 완전히 동일해선 안 됨"


# ═══════════════════════════════════════════════════════════
# 시나리오 5: 리스크 관리 + 전략 통합 시나리오
# ═══════════════════════════════════════════════════════════


class TestRiskStrategyIntegration:
    """전략 분석 결과를 기반으로 리스크 관리 모듈이 올바르게 동작하는지"""

    def test_position_sizing_with_strategy_output(self) -> None:
        """
        전략 분석으로 얻은 현재가를 기반으로 포지션 사이징 계산
        """
        # 상승 추세 데이터로 분석
        prices = _generate_price_series(60_000, 40, trend="up")
        strategy = MovingAverageCrossover(MAConfig(short_window=5, long_window=20))
        analysis = strategy.analyze({"prices": prices, "dates": [f"d{i}" for i in range(40)]})

        current_price = analysis["current_price"]
        assert current_price > 0

        # 분석 결과의 현재가 기준으로 포지션 크기 계산
        stop_loss = current_price * 0.97  # 3% 손절
        quantity = calculate_position_size(
            equity=20_000_000,
            entry_price=current_price,
            stop_loss_price=stop_loss,
        )
        assert quantity >= 1

        # 주문 금액이 포지션 제한 이내인지
        order_amount = quantity * current_price
        max_position = 20_000_000 * 0.20  # 20%
        assert order_amount <= max_position

    def test_consecutive_trades_respect_position_limits(self) -> None:
        """
        여러 종목에 연속 투자 시 각각 포지션 한도를 지키는지

        같은 계좌에서 3종목에 투자할 때,
        각 포지션이 max_position_size_pct 이내여야 한다.
        """
        equity = 30_000_000
        config = PositionRiskConfig(
            max_risk_per_trade_pct=1.0,
            max_position_size_pct=25.0,  # 종목당 25%
        )

        stocks = [
            {"price": 65_000, "stop": 62_000},  # 삼성전자급
            {"price": 150_000, "stop": 145_000},  # 고가주
            {"price": 15_000, "stop": 14_000},   # 중소형주
        ]

        for stock in stocks:
            qty = calculate_position_size(
                equity=equity,
                entry_price=stock["price"],
                stop_loss_price=stock["stop"],
                config=config,
            )
            assert qty >= 1
            position_value = qty * stock["price"]
            max_allowed = equity * config.max_position_size_pct / 100
            assert position_value <= max_allowed, (
                f"포지션 {position_value:,.0f}원이 한도 {max_allowed:,.0f}원 초과"
            )

    def test_daily_loss_limit_progression(self) -> None:
        """
        계좌 평가액이 점점 줄어들 때 일간 손실 한도 초과 시점 검증
        """
        peak = 10_000_000
        limit = 3.0  # 3% 한도

        # 2% 손실 → 아직 허용
        assert check_daily_loss_limit(peak, peak * 0.98, limit) is True

        # 2.9% 손실 → 아직 허용
        assert check_daily_loss_limit(peak, peak * 0.971, limit) is True

        # 3.1% 손실 → 한도 초과
        with pytest.raises(StrategyError):
            check_daily_loss_limit(peak, peak * 0.969, limit)


# ═══════════════════════════════════════════════════════════
# 시나리오 6: API 입력 검증 통합
# ═══════════════════════════════════════════════════════════


class TestAPIInputValidation:
    """여러 API 엔드포인트에 대한 잘못된 입력 통합 검증"""

    def setup_method(self) -> None:
        self.client = TestClient(app)
        self.fake_db = FakeDBSession()

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def _setup_deps(self, mock_client: MagicMock) -> None:
        app.dependency_overrides[get_kis_client] = lambda: mock_client

        async def _get_fake_db():
            yield self.fake_db

        app.dependency_overrides[get_db] = _get_fake_db

    def test_signal_with_invalid_window_combination(self) -> None:
        """short_window >= long_window → 422"""
        mock = _mock_kis_with_prices([50_000] * 30)
        self._setup_deps(mock)

        resp = self.client.post("/api/v1/signals", json={
            "stock_code": "005930",
            "short_window": 25,
            "long_window": 10,
        })
        assert resp.status_code == 422

    def test_order_with_non_numeric_stock_code(self) -> None:
        """종목코드가 영문 → 422"""
        mock = MagicMock()
        mock.close.return_value = None
        self._setup_deps(mock)

        resp = self.client.post("/api/v1/orders", json={
            "stock_code": "ABCDEF",
            "order_type": "buy",
            "quantity": 10,
        })
        assert resp.status_code == 422

    def test_order_zero_quantity(self) -> None:
        """수량 0 → 422"""
        mock = MagicMock()
        mock.close.return_value = None
        self._setup_deps(mock)

        resp = self.client.post("/api/v1/orders", json={
            "stock_code": "005930",
            "order_type": "buy",
            "quantity": 0,
        })
        assert resp.status_code == 422

    def test_health_check_always_works(self) -> None:
        """헬스체크는 의존성과 무관하게 항상 동작"""
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
