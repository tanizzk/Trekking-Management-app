
import redis
from flask_sqlalchemy import SQLAlchemy

from config import Config

db = SQLAlchemy()



redis_client = redis.Redis(
    host=Config.REDIS_HOST,
    port=Config.REDIS_PORT,
    db=Config.REDIS_CACHE_DB,
    decode_responses=True,
)