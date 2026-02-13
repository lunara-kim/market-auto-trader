FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY alembic.ini /app/
COPY alembic/ /app/alembic/
COPY config/ /app/config/
COPY src/ /app/src/

# 환경변수 설정
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 포트 노출
EXPOSE 8000

# 마이그레이션 실행 후 앱 시작
CMD ["sh", "-c", "alembic upgrade head && uvicorn src.main:app --host 0.0.0.0 --port 8000"]
