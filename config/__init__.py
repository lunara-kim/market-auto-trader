"""
설정 패키지

환경변수 기반 설정을 구조화하여 관리합니다.
- settings: 앱/DB/KIS 기본 설정
- trading: 매매 관련 설정 (수수료, 세금, 리스크)
- backtest: 백테스팅 전용 설정
- portfolio: 포트폴리오 리밸런싱 설정
"""

from __future__ import annotations

from config.backtest import backtest_settings
from config.portfolio import portfolio_settings
from config.settings import settings
from config.trading import trading_settings

__all__ = ["backtest_settings", "portfolio_settings", "settings", "trading_settings"]
