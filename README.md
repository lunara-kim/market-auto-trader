# Market Auto Trader (시장 자동매매 프로그램)

한국 주식 시장 자동매매 프로그램입니다. AI 기반 시장 분석과 자동 주문 실행을 지원합니다.

## 🎯 주요 기능 (계획)

- **한국투자증권 OpenAPI 연동**: 실시간 시세 조회 및 주문 실행
- **AI 기반 매매 신호 생성**: LangGraph 멀티 에이전트를 활용한 지능형 매매 전략
- **경제 일정 기반 전략**: 주요 경제 지표 발표 일정을 고려한 전략 수립
- **포트폴리오 대시보드**: 실시간 포트폴리오 현황 및 성과 모니터링
- **백테스팅 엔진**: 과거 데이터를 활용한 전략 검증
- **리스크 관리**: 자동 손절/익절 기능

## 🛠 기술 스택

- **Backend**: Python, FastAPI
- **Database**: PostgreSQL
- **AI/ML**: LangGraph, OpenAI
- **Trading API**: 한국투자증권 OpenAPI
- **Infrastructure**: Docker, Docker Compose

## 📁 프로젝트 구조

```
market-auto-trader/
├── README.md                    # 프로젝트 소개
├── LICENSE                      # 라이선스
├── .gitignore                   # Git 제외 파일
├── .env.example                 # 환경변수 템플릿
├── docker-compose.yml           # Docker 구성
├── Dockerfile                   # 앱 컨테이너
├── requirements.txt             # Python 의존성
├── AGENTS.md                    # AI 에이전트 가이드
├── config/
│   └── settings.py              # 앱 설정 관리
├── src/
│   ├── main.py                  # FastAPI 앱 엔트리포인트
│   ├── api/                     # API 라우터
│   ├── broker/                  # 증권사 API 클라이언트
│   ├── data/                    # 데이터 수집기
│   ├── strategy/                # 매매 전략
│   ├── models/                  # 데이터베이스 모델
│   └── utils/                   # 유틸리티
├── tests/                       # 테스트 코드
└── docs/                        # 문서
```

## 🚀 설치 및 실행

### 1. 환경 설정

```bash
# 저장소 클론
git clone https://github.com/lunara-kim/market-auto-trader.git
cd market-auto-trader

# 환경변수 설정
cp .env.example .env
# .env 파일을 열어 실제 API 키 등을 입력하세요
```

### 2. Docker로 실행

```bash
# Docker Compose로 실행 (PostgreSQL + 앱)
docker-compose up -d

# 로그 확인
docker-compose logs -f app
```

### 3. 개발 모드 실행

```bash
# Python 가상환경 생성 및 활성화
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 앱 실행
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. API 확인

- Health Check: http://localhost:8000/health
- API 문서: http://localhost:8000/docs

## 📝 개발 로드맵

### Phase 0: 프로젝트 초기 세팅 ✅
- 기본 프로젝트 구조
- Docker 환경 구성
- FastAPI 기본 엔드포인트

### Phase 1: 데이터 수집 (진행 예정)
- 한국투자증권 API 연동
- 실시간 시세 데이터 수집
- 데이터베이스 스키마 구축

### Phase 2: 전략 엔진
- 기본 매매 전략 구현
- 백테스팅 프레임워크
- 시그널 생성 로직

### Phase 3: AI 에이전트
- LangGraph 멀티 에이전트 시스템
- 시장 분석 에이전트
- 리스크 관리 에이전트

### Phase 4: 자동 거래
- 주문 실행 시스템
- 포지션 관리
- 리스크 관리 (손절/익절)

### Phase 5: 대시보드
- 포트폴리오 현황 시각화
- 거래 내역 조회
- 성과 분석

### Phase 6: 프로덕션 준비
- 모니터링 및 알림
- 로깅 및 에러 추적
- 보안 강화

## ⚠️ 주의사항

- 이 프로젝트는 **교육 및 연구 목적**으로 개발되었습니다.
- 실제 투자에 사용하기 전에 충분한 테스트와 검증이 필요합니다.
- 투자로 인한 손실은 사용자 본인의 책임입니다.
- 한국투자증권 API 사용 시 약관을 준수해야 합니다.

## 📄 라이선스

MIT License - 자세한 내용은 [LICENSE](LICENSE) 파일을 참고하세요.

## 🤝 기여

이슈 제기 및 풀 리퀘스트는 언제나 환영합니다!

## 📧 문의

프로젝트와 관련된 문의사항은 GitHub Issues를 통해 남겨주세요.
