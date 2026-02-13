"""
백테스팅(Backtest) 설정

백테스트 실행 시 사용되는 파라미터를 환경변수로 관리합니다.
실거래와 다른 수수료/세금 체계를 적용하거나,
초기 자본금/무위험 수익률 등을 별도로 지정할 수 있습니다.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BacktestSettings(BaseSettings):
    """백테스팅 전용 설정

    실거래와 분리된 백테스트용 파라미터:
    - 초기 자본금
    - 수수료/세금 (백테스트용 별도 설정 가능)
    - 샤프 비율 계산용 무위험 수익률
    - 연간 거래일수
    """

    # ── 자본금 ──
    initial_capital: float = 10_000_000.0  # 초기 자본금 (1천만 원)

    # ── 수수료/세금 (백테스트용, None이면 trading_settings 값 사용) ──
    commission_rate: float | None = None       # 매수/매도 공통 수수료율
    sell_tax_rate: float | None = None         # 매도 시 총 세율

    # ── 성과 측정 ──
    risk_free_rate: float = 0.035             # 무위험 수익률 (연 3.5%, 샤프 비율용)
    trading_days_per_year: int = 252          # 연간 거래일수

    # ── 데이터 ──
    lookback_multiplier: float = 1.5          # 필요 데이터 기간 배수 (캘린더일 변환용)

    model_config = SettingsConfigDict(
        env_prefix="BACKTEST_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def get_commission_rate(self, fallback: float = 0.00015) -> float:
        """백테스트용 수수료율 반환 (미설정 시 fallback 사용)"""
        return self.commission_rate if self.commission_rate is not None else fallback

    def get_sell_tax_rate(self, fallback: float = 0.0023) -> float:
        """백테스트용 매도 세율 반환 (미설정 시 fallback 사용)"""
        return self.sell_tax_rate if self.sell_tax_rate is not None else fallback


# 전역 백테스트 설정 인스턴스
backtest_settings = BacktestSettings()
