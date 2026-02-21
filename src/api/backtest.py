"""백테스트 API 엔드포인트."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.backtest.data_loader import load_history
from src.backtest.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.backtest.historical_per import HistoricalPERCalculator
from src.backtest.historical_sentiment import HistoricalFearGreedLoader

router = APIRouter(prefix="/api/v1/backtest", tags=["Backtest"])


class BacktestRunRequest(BaseModel):
    symbols: List[str] = Field(..., description="백테스트 대상 심볼들")
    period: str = Field("6mo", description="yfinance period 문자열")
    interval: str = Field("1d", description="캔들 간격")
    initial_capital: float = Field(10_000_000.0)
    sentiment_bias: float = Field(0.0, description="센티멘트 스코어 고정값")
    use_sentiment: bool = Field(True, description="히스토리컬 Fear & Greed 반영 여부")
    use_per: bool = Field(True, description="히스토리컬 PER quality 반영 여부")


class BacktestRunResponse(BaseModel):
    backtest_id: str
    summary: Dict[str, Any]


class BacktestResultResponse(BaseModel):
    backtest_id: str
    result: Dict[str, Any]


# 메모리 내 결과 저장소 (프로세스 생명주기 동안만 유지)
_BACKTEST_RESULTS: dict[str, BacktestResult] = {}


@router.post("/run", response_model=BacktestRunResponse)
async def run_backtest(payload: BacktestRunRequest) -> BacktestRunResponse:
    if not payload.symbols:
        raise HTTPException(status_code=400, detail="symbols must not be empty")

    config = BacktestConfig(
        initial_capital=payload.initial_capital,
        sentiment_bias=payload.sentiment_bias,
        use_sentiment=payload.use_sentiment,
        use_per=payload.use_per,
    )

    sentiment_loader: HistoricalFearGreedLoader | None = None
    per_calculator: HistoricalPERCalculator | None = None

    if payload.use_sentiment:
        sentiment_loader = HistoricalFearGreedLoader()
        sentiment_loader.load()

    if payload.use_per:
        per_calculator = HistoricalPERCalculator()

    engine = BacktestEngine(
        config=config,
        sentiment_loader=sentiment_loader,
        per_calculator=per_calculator,
    )

    symbol_data: dict[str, Any] = {}
    for symbol in payload.symbols:
        df = load_history(symbol, period=payload.period, interval=payload.interval)
        symbol_data[symbol] = df

    result = engine.run(symbol_data)

    import uuid

    backtest_id = uuid.uuid4().hex
    _BACKTEST_RESULTS[backtest_id] = result

    summary = {
        "total_return": result.total_return,
        "win_rate": result.win_rate,
        "avg_return": result.avg_return,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
    }
    return BacktestRunResponse(backtest_id=backtest_id, summary=summary)


@router.get("/results/{backtest_id}", response_model=BacktestResultResponse)
async def get_backtest_result(backtest_id: str) -> BacktestResultResponse:
    result = _BACKTEST_RESULTS.get(backtest_id)
    if result is None:
        raise HTTPException(status_code=404, detail="backtest result not found")

    # Pydantic 모델 호환을 위해 dict 형태로 직렬화
    result_dict = {
        "total_return": result.total_return,
        "win_rate": result.win_rate,
        "avg_return": result.avg_return,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "trades": [
            {
                "symbol": t.symbol,
                "date": t.date,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "pnl_pct": t.pnl_pct,
            }
            for t in result.trades
        ],
        "equity_curve": result.equity_curve,
        "per_symbol": result.per_symbol,
    }
    return BacktestResultResponse(backtest_id=backtest_id, result=result_dict)
