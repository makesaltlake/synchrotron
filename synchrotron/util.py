
import redis
import os

def redis_connection():
  # TODO: Make this a context manager that disconnects eagerly
  return redis.Redis.from_url(os.getenv('REDIS_URL'), charset='utf-8', decode_responses=True)
