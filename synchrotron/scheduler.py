
from apscheduler.schedulers.blocking import BlockingScheduler
import os
from synchrotron.util import redis_connection

scheduler = BlockingScheduler()


@scheduler.scheduled_job('cron', hour=3, timezone='America/Denver')
def trigger_report():
    redis_connection().publish('report', '')


if __name__ == '__main__':
  scheduler.start()