import os
import json
from pathlib import Path
from dotenv import load_dotenv

# 로컬 환경인 경우 .env 로드 (override=True를 설정하여 시스템 환경 변수보다 .env 파일 우선 적용)
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
else:
    load_dotenv()  # 시스템 환경 변수 로드 백업

class Config:
    # System configs
    RUN_MODE = os.getenv("RUN_MODE", "local").lower()
    PORT = int(os.getenv("PORT", 8000))
    SECRET_KEY = os.getenv("SECRET_KEY", "auto-car-blog-secret")

    # API Keys
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    JINA_API_KEY = os.getenv("JINA_API_KEY")

    # Telegram configs
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    TELEGRAM_WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL")

    # Tistory configs
    TISTORY_ACCESS_TOKEN = os.getenv("TISTORY_ACCESS_TOKEN")
    TISTORY_BLOG_NAME = os.getenv("TISTORY_BLOG_NAME")

    # WordPress configs
    WORDPRESS_URL = os.getenv("WORDPRESS_URL")
    WORDPRESS_USERNAME = os.getenv("WORDPRESS_USERNAME")
    WORDPRESS_APPLICATION_PASSWORD = os.getenv("WORDPRESS_APPLICATION_PASSWORD")

    # Google Sheets credentials config
    GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
    GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH")
    GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")

    # Firebase Firestore credentials config
    FIREBASE_CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH")
    FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON") or os.getenv("FIREBASE_SERVICE_ACCOUNT")

    # Vercel Upstash Configs
    UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL")
    UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
    QSTASH_TOKEN = os.getenv("QSTASH_TOKEN")

    # Google OAuth 2.0 Web Client Configs
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    @classmethod
    def get_google_sheets_credentials(cls):
        """Google Sheets 크레덴셜 정보를 딕셔너리 혹은 파일 경로 형태로 반환합니다."""
        if cls.GOOGLE_SHEETS_CREDENTIALS_JSON:
            try:
                return json.loads(cls.GOOGLE_SHEETS_CREDENTIALS_JSON)
            except Exception as e:
                print(f"Error parsing GOOGLE_SHEETS_CREDENTIALS_JSON: {e}")
        
        # 파이어베이스 서비스 계정 정보를 구글 시트/드라이브 자격증명으로 재활용 (이메일 및 키가 동일하므로 프로젝트 통합 가능)
        if cls.FIREBASE_CREDENTIALS_JSON:
            try:
                return json.loads(cls.FIREBASE_CREDENTIALS_JSON)
            except Exception as e:
                print(f"Error parsing FIREBASE_CREDENTIALS_JSON as Google Sheets credentials: {e}")

        if cls.GOOGLE_SHEETS_CREDENTIALS_PATH and os.path.exists(cls.GOOGLE_SHEETS_CREDENTIALS_PATH):
            try:
                with open(cls.GOOGLE_SHEETS_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error reading GOOGLE_SHEETS_CREDENTIALS_PATH: {e}")
        
        return None

    @classmethod
    def get_firebase_credentials(cls):
        """Firebase 크레덴셜 정보를 딕셔너리 혹은 파일 경로 형태로 반환합니다."""
        if cls.FIREBASE_CREDENTIALS_JSON:
            try:
                return json.loads(cls.FIREBASE_CREDENTIALS_JSON)
            except Exception as e:
                print(f"Error parsing FIREBASE_CREDENTIALS_JSON: {e}")
        
        if cls.FIREBASE_CREDENTIALS_PATH and os.path.exists(cls.FIREBASE_CREDENTIALS_PATH):
            try:
                with open(cls.FIREBASE_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error reading FIREBASE_CREDENTIALS_PATH: {e}")
        
        return None

    @classmethod
    def validate(cls):
        """필수 환경 변수 존재 여부를 체크하고 로그를 출력합니다."""
        missing = []
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if not cls.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        
        if missing:
            print(f"[WARN] 필수 환경 변수가 누락되었습니다: {', '.join(missing)}")
            print("[WARN] 파이프라인의 일부 기능이 작동하지 않을 수 있습니다.")
        else:
            print("[INFO] 기본 환경 변수 로드 완료.")
