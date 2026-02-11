# 시스템 아키텍처

Market Auto Trader의 전체 시스템 아키텍처를 설명합니다.

## 개요

Market Auto Trader는 한국 주식 시장에서 AI 기반 자동매매를 수행하는 시스템입니다. 데이터 수집부터 분석, 신호 생성, 주문 실행까지 전 과정을 자동화합니다.

## 시스템 구성도

```
┌─────────────────────────────────────────────────────────────┐
│                        Market Auto Trader                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Data Layer   │───▶│ Strategy     │───▶│ Execution    │  │
│  │ (수집)       │    │ Layer        │    │ Layer        │  │
│  │              │    │ (분석/신호)   │    │ (주문)       │  │
│  └──────────────┘    └──────────────┘    └──────────────┘  │
│         │                    │                    │          │
│         ▼                    ▼                    ▼          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              PostgreSQL Database                     │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
         │                     │                     │
         ▼                     ▼                     ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ 한국투자증권  │    │ OpenAI API   │    │ 경제 지표    │
│ OpenAPI      │    │              │    │ API          │
└──────────────┘    └──────────────┘    └──────────────┘
```

## 주요 컴포넌트

### 1. Data Layer (데이터 수집 계층)

**역할**: 외부 소스로부터 데이터를 수집하고 저장

**주요 기능**:
- 한국투자증권 API를 통한 실시간 시세 조회
- 과거 가격 데이터 수집
- 경제 지표 발표 일정 수집
- 종목 관련 뉴스 수집

**구현**:
- `src/data/collector.py`: MarketDataCollector
- `src/broker/kis_client.py`: KISClient

### 2. Strategy Layer (전략 계층)

**역할**: 수집된 데이터를 분석하고 매매 신호 생성

**주요 기능**:
- 기술적 분석 (이동평균, RSI, MACD 등)
- 기본적 분석 (재무제표, 경제지표)
- AI 기반 패턴 인식 (LangGraph)
- 멀티 에이전트 협업 (시장 분석 에이전트 + 리스크 관리 에이전트)

**구현**:
- `src/strategy/base.py`: BaseStrategy (추상 클래스)
- 향후 구체적인 전략 클래스들 추가 예정

### 3. Execution Layer (실행 계층)

**역할**: 매매 신호를 실제 주문으로 변환하여 실행

**주요 기능**:
- 주문 생성 및 실행
- 포지션 관리
- 리스크 관리 (손절/익절)
- 주문 모니터링

**구현**:
- `src/broker/kis_client.py`: 주문 실행
- `src/models/schema.py`: Order, Portfolio 모델

### 4. Database (데이터베이스)

**역할**: 모든 데이터의 영구 저장소

**주요 테이블**:
- `portfolios`: 포트폴리오 정보
- `orders`: 주문 내역
- `market_data`: 시장 데이터
- `signals`: 매매 신호

**구현**:
- PostgreSQL 15
- SQLAlchemy ORM

## 데이터 흐름

```
1. 데이터 수집
   외부 API → MarketDataCollector → Database

2. 전략 분석
   Database → Strategy → 매매 신호 생성 → Database

3. 주문 실행
   Database (Signal) → Execution Layer → 한국투자증권 API → Database (Order)

4. 포트폴리오 업데이트
   Database (Order) → Portfolio 업데이트
```

## 기술 스택 상세

### Backend
- **FastAPI**: 고성능 비동기 웹 프레임워크
- **Uvicorn**: ASGI 서버
- **SQLAlchemy**: ORM
- **Pydantic**: 데이터 검증

### AI/ML
- **LangGraph**: 멀티 에이전트 워크플로우
- **LangChain**: LLM 체인 구성
- **OpenAI**: GPT 모델 활용

### Database
- **PostgreSQL**: 관계형 데이터베이스
- **Alembic**: 마이그레이션 도구 (향후 추가)

### Infrastructure
- **Docker**: 컨테이너화
- **Docker Compose**: 멀티 컨테이너 오케스트레이션

## 보안 고려사항

1. **API 키 관리**: 환경변수로 관리, .env 파일은 절대 커밋하지 않음
2. **데이터베이스 접근**: 환경별 계정 분리
3. **주문 검증**: 이중 체크 메커니즘
4. **로깅**: 민감한 정보 마스킹

## 확장성 고려사항

1. **수평적 확장**: Docker Swarm 또는 Kubernetes로 확장 가능
2. **데이터베이스 스케일링**: Read Replica 구성 가능
3. **캐싱**: Redis 추가 가능
4. **메시지 큐**: RabbitMQ/Kafka로 비동기 처리 가능

## 다음 단계

1. 한국투자증권 API 완전 구현
2. 기본 매매 전략 개발
3. 백테스팅 엔진 구현
4. LangGraph 멀티 에이전트 시스템 구축
5. 대시보드 개발
