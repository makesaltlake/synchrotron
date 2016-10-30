
import redis
import os
import time
import slackclient


class SynchrotronWorker:
  def __init__(self):
    self.slack = slackclient.SlackClient(os.getenv('SLACK_TOKEN'))
    self.slack_channel = os.getenv('SLACK_CHANNEL')

  def run(self):
    r = redis.Redis.from_url(os.getenv('REDIS_URL'))

    p = r.pubsub(ignore_subscribe_messages=True)
    p.subscribe('trigger', 'sync')

    # fire off initial sync
    self.sync()

    # then listen for requests
    for message in p.listen():
      if p['channel'] == 'sync':
        # TODO: ignore multiple sync messages all sent in short order
        self.sync()
      elif p['channel'] == 'trigger':
        self.trigger(p['data'])

  def sync(self):
    print('sync at %s' % time.ctime())

  def trigger(self, address):
    self.send_slack_message(':wave:')

  def send_slack_message(self, message):
    self.slack.api_call('chat.postMessage', channel=self.slack_channel, text=message, as_user=True)


def retry(function, retries=3):
  for i in range(retries):
    try:
      result = function()
    except Exception:
      if i == retries - 1:
        raise
    else:
      return result


if __name__ == '__main__':
  SynchrotronWorker().run()
