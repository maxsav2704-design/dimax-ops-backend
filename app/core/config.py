from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )
    DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@db:5432/dimax"
    JWT_SECRET: str = "change-me"
    JWT_ISSUER: str = "dimax"
    JWT_ACCESS_TTL_MIN: int = 30
    JWT_REFRESH_TTL_DAYS: int = 30
    PLATFORM_API_TOKEN: str = ""

    SEED_COMPANY_NAME: str = "DIMAX GROUP"
    SEED_ADMIN_EMAIL: str = "admin@dimax.local"
    SEED_ADMIN_PASSWORD: str = "secret123"
    SEED_ADMIN_FULL_NAME: str = "Admin DIMAX"

    PUBLIC_BASE_URL: str = "http://localhost:8000"
    CORS_ALLOW_ORIGINS: str = (
        "http://localhost:5173,"
        "http://127.0.0.1:5173,"
        "http://localhost:4173,"
        "http://127.0.0.1:4173"
    )

    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 25
    SMTP_TLS: bool = False
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@dimax.local"
    EMAIL_ENABLED: bool = True

    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = ""
    TWILIO_STATUS_CALLBACK_URL: str = ""
    TWILIO_WEBHOOK_VALIDATE: bool = False
    TWILIO_WEBHOOK_AUTH_TOKEN: str = ""
    OUTBOX_WEBHOOK_TOKEN: str = ""
    OUTBOX_DELIVERY_RISK_AUTO_ISSUE_ENABLED: bool = True
    OUTBOX_DELIVERY_RISK_MIN_FAILED: int = 1
    OUTBOX_DELIVERY_RISK_WINDOW_HOURS: int = 72
    WHATSAPP_ENABLED: bool = True
    WHATSAPP_FALLBACK_TO_EMAIL: bool = True

    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "dimax"
    MINIO_SECURE: bool = False
    MINIO_PRESIGN_EXPIRY_SEC: int = 86400

    FILE_TOKEN_TTL_SEC: int = 3600
    FILE_TOKEN_USES: int = 1
    JOURNAL_PUBLIC_TOKEN_TTL_SEC: int = 2592000

    SYNC_GC_SAFETY_LAG: int = 2000
    SYNC_GC_BATCH_LIMIT: int = 200000
    SYNC_ACTIVE_DAYS: int = 30

    SYNC_WARN_LAG: int = 2000
    SYNC_DANGER_LAG: int = 5000
    SYNC_WARN_DAYS_OFFLINE: int = 3
    SYNC_DANGER_DAYS_OFFLINE: int = 7
    SYNC_ALERT_COOLDOWN_MINUTES: int = 360  # 6 hours
    SYNC_ALERT_WEBHOOK_URL: str | None = None

    SYNC_PROJECT_AUTO_PROBLEM_ENABLED: bool = False
    SYNC_PROJECT_AUTO_PROBLEM_DAYS: int = 7
    PLAN_ALERT_WEBHOOK_URL: str | None = None
    PLAN_ALERT_WARN_PCT: int = 80
    PLAN_ALERT_DANGER_PCT: int = 95
    PLAN_ALERT_COOLDOWN_MINUTES: int = 360

    PUBLIC_FILES_RL_WINDOW_SEC: int = 60
    PUBLIC_FILES_RL_MAX_REQ: int = 30
    AUTH_LOGIN_RL_WINDOW_SEC: int = 60
    AUTH_LOGIN_RL_MAX_REQ: int = 60
    AUTH_REFRESH_RL_WINDOW_SEC: int = 60
    AUTH_REFRESH_RL_MAX_REQ: int = 120

    WAZE_BASE_URL: str = "https://waze.com/ul"
    WAZE_NAVIGATION_ENABLED: bool = True


settings = Settings()
