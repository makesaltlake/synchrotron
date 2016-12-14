
from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()


@scheduler.scheduled_job('cron', hour=3, timezone='America/Denver')
def trigger_report():
    r = redis.Redis.from_url(os.getenv('REDIS_URL'), charset='utf-8', decode_responses=True)
    r.publish('report')


if __name__ == '__main__':
  scheduler.start()