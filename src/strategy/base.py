"""
매매 전략 베이스 클래스

모든 매매 전략이 상속받아야 하는 추상 클래스를 정의합니다.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseStrategy(ABC):
    """매매 전략 베이스 클래스"""

    def __init__(self, name: str):
        """
        Args:
            name: 전략 이름
        """
        self.name = name

    @abstractmethod
    def analyze(self, market_data: dict[str, Any]) -> dict[str, Any]:
        """
        시장 데이터를 분석하여 인사이트를 도출

        Args:
            market_data: 시장 데이터 (가격, 지표, 뉴스 등)

        Returns:
            분석 결과 (기술적 지표, 트렌드, 리스크 등)
        """
        pass

    @abstractmethod
    def generate_signal(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        """
        분석 결과를 바탕으로 매매 신호 생성

        Args:
            analysis_result: analyze() 메서드의 결과

        Returns:
            매매 신호 (매수/매도/관망, 목표가, 손절가 등)
        """
        pass

    @abstractmethod
    def backtest(
        self, historical_data: list[dict[str, Any]], initial_capital: float
    ) -> dict[str, Any]:
        """
        과거 데이터로 전략 백테스팅

        Args:
            historical_data: 과거 시장 데이터
            initial_capital: 초기 자본금

        Returns:
            백테스팅 결과 (수익률, 승률, MDD, 샤프 비율 등)
        """
        pass
