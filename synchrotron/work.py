
import redis
import os


class SynchrotronWorker:
  def __init__(self):
    pass

  def run(self):
    r = redis.Redis.from_url(os.getenv('REDIS_URL'))

    p = db.pubsub(ignore_subscribe_messages=True)
    p.subscribe('trigger')

    # fire off initial sync
    sync()

    # then listen for requests to sync again
    for message in p.listen():
      # drain additional messages in case we've been asked to sync multiple times
      while p.get_message():
        pass
      # then sync
      sync()

  def sync(self):
    pass


if __name__ == '__main__':
  SynchrotronWorker().run()
