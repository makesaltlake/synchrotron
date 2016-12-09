
import redis
import os
import time
import slackclient
from contextlib import contextmanager
import requests
import xmlrpc.client
from urllib.parse import urljoin
import enum
import stripe

InviteStatus = enum.Enum('InviteStatus', 'already_invited already_in_team successful')
BASELINE_SUBSCRIPTION = 50


class SynchrotronWorker:
  def __init__(self):
    self.slack = slackclient.SlackClient(os.getenv('SLACK_TOKEN'))
    self.slack_channel = os.getenv('SLACK_CHANNEL')
    self.stripe_key = os.getenv('STRIPE_SECRET_KEY')

  def setup(self):
    stripe.api_key = self.stripe_key

  def run(self):
    self.setup()

    r = redis.Redis.from_url(os.getenv('REDIS_URL'), charset='utf-8', decode_responses=True)

    p = r.pubsub(ignore_subscribe_messages=True)
    p.subscribe('trigger', 'sync')

    for message in p.listen():
      if message['channel'] == 'trigger':
        self.trigger(message['data'])
      elif message['channel'] == 'report':
        self.report()

  def trigger(self, address):
    # invite_status = self.invite_to_slack(address)
    # invite_observation = {
    #   InviteStatus.successful: 'Slack invitation sent.',
    #   InviteStatus.already_invited: 'This person has already received a Slack invitation',
    #   InviteStatus.already_in_team: 'This person is already a member of the Slack team.'
    # }.get(invite_status, 'Slack invitation failed with error %r.' % invite_status)
    invite_observation = 'Automatic slack invites for new members are disabled right now.'

    self.send_slack_message('New member: %s. %s' % (address, invite_observation))

  def report(self):
    count = 0
    per_month = 0.0
    weird = 0

    for subscription in stripe.Subscription.list().auto_paging_iter():
      count += 1
      if subscription.status in ('active', 'trialing'):
        if subscription.plan.interval != 'month':
          raise RuntimeError('wtf')
        per_month += subscription.plan.amount / subscription.plan.interval_count
      else:
        weird += 1

    if weird > 0:
      weird_message = " %s subscriptions in a weird state (possibly the user's card was declined)." % weird
    else:
      weird_message = ''

    self.send_slack_message(":wave: %s subscriptions totaling $%.2f/month before Stripe transaction fees, equivalent to %.1f $%s/month memberships.%s" % (
      count,
      per_month / 100,
      per_month / 100 / BASELINE_SUBSCRIPTION,
      BASELINE_SUBSCRIPTION,
      weird_message
    ))

  def invite_to_slack(self, address):
    response = self.slack.api_call('users.admin.invite', email=address, set_active=True)
    if response['ok'] == True:
      return InviteStatus.successful
    elif response['error'] == 'already_invited':
      return InviteStatus.already_invited
    elif response['error'] == 'already_in_team':
      return InviteStatus.already_in_team
    else:
      return response['error']

  def send_slack_message(self, message):
    self.slack.api_call('chat.postMessage', channel=self.slack_channel, text=message, as_user=True)


def retry(function, retries=3):
  for i in range(retries):
    try:
      result = function()
    except Exception as e:
      if isinstance(e, requests.HTTPError) and e.response is not None:
        print('Request failed, body: %s' % e.response.text)

      if i == retries - 1:
        print('try %s failed, bailing' % (i + 1))
        raise
      else:
        print('try %s failed, retrying...' % (i + 1))
    else:
      return result


if __name__ == '__main__':
  SynchrotronWorker().run()
