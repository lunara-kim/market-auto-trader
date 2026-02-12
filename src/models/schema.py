"""
SQLAlchemy 데이터베이스 모델

주요 엔티티의 테이블 스키마를 정의합니다.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Portfolio(Base):
    """포트폴리오 테이블"""

    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    account_no = Column(String(50), nullable=False)
    total_value = Column(Float, nullable=False)  # 총 평가금액
    cash = Column(Float, nullable=False)  # 예수금
    profit_loss = Column(Float, default=0.0)  # 손익
    profit_loss_rate = Column(Float, default=0.0)  # 수익률 (%)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계
    orders = relationship("Order", back_populates="portfolio")


class Order(Base):
    """주문 테이블"""

    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"))
    stock_code = Column(String(20), nullable=False)  # 종목 코드
    stock_name = Column(String(100))  # 종목명
    order_type = Column(String(10), nullable=False)  # buy, sell
    order_price = Column(Float)  # 주문가 (None이면 시장가)
    quantity = Column(Integer, nullable=False)  # 수량
    status = Column(String(20), default="pending")  # pending, executed, cancelled
    executed_price = Column(Float)  # 체결가
    executed_at = Column(DateTime)  # 체결 시각
    created_at = Column(DateTime, default=datetime.utcnow)

    # 관계
    portfolio = relationship("Portfolio", back_populates="orders")


class MarketData(Base):
    """시장 데이터 테이블"""

    __tablename__ = "market_data"

    id = Column(Integer, primary_key=True, index=True)
    stock_code = Column(String(20), nullable=False, index=True)
    stock_name = Column(String(100))
    date = Column(DateTime, nullable=False, index=True)
    open_price = Column(Float)  # 시가
    high_price = Column(Float)  # 고가
    low_price = Column(Float)  # 저가
    close_price = Column(Float)  # 종가
    volume = Column(Integer)  # 거래량
    created_at = Column(DateTime, default=datetime.utcnow)


class Signal(Base):
    """매매 신호 테이블"""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    stock_code = Column(String(20), nullable=False)
    signal_type = Column(String(10), nullable=False)  # buy, sell, hold
    strength = Column(Float)  # 신호 강도 (0.0 ~ 1.0)
    target_price = Column(Float)  # 목표가
    stop_loss = Column(Float)  # 손절가
    strategy_name = Column(String(100))  # 전략명
    reason = Column(Text)  # 신호 생성 사유
    is_executed = Column(Boolean, default=False)  # 실행 여부
    created_at = Column(DateTime, default=datetime.utcnow)
