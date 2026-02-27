# CRON_CONTEXT.md — 크론잡 서브에이전트용 컨텍스트

## 프로젝트 개요
- **market-auto-trader**: 한투 OpenAPI 기반 AI 자동매매 시스템
- **위치**: `/Users/lunara/.openclaw/workspace/market-auto-trader`
- **venv**: `source .venv/bin/activate`
- **Git**: `origin` = `jjangdeok/market-auto-trader`, `upstream` = `lunara-kim/market-auto-trader`

## 핵심 코드 위치
- `src/strategy/auto_trader.py` — AutoTraderEngine (시그널 스코어링)
- `src/strategy/auto_trader_scheduler.py` — 스케줄러
- `src/analysis/sentiment.py` — FearGreedIndex, HybridSentimentAnalyzer
- `src/analysis/news_sentiment.py` — LLM 뉴스 분석 (OpenAI gpt-4o-mini)
- `src/analysis/news_collector.py` — RSS 뉴스 수집
- `src/analysis/screener.py` — PER quality 스크리닝
- `src/analysis/market_profile.py` — 시장/섹터별 프로필 (PEG ratio)
- `src/analysis/universe.py` — KOSPI_TOP30, US_UNIVERSE 프리셋
- `src/backtest/engine.py` — BacktestEngine
- `src/backtest/data_loader.py` — yfinance 히스토리컬 데이터
- `src/backtest/historical_sentiment.py` — 과거 Fear&Greed 데이터
- `src/backtest/historical_per.py` — 과거 PER 데이터
- `src/backtest/optimizer.py` — Grid Search 파라미터 최적화
- `src/report/weekly_report.py` — 주간 성과 리포트
- `src/report/trade_logger.py` — 거래 기록
- `src/strategy/safety.py` — 긴급 정지, 일일 손실 가드

## 시그널 스코어링 공식
- sentiment(±30) + PER quality(0 or +25) + RSI(±20) + Bollinger(±15) = total
- Buy > 35, Sell < -20
- 트레일링 스톱: 최고가 대비 -5%
- 익절: +10%, 최소 거래 간격: 5일

## 시장/섹터 프로필
- KR VALUE: PER < 업종평균 → undervalued
- US GROWTH: PEG ratio 사용 (PEG < 1.5 → 저평가)
- US VALUE: PER threshold 25
- ETF: PER 필터 스킵, 기술적 분석만

## 백테스트 결과 히스토리
- 파일: `memory/backtest-history.json` (없으면 새로 생성)
- 매 실행 후 결과를 append해서 추이 추적
- 형식: {"date": "YYYY-MM-DD", "market": "KR|US", "total_return": N, "win_rate": N, "mdd": N, "sharpe": N, "details": {...}}

## GitHub 작업 규칙
- `gh` CLI로 Issue/PR 생성 (인증 실패 시 스킵하고 리포트에 기록)
- PR: `jjangdeok` fork에서 작업 → `lunara-kim` 본레포로 PR
- 브랜치: `fix/auto-YYYYMMDD-설명` 또는 `feature/auto-YYYYMMDD-설명`
- 테스트 필수: `python -m pytest tests/ -x -q`
- lint 필수: `ruff check src/ tests/`

## 자율 개선 기준
| 조건 | 대응 |
|------|------|
| 특정 종목 연속 3일+ 손실 | 해당 종목 파라미터 조정 검토 → Issue |
| 전체 승률 < 40% | 시그널 임계치 재검토 → Issue 또는 PR |
| MDD > 5% | 손절 기준 강화 → Issue 또는 PR |
| 코드 에러/버그 | 즉시 수정 PR (subagent spawn) |
| 센티멘트/뉴스 API 실패 | fallback 동작 확인, 필요시 수정 |
| 새 패턴/아이디어 발견 | 구체적 개선안 → Issue |

## 주의사항
- **절대 실제 주문 보내지 말 것**
- dry_run=True 항상 유지
- 파라미터 변경 시 반드시 백테스트로 Before/After 검증
