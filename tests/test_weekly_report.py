"""주간 리포트 + 거래 기록기 테스트"""

import json
from datetime import date, datetime, timezone


from src.report.trade_logger import SignalRecord, TradeLogger, TradeRecord
from src.report.weekly_report import WeeklyReportGenerator


class TestTradeLogger:
    def test_log_and_retrieve_signal(self, tmp_path):
        logger = TradeLogger(log_dir=tmp_path)
        record = SignalRecord(
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            stock_code="005930",
            stock_name="삼성전자",
            signal_type="buy",
            score=45.0,
            sentiment_score=15.0,
            quality_score=25.0,
            technical_score=5.0,
            reason="테스트",
            price_at_signal=70000,
        )
        logger.log_signal(record)
        signals = logger.get_signals(date.today())
        assert len(signals) == 1
        assert signals[0]["stock_code"] == "005930"

    def test_log_and_retrieve_trade(self, tmp_path):
        logger = TradeLogger(log_dir=tmp_path)
        record = TradeRecord(
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            stock_code="005930",
            stock_name="삼성전자",
            action="buy",
            quantity=10,
            price=70000,
            notional=700000,
            signal_score=45.0,
        )
        logger.log_trade(record)
        trades = logger.get_trades(date.today())
        assert len(trades) == 1
        assert trades[0]["action"] == "buy"

    def test_date_range(self, tmp_path):
        logger = TradeLogger(log_dir=tmp_path)
        today = date.today()
        # 직접 파일 생성
        data = {
            "signals": [{"stock_code": "005930", "signal_type": "buy"}],
            "trades": [{"stock_code": "005930", "action": "buy", "notional": 100000}],
        }
        (tmp_path / f"{today.isoformat()}.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        log = logger.get_date_range(today, today)
        assert len(log.signals) == 1
        assert len(log.trades) == 1


class TestWeeklyReport:
    def _setup_logger(self, tmp_path) -> TradeLogger:
        """테스트용 거래 데이터 셋업"""
        logger = TradeLogger(log_dir=tmp_path)
        today = date.today()
        data = {
            "signals": [
                {"stock_code": "005930", "stock_name": "삼성전자", "signal_type": "buy", "score": 50.0},
                {"stock_code": "000660", "stock_name": "SK하이닉스", "signal_type": "strong_buy", "score": 70.0},
                {"stock_code": "035420", "stock_name": "NAVER", "signal_type": "hold", "score": 10.0},
            ],
            "trades": [
                {"stock_code": "005930", "stock_name": "삼성전자", "action": "buy", "quantity": 10, "price": 70000, "notional": 700000, "signal_score": 50.0},
                {"stock_code": "005930", "stock_name": "삼성전자", "action": "sell", "quantity": 10, "price": 73000, "notional": 730000, "signal_score": -30.0},
                {"stock_code": "000660", "stock_name": "SK하이닉스", "action": "buy", "quantity": 5, "price": 150000, "notional": 750000, "signal_score": 70.0},
            ],
        }
        (tmp_path / f"{today.isoformat()}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        return logger

    def test_generate_stats(self, tmp_path):
        logger = self._setup_logger(tmp_path)
        gen = WeeklyReportGenerator(logger)
        stats = gen.generate_stats(weeks_ago=0)
        assert stats.total_trades == 3
        assert stats.buy_count == 2
        assert stats.sell_count == 1

    def test_win_rate(self, tmp_path):
        logger = self._setup_logger(tmp_path)
        gen = WeeklyReportGenerator(logger)
        stats = gen.generate_stats(weeks_ago=0)
        # 삼성전자: sell 730k - buy 700k = +30k (win)
        # SK하이닉스: buy only = -750k (loss)
        assert stats.win_count == 1
        assert stats.loss_count == 1
        assert stats.win_rate == 50.0

    def test_format_markdown(self, tmp_path):
        logger = self._setup_logger(tmp_path)
        gen = WeeklyReportGenerator(logger)
        stats = gen.generate_stats(weeks_ago=0)
        md = gen.format_markdown(stats)
        assert "주간 투자 리포트" in md
        assert "성과 요약" in md
        assert "삼성전자" in md

    def test_signal_accuracy(self, tmp_path):
        logger = self._setup_logger(tmp_path)
        gen = WeeklyReportGenerator(logger)
        stats = gen.generate_stats(weeks_ago=0)
        # 2 buy signals (005930, 000660), both traded
        assert stats.buy_signal_count == 2
        assert stats.signal_accuracy == 100.0

    def test_empty_week(self, tmp_path):
        logger = TradeLogger(log_dir=tmp_path)
        gen = WeeklyReportGenerator(logger)
        stats = gen.generate_stats(weeks_ago=0)
        assert stats.total_trades == 0
        md = gen.format_markdown(stats)
        assert "거래가 없습니다" in md

    def test_cumulative_stats(self, tmp_path):
        logger = self._setup_logger(tmp_path)
        gen = WeeklyReportGenerator(logger)
        cumulative = gen.generate_cumulative_stats(weeks=2)
        assert len(cumulative) == 2


class TestReportAPI:
    def test_weekly_report_api(self, tmp_path):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.report import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/v1/report/weekly")
        assert resp.status_code == 200
        data = resp.json()
        assert "markdown" in data
        assert "stats" in data

    def test_cumulative_report_api(self, tmp_path):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.report import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/v1/report/cumulative?weeks=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "weeks" in data
        assert len(data["weeks"]) == 2
