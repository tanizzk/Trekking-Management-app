import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # --- Core Flask ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")

    # --- Database (SQLite, created programmatically by SQLAlchemy) ---
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'trekking.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Redis (cache) ---
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
    REDIS_CACHE_DB = int(os.environ.get("REDIS_CACHE_DB", 0))

    # --- Celery (broker + result backend, separate Redis DBs) ---
    CELERY_BROKER_URL = os.environ.get(
        "CELERY_BROKER_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/1"
    )
    CELERY_RESULT_BACKEND = os.environ.get(
        "CELERY_RESULT_BACKEND", f"redis://{REDIS_HOST}:{REDIS_PORT}/2"
    )

    # --- JWT ---
    JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", 12))

    # --- Cache TTL for open treks listing ---
    TREKS_CACHE_TTL_SECONDS = int(os.environ.get("TREKS_CACHE_TTL_SECONDS", 60))

    # --- Seeded admin (single pre-existing admin, no admin self-registration) ---
    ADMIN_NAME = os.environ.get("ADMIN_NAME", "System Administrator")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@trekmanager.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Admin@123")