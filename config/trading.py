"""
매매(Trading) 설정

수수료, 세금, 전략 기본값, 리스크 관리 파라미터 등
매매 실행에 필요한 설정을 환경변수로 관리합니다.

기존에 코드 내에 하드코딩되어 있던 값들을 외부화하여,
실거래/모의투자/백테스트 환경별로 다르게 설정할 수 있습니다.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingSettings(BaseSettings):
    """매매 관련 설정

    수수료/세금:
    - 한투 기준 기본값 (2024년 기준)
    - 매수 수수료: 0.015% (온라인 할인)
    - 매도 수수료: 0.015%
    - 증권거래세: 0.18% (코스피, 2024~), 코스닥 0.18%
    - 농어촌특별세: 0.15% (코스피만)

    전략 기본값:
    - 이동평균 단기/장기 기간
    - 신호 임계값 (노이즈 필터)

    리스크 관리:
    - 1트레이드 최대 손실 비율
    - 종목당 최대 포지션 비율
    - 일간 최대 손실 한도
    """

    # ── 수수료 ──
    buy_commission_rate: float = 0.00015   # 매수 수수료율 (0.015%)
    sell_commission_rate: float = 0.00015  # 매도 수수료율 (0.015%)

    # ── 세금 ──
    securities_tax_rate: float = 0.0018    # 증권거래세 (0.18%)
    rural_tax_rate: float = 0.0015         # 농어촌특별세 (0.15%, 코스피만)
    total_sell_tax_rate: float = 0.0023    # 매도 시 총 세율 (거래세+농특세, 기본값)

    # ── 이동평균 전략 기본값 ──
    ma_short_window: int = 5              # 단기 이동평균 기간
    ma_long_window: int = 20             # 장기 이동평균 기간
    ma_signal_threshold: float = 0.0      # 교차 시 최소 스프레드(%) — 노이즈 필터

    # ── 리스크 관리 ──
    max_risk_per_trade_pct: float = 1.0   # 1트레이드 최대 손실 비율(%)
    max_position_size_pct: float = 20.0   # 종목당 최대 포지션 비율(%)
    max_daily_loss_pct: float = 3.0       # 일간 최대 손실 한도(%)

    # ── 원샷 주문 ──
    oneshot_max_notional_krw: int = 1_000_000  # 원샷 주문 기본 금액 상한 (100만 원)

    model_config = SettingsConfigDict(
        env_prefix="TRADING_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# 전역 매매 설정 인스턴스
trading_settings = TradingSettings()
