"""
로깅 설정

JSON 포맷 로깅을 지원하며, 환경변수로 로그 레벨을 조정할 수 있습니다.
"""

import logging
import sys
import json
from datetime import datetime
from typing import Any
from config.settings import settings


class JSONFormatter(logging.Formatter):
    """JSON 포맷 로그 포매터"""
    
    def format(self, record: logging.LogRecord) -> str:
        """로그 레코드를 JSON 형식으로 변환"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # 예외 정보가 있으면 추가
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """
    로거 인스턴스 생성
    
    Args:
        name: 로거 이름 (보통 __name__ 사용)
    
    Returns:
        설정된 로거 인스턴스
    """
    logger = logging.getLogger(name)
    
    # 이미 핸들러가 설정되어 있으면 중복 방지
    if logger.handlers:
        return logger
    
    # 로그 레벨 설정
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # 콘솔 핸들러 설정
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    
    # JSON 포매터 적용 (프로덕션 환경)
    if settings.app_env == "production":
        formatter = JSONFormatter()
    else:
        # 개발 환경에서는 읽기 쉬운 포맷 사용
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger
