"""
거래 기록기 — 시그널과 주문을 JSON 파일에 기록

모든 시그널 발생과 실제 체결을 기록하여 주간 리포트 생성 시 활용합니다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SignalRecord:
    """시그널 기록"""

    timestamp: str
    stock_code: str
    stock_name: str
    signal_type: str  # strong_buy, buy, hold, sell, strong_sell
    score: float
    sentiment_score: float
    quality_score: float
    technical_score: float
    reason: str
    price_at_signal: int = 0


@dataclass
class TradeRecord:
    """거래(체결) 기록"""

    timestamp: str
    stock_code: str
    stock_name: str
    action: str  # buy / sell
    quantity: int
    price: int
    notional: int
    signal_score: float
    dry_run: bool = False


@dataclass
class TradeLog:
    """전체 거래 로그"""

    signals: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)


class TradeLogger:
    """거래 기록기 — JSON 파일 기반"""

    def __init__(self, log_dir: str | Path = "data/trade_logs") -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self, target_date: date | None = None) -> Path:
        """날짜별 로그 파일 경로"""
        d = target_date or datetime.now(tz=timezone.utc).date()
        return self._log_dir / f"{d.isoformat()}.json"

    def _load(self, target_date: date | None = None) -> TradeLog:
        path = self._log_path(target_date)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return TradeLog(
                    signals=data.get("signals", []),
                    trades=data.get("trades", []),
                )
            except (json.JSONDecodeError, KeyError):
                logger.warning("로그 파일 파싱 실패: %s", path)
        return TradeLog()

    def _save(self, log: TradeLog, target_date: date | None = None) -> None:
        path = self._log_path(target_date)
        path.write_text(
            json.dumps({"signals": log.signals, "trades": log.trades}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def log_signal(self, record: SignalRecord) -> None:
        """시그널 기록"""
        today = datetime.now(tz=timezone.utc).date()
        log = self._load(today)
        log.signals.append(asdict(record))
        self._save(log, today)
        logger.debug("시그널 기록: %s %s score=%.1f", record.stock_code, record.signal_type, record.score)

    def log_trade(self, record: TradeRecord) -> None:
        """거래 기록"""
        today = datetime.now(tz=timezone.utc).date()
        log = self._load(today)
        log.trades.append(asdict(record))
        self._save(log, today)
        logger.debug("거래 기록: %s %s %d주 @ %d", record.stock_code, record.action, record.quantity, record.price)

    def get_signals(self, target_date: date) -> list[dict[str, Any]]:
        """특정 날짜의 시그널 조회"""
        return self._load(target_date).signals

    def get_trades(self, target_date: date) -> list[dict[str, Any]]:
        """특정 날짜의 거래 조회"""
        return self._load(target_date).trades

    def get_date_range(self, start: date, end: date) -> TradeLog:
        """날짜 범위의 모든 기록 조회"""
        all_signals: list[dict[str, Any]] = []
        all_trades: list[dict[str, Any]] = []
        current = start
        while current <= end:
            log = self._load(current)
            all_signals.extend(log.signals)
            all_trades.extend(log.trades)
            current = date.fromordinal(current.toordinal() + 1)
        return TradeLog(signals=all_signals, trades=all_trades)
