"""
Settings (애플리케이션 설정) 테스트

환경변수 기반 설정의 기본값과 커스텀 값 적용을 검증합니다.
"""

from config.settings import Settings


class TestSettingsDefaults:
    """Settings 기본값 테스트"""

    def test_default_kis_mock_is_true(self):
        """기본 한투 API 모드가 모의투자(mock=True)인지 확인"""
        s = Settings(
            kis_app_key="",
            kis_app_secret="",
            kis_account_no="",
        )
        assert s.kis_mock is True

    def test_default_app_env(self):
        """기본 앱 환경이 development인지 확인"""
        s = Settings(
            kis_app_key="",
            kis_app_secret="",
            kis_account_no="",
        )
        assert s.app_env == "development"

    def test_default_log_level(self):
        """기본 로그 레벨이 INFO인지 확인"""
        s = Settings(
            kis_app_key="",
            kis_app_secret="",
            kis_account_no="",
        )
        assert s.log_level == "INFO"

    def test_default_database_url(self):
        """기본 데이터베이스 URL 형식 확인"""
        s = Settings(
            kis_app_key="",
            kis_app_secret="",
            kis_account_no="",
        )
        assert "postgresql://" in s.database_url

    def test_default_openai_api_key_is_none(self):
        """OpenAI API 키가 기본 None인지 확인"""
        s = Settings(
            kis_app_key="",
            kis_app_secret="",
            kis_account_no="",
        )
        assert s.openai_api_key is None


class TestSettingsCustom:
    """Settings 커스텀 값 테스트"""

    def test_custom_app_env(self):
        """커스텀 app_env 적용 확인"""
        s = Settings(
            kis_app_key="",
            kis_app_secret="",
            kis_account_no="",
            app_env="production",
        )
        assert s.app_env == "production"

    def test_custom_log_level(self):
        """커스텀 log_level 적용 확인"""
        s = Settings(
            kis_app_key="",
            kis_app_secret="",
            kis_account_no="",
            log_level="DEBUG",
        )
        assert s.log_level == "DEBUG"

    def test_kis_credentials(self):
        """한투 API 인증 정보가 올바르게 설정되는지 확인"""
        s = Settings(
            kis_app_key="my_key",
            kis_app_secret="my_secret",
            kis_account_no="12345678-01",
        )
        assert s.kis_app_key == "my_key"
        assert s.kis_app_secret == "my_secret"
        assert s.kis_account_no == "12345678-01"
