"""
애플리케이션 설정 관리

pydantic-settings를 사용하여 환경변수 기반 설정을 관리합니다.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """애플리케이션 설정"""
    
    # 한국투자증권 API 설정
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""
    kis_mock: bool = True
    
    # 데이터베이스 설정
    database_url: str = "postgresql://trader:trader@localhost:5432/market_trader"
    
    # OpenAI 설정
    openai_api_key: Optional[str] = None
    
    # 앱 설정
    app_env: str = "development"
    log_level: str = "INFO"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )


# 전역 설정 인스턴스
settings = Settings()
