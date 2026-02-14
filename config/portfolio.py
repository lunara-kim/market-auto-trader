"""
포트폴리오(Portfolio) 설정

자동 리밸런싱에 필요한 목표 비중, 임계값, 거래 제약 등을
환경변수로 관리합니다.
"""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PortfolioSettings(BaseSettings):
    """포트폴리오 리밸런싱 설정

    목표 포트폴리오:
    - target_allocations: 종목코드별 목표 비중(%)
    - 비중 합계는 100% 이하여야 함 (나머지는 현금)

    리밸런싱 규칙:
    - rebalance_threshold_pct: 목표 비중에서 이탈 임계값(%)
    - rebalance_mode: "proportional" (전체 비례) 또는 "threshold" (임계값 초과 시만)

    거래 제약:
    - min_trade_amount_krw: 최소 거래 금액 (너무 작은 주문 방지)
    - max_single_order_pct: 한 번 리밸런싱에서 단일 종목 최대 주문 비율(%)
    """

    # ── 목표 포트폴리오 ──
    target_allocations: dict[str, float] = {}  # 종목코드: 목표 비중(%)

    # ── 리밸런싱 임계값 ──
    rebalance_threshold_pct: float = 5.0  # 목표 비중 ±5% 이탈 시 리밸런싱

    # ── 거래 제약 ──
    min_trade_amount_krw: int = 50_000  # 최소 거래 금액 (5만 원)
    max_single_order_pct: float = 10.0  # 단일 종목 최대 주문 비율 (10%)

    # ── 리밸런싱 모드 ──
    rebalance_mode: str = "threshold"  # "proportional" 또는 "threshold"

    model_config = SettingsConfigDict(
        env_prefix="PORTFOLIO_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("target_allocations", mode="after")
    @classmethod
    def validate_allocations(cls, v: dict[str, float]) -> dict[str, float]:
        """목표 비중 합계가 100% 이하인지 검증"""
        if not v:
            return v

        total = sum(v.values())
        if total > 100.0:
            raise ValueError(
                f"목표 비중 합계({total:.2f}%)는 100% 이하여야 합니다."
            )

        for code, pct in v.items():
            if pct < 0:
                raise ValueError(
                    f"종목 {code}의 목표 비중({pct:.2f}%)는 0 이상이어야 합니다."
                )

        return v

    @field_validator("rebalance_threshold_pct", mode="after")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        """리밸런싱 임계값이 양수인지 검증"""
        if v <= 0:
            raise ValueError(
                f"rebalance_threshold_pct({v})는 0보다 커야 합니다."
            )
        return v

    @field_validator("min_trade_amount_krw", mode="after")
    @classmethod
    def validate_min_trade_amount(cls, v: int) -> int:
        """최소 거래 금액이 양수인지 검증"""
        if v <= 0:
            raise ValueError(f"min_trade_amount_krw({v})는 0보다 커야 합니다.")
        return v

    @field_validator("max_single_order_pct", mode="after")
    @classmethod
    def validate_max_order_pct(cls, v: float) -> float:
        """최대 주문 비율이 양수이고 100% 이하인지 검증"""
        if v <= 0 or v > 100:
            raise ValueError(
                f"max_single_order_pct({v})는 0보다 크고 100 이하여야 합니다."
            )
        return v

    @field_validator("rebalance_mode", mode="after")
    @classmethod
    def validate_rebalance_mode(cls, v: str) -> str:
        """리밸런싱 모드가 유효한지 검증"""
        allowed_modes = {"proportional", "threshold"}
        if v not in allowed_modes:
            raise ValueError(
                f"rebalance_mode는 {allowed_modes} 중 하나여야 합니다 (입력: {v})"
            )
        return v


# 전역 포트폴리오 설정 인스턴스
portfolio_settings = PortfolioSettings()
