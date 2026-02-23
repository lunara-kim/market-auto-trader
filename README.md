# Market Auto Trader (시장 자동매매 프로그램) 📈

한국투자증권 OpenAPI 기반 자동매매 프로그램입니다. 다양한 기술적 분석 전략, 자동 리밸런싱, 실시간 모니터링, 그리고 체계적인 리스크 관리를 지원합니다.

## 🎯 주요 기능

### 매매 전략
- **이동평균 교차 전략** — SMA/EMA 골든크로스·데드크로스 기반 매매 신호
- **RSI (상대강도지수) 전략** — 과매수/과매도 판단
- **볼린저 밴드 전략** — 밴드 이탈 시 매매 신호
- **복합 전략 매니저** — 다중 전략 신호 종합 (다수결/가중/만장일치 투표)
- **백테스팅 엔진** — 수수료·세금·MDD·샤프비율 포함 전략 검증

### 자동 매매
- **한투 OpenAPI 연동** — 시세 조회, 매수/매도 주문, 잔고 조회
- **원샷 주문** — 국내/해외 종목 즉시 매수
- **자동 리밸런싱** — 목표 비중 기반 자동 매매 (일/주/월 스케줄)
- **리스크 관리** — 최대 손실 제한, 포지션 사이징

### 실시간 모니터링
- **WebSocket 실시간 시세** — 한투 WebSocket API 연동, 자동 재연결
- **PnL 대시보드 API** — 실시간 포트폴리오 손익 조회
- **알림 시스템** — 손절/목표가/급등급락/거래량 이상 시 Discord 알림
- **상세 헬스체크** — DB 연결, API 상태, 업타임 모니터링

### 데이터 관리
- **일봉 데이터 자동 수집** — 스케줄 기반 DB 저장
- **히스토리컬 데이터 캐시** — DB 캐싱으로 API 호출 절약
- **데이터 품질 검증** — OHLCV 유효성, 이상치/누락일 탐지
- **거래 리포트** — 일일 요약, 포트폴리오 스냅샷, 실현 손익 계산

## 🛠 기술 스택

| 영역 | 기술 |
|------|------|
| **Backend** | Python 3.13, FastAPI, Pydantic v2 |
| **Database** | PostgreSQL, SQLAlchemy 2.0, Alembic |
| **Trading API** | 한국투자증권 OpenAPI (REST + WebSocket) |
| **Testing** | pytest (726+ 테스트), pytest-asyncio |
| **Lint** | ruff |
| **Infra** | Docker, Docker Compose, GitHub Actions CI |

## 📁 프로젝트 구조

```
market-auto-trader/
├── config/
│   ├── settings.py          # 앱 기본 설정
│   ├── trading.py           # 매매 설정 (수수료, 세금, 전략 파라미터)
│   ├── backtest.py          # 백테스트 설정 (초기자본, 무위험수익률)
│   └── portfolio.py         # 포트폴리오 설정 (목표 비중, 리밸런싱)
├── src/
│   ├── main.py              # FastAPI 앱 엔트리포인트
│   ├── db.py                # DB 연결 설정
│   ├── exceptions.py        # 커스텀 예외
│   ├── api/
│   │   ├── routes.py        # 기본 라우터 (헬스체크)
│   │   ├── orders.py        # 주문 API
│   │   ├── portfolio.py     # 포트폴리오 API
│   │   ├── signals.py       # 매매 신호 API
│   │   ├── policies.py      # 원샷 주문 정책 API
│   │   ├── alerts.py        # 알림 관리 API
│   │   ├── rebalancing.py   # 리밸런싱 API
│   │   ├── streaming.py     # 실시간 스트리밍 API
│   │   ├── dashboard.py     # PnL 대시보드 API
│   │   ├── data_pipeline.py # 데이터 파이프라인 API
│   │   ├── trade_report.py  # 거래 리포트 API
│   │   ├── health.py        # 상세 헬스체크 API
│   │   └── strategy_manager.py  # 전략 비교 API
│   ├── broker/
│   │   └── kis_client.py    # 한투 OpenAPI 클라이언트
│   ├── data/
│   │   ├── collector.py     # 시장 데이터 수집
│   │   ├── pipeline.py      # 일봉 데이터 파이프라인
│   │   ├── cache.py         # 데이터 캐싱 레이어
│   │   └── quality.py       # 데이터 품질 검증
│   ├── strategy/
│   │   ├── base.py          # BaseStrategy 추상 클래스
│   │   ├── moving_average.py    # 이동평균 교차 전략
│   │   ├── rsi.py               # RSI 전략
│   │   ├── bollinger_bands.py   # 볼린저 밴드 전략
│   │   ├── strategy_manager.py  # 복합 전략 매니저
│   │   ├── rebalancer.py       # 리밸런싱 엔진
│   │   ├── rebalance_scheduler.py  # 리밸런싱 스케줄러
│   │   └── risk.py             # 리스크 관리
│   ├── streaming/
│   │   └── websocket_client.py  # KIS WebSocket 실시간 시세
│   ├── notification/
│   │   ├── alert_manager.py     # 알림 규칙 관리
│   │   └── discord_notifier.py  # Discord 알림 연동
│   └── utils/
│       ├── retry.py         # Exponential backoff 재시도
│       ├── trade_report.py  # 거래 리포트 유틸
│       └── logger.py        # 로깅 설정
├── alembic/                 # DB 마이그레이션
├── tests/                   # 726+ 테스트
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .github/workflows/ci.yml # GitHub Actions CI
```

## 🚀 설치 및 실행

### 1. 환경 설정

```bash
git clone https://github.com/lunara-kim/market-auto-trader.git
cd market-auto-trader

cp .env.example .env
# .env 파일에 한투 API 키 등 설정
```

### 2. Docker로 실행

```bash
docker compose up -d          # PostgreSQL + 앱 실행
docker compose logs -f app    # 로그 확인
```

### 3. 로컬 개발 모드

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# DB 마이그레이션
alembic upgrade head

# 앱 실행
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 테스트 실행

```bash
python -m pytest -q           # 전체 테스트
python -m pytest --tb=short   # 실패 시 상세 출력
```

### 5. API 문서

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- 헬스체크: http://localhost:8000/health
- 상세 헬스: http://localhost:8000/api/v1/health/detailed

## 📊 API 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/health` | GET | 기본 헬스체크 |
| `/api/v1/health/detailed` | GET | 상세 헬스체크 (DB, API 상태) |
| `/api/v1/orders` | POST/GET | 주문 실행 및 내역 조회 |
| `/api/v1/portfolio` | GET | 포트폴리오 현황 |
| `/api/v1/portfolio/summary` | GET | 포트폴리오 요약 |
| `/api/v1/signals` | POST | 매매 신호 생성 |
| `/api/v1/strategies/available` | GET | 사용 가능한 전략 목록 |
| `/api/v1/strategies/signal` | POST | 복합 전략 신호 |
| `/api/v1/strategies/compare` | POST | 전략별 성과 비교 |
| `/api/v1/alerts` | CRUD | 알림 규칙 관리 |
| `/api/v1/rebalancing` | POST/GET | 리밸런싱 실행/내역 |
| `/api/v1/dashboard` | GET | PnL 대시보드 |
| `/api/v1/streaming` | WS/GET | 실시간 시세 |
| `/api/v1/data-pipeline` | POST/GET | 데이터 수집/상태 |
| `/api/v1/reports` | GET | 거래 리포트 |

## 📝 개발 로드맵

### Phase 1: 기초 인프라 ✅
Docker, CI/CD, DB 마이그레이션, 한투 API 클라이언트, 시장 데이터 수집

### Phase 2: 전략 + API ✅
이동평균 전략, 백테스팅, 포트폴리오/주문 API, 리스크 관리, config 구조화

### Phase 3: 자동 매매 시스템 고도화 ✅
- 3-1: 전략 다변화 (RSI, 볼린저 밴드, 복합 전략 매니저)
- 3-2: 자동 리밸런싱 (목표 비중, 스케줄러, 내역 DB)
- 3-3: 실시간 모니터링 (WebSocket, PnL 대시보드, 알림)
- 3-4: 데이터 파이프라인 (자동 수집, 캐싱, 품질 검증)
- 3-5: 운영 안정성 (에러 재시도, 헬스체크, 거래 리포트)

### Phase 4: 프로덕션 준비 (예정)
- 프론트엔드 대시보드 (React)
- 모의투자 연동 테스트
- 배포 파이프라인 (CD)
- 모니터링 (Prometheus + Grafana)

## ⚠️ 주의사항

- 이 프로젝트는 **교육 및 연구 목적**으로 개발되었습니다.
- 실제 투자에 사용하기 전에 충분한 모의투자 테스트가 필요합니다.
- 투자로 인한 손실은 사용자 본인의 책임입니다.
- 한국투자증권 API 사용 시 약관을 준수해야 합니다.

## 📄 라이선스

Apache License 2.0 — [LICENSE](LICENSE) 참고

## 🤝 기여

이슈 및 풀 리퀘스트 환영합니다!
