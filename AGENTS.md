# AGENTS.md - AI 코딩 에이전트 가이드

이 문서는 AI 코딩 에이전트(GitHub Copilot, Cursor, Claude, GPT 등)가 이 프로젝트를 이해하고 효과적으로 기여할 수 있도록 작성되었습니다.

## 프로젝트 개요

**Market Auto Trader**는 한국 주식 시장 자동매매 프로그램입니다.

### 목표
- 한국투자증권 OpenAPI를 활용한 실시간 매매
- LangGraph 기반 멀티 에이전트 시스템으로 지능형 의사결정
- 백테스팅을 통한 전략 검증
- 리스크 관리 자동화

### 현재 상태
- **Phase 0**: 프로젝트 초기 구조 세팅 완료
- 기본 FastAPI 앱, Docker 환경, 스켈레톤 코드 구현됨
- 실제 기능은 대부분 구현 예정 (NotImplementedError)

## 기술 스택

### Backend
- **Python 3.11**: 메인 언어
- **FastAPI**: REST API 프레임워크
- **SQLAlchemy 2.0**: ORM
- **Pydantic 2.5+**: 데이터 검증 및 설정 관리
- **Uvicorn**: ASGI 서버

### AI/ML
- **LangGraph 0.2+**: 멀티 에이전트 워크플로우
- **LangChain 0.3+**: LLM 체인
- **OpenAI 1.50+**: GPT 모델

### Database
- **PostgreSQL 15**: 메인 데이터베이스

### Infrastructure
- **Docker & Docker Compose**: 컨테이너화
- **pytest**: 테스트 프레임워크

### 외부 API
- **한국투자증권 OpenAPI**: 주식 시세 조회 및 주문

## 디렉토리 구조

```
market-auto-trader/
├── config/               # 설정 파일
│   └── settings.py       # Pydantic Settings 기반 환경변수 관리
├── src/                  # 소스 코드
│   ├── main.py           # FastAPI 앱 엔트리포인트
│   ├── api/              # API 라우터
│   │   └── routes.py     # REST API 엔드포인트
│   ├── broker/           # 증권사 API 클라이언트
│   │   └── kis_client.py # 한국투자증권 API 클라이언트
│   ├── data/             # 데이터 수집
│   │   └── collector.py  # 시장 데이터 수집기
│   ├── strategy/         # 매매 전략
│   │   └── base.py       # 전략 베이스 클래스 (ABC)
│   ├── models/           # 데이터베이스 모델
│   │   └── schema.py     # SQLAlchemy 모델
│   └── utils/            # 유틸리티
│       └── logger.py     # 로깅 설정
├── tests/                # 테스트
│   └── test_health.py    # 기본 헬스체크 테스트
├── docs/                 # 문서
│   └── architecture.md   # 시스템 아키텍처
├── docker-compose.yml    # Docker Compose 설정
├── Dockerfile            # Docker 이미지 빌드
├── requirements.txt      # Python 의존성
└── .env.example          # 환경변수 템플릿
```

## 개발 가이드라인

### Python 코딩 스타일

1. **Type Hints 필수**: 모든 함수/메서드에 타입 힌트 사용
   ```python
   def get_price(self, stock_code: str) -> Dict[str, Any]:
       pass
   ```

2. **Docstring 작성**: 한국어로 명확하게 설명
   ```python
   def fetch_stock_price(self, stock_code: str) -> Dict[str, Any]:
       """
       주식 가격 데이터 수집
       
       Args:
           stock_code: 종목 코드 (예: "005930" - 삼성전자)
       
       Returns:
           가격 데이터 (현재가, 등락률 등)
       """
   ```

3. **한국어 주석**: 코드 내 주석은 한국어로 작성
   ```python
   # 계좌 잔고 조회
   balance = client.get_balance()
   ```

4. **Error Handling**: 명확한 에러 메시지와 함께 예외 처리
   ```python
   try:
       result = api_call()
   except Exception as e:
       logger.error(f"API 호출 실패: {e}")
       raise
   ```

### FastAPI 패턴

1. **라우터 사용**: 기능별로 라우터 분리
2. **의존성 주입**: 데이터베이스 세션, 설정 등
3. **Pydantic 모델**: 요청/응답 검증
4. **비동기 처리**: async/await 적극 활용

### 데이터베이스

1. **SQLAlchemy 2.0 스타일**: 최신 API 사용
2. **관계 정의**: relationship() 사용
3. **인덱스**: 조회가 많은 컬럼에 index=True
4. **Timestamp**: created_at, updated_at 필수

### 테스트

1. **pytest 사용**: 모든 새 기능에 테스트 작성
2. **TestClient**: FastAPI 엔드포인트 테스트
3. **Mock**: 외부 API 호출은 Mock 사용
4. **Coverage**: 70% 이상 목표

## 환경 설정

### 로컬 개발

```bash
# Python 가상환경
python3.11 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일 수정

# 앱 실행
uvicorn src.main:app --reload
```

### Docker 개발

```bash
# 컨테이너 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f app

# 컨테이너 중지
docker-compose down
```

## 다음 구현 항목 (우선순위)

### Phase 1: 데이터 수집 (High Priority)
1. `src/broker/kis_client.py` 완전 구현
   - OAuth 인증
   - get_balance() 구현
   - get_price() 구현
   - place_order() 구현
2. `src/data/collector.py` 구현
   - fetch_stock_price() 구현
   - 데이터 저장 로직

### Phase 2: 전략 엔진 (Medium Priority)
1. 기본 전략 구현 (이동평균 전략 등)
2. 백테스팅 프레임워크
3. 시그널 생성 로직

### Phase 3: AI 에이전트 (Medium Priority)
1. LangGraph 멀티 에이전트 시스템
2. 시장 분석 에이전트
3. 리스크 관리 에이전트

## 중요한 규칙

### DO ✅
- 모든 API 키는 환경변수로 관리
- 주석과 문서는 한국어로 작성
- 테스트 코드 작성
- 로깅 적극 활용
- Type hints 사용

### DON'T ❌
- .env 파일을 절대 커밋하지 말 것
- 하드코딩된 API 키/비밀번호
- 주석 없는 복잡한 로직
- 예외 무시 (pass)
- 글로벌 변수 남용

## 테스트 실행

```bash
# 전체 테스트
pytest

# 특정 파일
pytest tests/test_health.py

# Coverage
pytest --cov=src tests/
```

## 도움이 필요한 경우

1. **아키텍처 이해**: `docs/architecture.md` 참고
2. **API 문서**: http://localhost:8000/docs (앱 실행 후)
3. **환경변수**: `.env.example` 참고
4. **이슈 제기**: GitHub Issues

## AI 에이전트를 위한 팁

- 이 프로젝트는 **초기 단계**입니다. 대부분의 기능이 스켈레톤 상태입니다.
- 새 기능 구현 시 **기존 패턴을 따라주세요** (예: BaseStrategy 상속)
- **한국어 주석**을 작성해주세요.
- **Type hints**와 **Docstring**은 필수입니다.
- 외부 API 연동 시 **에러 처리**와 **재시도 로직**을 고려해주세요.
- 금융 데이터는 **정확성이 중요**합니다. 검증 로직을 추가해주세요.
