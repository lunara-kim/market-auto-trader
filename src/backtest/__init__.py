"""백테스트 모듈 패키지

시그널 스코어링(센티멘트 + PER + RSI + 볼린저밴드)을
과거 시세 데이터로 검증하기 위한 유틸리티 모음입니다.
"""

from __future__ import annotations

from .engine import BacktestEngine, BacktestResult, BacktestTrade  # noqa: F401
