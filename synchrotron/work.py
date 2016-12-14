
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
from collections import namedtuple

InviteStatus = enum.Enum('InviteStatus', 'already_invited already_in_team successful')
Report = namedtuple('Report', [
  'count',
  'per_month_average',
  'per_month_average_before_fees',
  'per_month_min',
  'per_month_max',
  'past_due_count'
])


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

  def create_report(self):
    count = 0
    per_month_average = 0.0
    per_month_average_before_fees = 0.0
    per_month_min = 0.0
    per_month_max = 0.0
    past_due_count = 0

    for subscription in stripe.Subscription.list().auto_paging_iter():
      count += 1
      if subscription.status in ('active', 'trialing'):
        if subscription.plan.interval != 'month':
          raise RuntimeError('wtf')
        amount_after_transaction_fees = subscription.plan.amount * (1 - 0.029) - 0.3
        per_month_average += amount_after_transaction_fees / subscription.plan.interval_count
        per_month_average_before_fees += subscription.plan.amount / subscription.plan.interval_count
        per_month_max += amount_after_transaction_fees
        if subscription.plan.interval_count == 1:
          per_month_min += amount_after_transaction_fees
      else:
        past_due_count += 1

    return Report(
      count,
      round(per_month_average / 100, 2),
      round(per_month_average_before_fees / 100, 2),
      round(per_month_min / 100, 2),
      round(per_month_max / 100, 2),
      past_due_count
    )

  def report(self):
    report = self.create_report()

    fields = [
      {'title': 'Paid memberships', 'value': str(report.count)},
      {'title': 'Monthly average before Stripe fees', 'value': '$%.2f' % report.per_month_average_before_fees, 'short': True},
      {'title': 'Monthly average after Stripe fees', 'value': '$%.2f' % report.per_month_average, 'short': True},
      {'title': 'Min', 'value': '$%.2f' % report.per_month_min, 'short': True},
      {'title': 'Max', 'value': '$%.2f' % report.per_month_max, 'short': True}
    ]

    if report.past_due_count > 0:
      fields.append({'title': 'Past due memberships', 'value': str(report.past_due_count)})

    self.send_slack_message(attachments=[{'fields': fields}])

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

  def send_slack_message(self, **params):
    self.slack.api_call('chat.postMessage', **{'channel': self.slack_channel, 'as_user': True, **params})


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
