
import redis
import os
import stripe

def redis_connection():
  # TODO: Make this a context manager that disconnects eagerly
  return redis.Redis.from_url(os.getenv('REDIS_URL'), charset='utf-8', decode_responses=True)


def setup_stripe():
  stripe.api_version = '2016-10-19'
  stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
