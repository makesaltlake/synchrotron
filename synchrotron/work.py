
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
from synchrotron.util import redis_connection
import json

InviteStatus = enum.Enum('InviteStatus', 'already_invited already_in_team successful')
Report = namedtuple('Report', [
  'total_count',
  'current_ongoing_count',
  'past_due_members',
  'pending_cancellation_members',
  'per_month_average',
  'per_month_average_before_fees',
  'per_month_baseline',
])

stripe_event_processors = {}


def stripe_event_processor(event_type):
  def decorator(function):
    stripe_event_processors[event_type] = function
    return function
  return decorator


class SynchrotronWorker:
  def __init__(self):
    self.slack = slackclient.SlackClient(os.getenv('SLACK_TOKEN'))
    self.slack_channel = os.getenv('SLACK_CHANNEL')
    self.stripe_key = os.getenv('STRIPE_SECRET_KEY')

  def setup(self):
    stripe.api_key = self.stripe_key

  def run(self):
    self.setup()

    r = redis_connection()

    p = r.pubsub(ignore_subscribe_messages=True)
    p.subscribe('trigger', 'sync', 'report', 'stripe_event')

    for message in p.listen():
      if message['channel'] == 'trigger':
        self.trigger(message['data'])
      elif message['channel'] == 'report':
        self.report()
      elif message['channel'] == 'stripe_event':
        self.process_stripe_event(message['data'])

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
    total_count = 0
    current_ongoing_count = 0
    past_due_members = []
    pending_cancellation_members = []
    per_month_average = 0.0
    per_month_average_before_fees = 0.0
    per_month_baseline = 0.0

    for subscription in stripe.Subscription.list(expand=['data.customer']).auto_paging_iter():
      total_count += 1
      if subscription.status in ('active', 'trialing'):
        if subscription.plan.interval != 'month':
          raise RuntimeError('wtf')
        if subscription.cancel_at_period_end:
          pending_cancellation_members.append(self.summarize_customer(subscription.customer))
        else:
          current_ongoing_count += 1
          amount_after_transaction_fees = subscription.plan.amount * (1 - 0.029) - 0.3
          per_month_average += amount_after_transaction_fees / subscription.plan.interval_count
          per_month_average_before_fees += subscription.plan.amount / subscription.plan.interval_count
          if subscription.plan.interval_count == 1:
            per_month_baseline += amount_after_transaction_fees
      else:
        past_due_members.append(self.summarize_customer(subscription.customer))

    return Report(
      total_count=total_count,
      current_ongoing_count=current_ongoing_count,
      past_due_members=past_due_members,
      pending_cancellation_members=pending_cancellation_members,
      per_month_average=round(per_month_average / 100, 2),
      per_month_average_before_fees=round(per_month_average_before_fees / 100, 2),
      per_month_baseline=round(per_month_baseline / 100, 2)
    )

  def create_report_attachments(self):
    report = self.create_report()

    subscription_fields = [
      {'title': 'Total subscriptions', 'value': str(report.total_count), 'short': True},
      {'title': 'Current, ongoing subscriptions', 'value': str(report.current_ongoing_count), 'short': True},
      {'title': 'Past due subscriptions', 'value': str(len(report.past_due_members)), 'short': True},
      {'title': 'Subscriptions pending cancellation', 'value': str(len(report.pending_cancellation_members)), 'short': True}
    ]
    projection_fields = [
      {'title': 'Monthly average before Stripe fees', 'value': '$%.2f' % report.per_month_average_before_fees, 'short': True},
      {'title': 'Monthly average after Stripe fees', 'value': '$%.2f' % report.per_month_average, 'short': True},
      {'title': 'Monthly baseline after Stripe fees', 'value': '$%.2f' % report.per_month_baseline}
    ]

    attachments = [
      {
        'pretext': 'Subscription stats:',
        'fields': subscription_fields
      },
      {
        'pretext': 'Income projections for current, ongoing subscriptions:',
        'fields': projection_fields
      }
    ]

    if report.past_due_members:
      attachments.append({
        'pretext': 'Members with past due subscriptions:',
        'text': '\n'.join(report.past_due_members)
      })

    return attachments

  def report(self):
    self.send_slack_message(attachments=self.create_report_attachments())

  def process_stripe_event(self, data):
    event = json.loads(data)
    if event['type'] in stripe_event_processors:
      stripe_event_processors[event['type']].__get__(self, type(self))(event)

  @stripe_event_processor('customer.subscription.created')
  def process_customer_subscription_created(self, event):
    self.send_slack_message(
      text='New member: %s' % self.summarize_customer(event['data']['object']['customer']),
      attachments=self.create_report_attachments()
    )

  @stripe_event_processor('customer.subscription.deleted')
  def process_customer_subscription_deleted(self, event):
    self.send_slack_message(
      text="%s's subscription has been cancelled." % self.summarize_customer(event['data']['object']['customer']),
      attachments=self.create_report_attachments()
    )

  @stripe_event_processor('customer.subscription.updated')
  def process_customer_subscription_updated(self, event):
    cancel_at_period_end = event['data']['object']['cancel_at_period_end']
    if cancel_at_period_end != event['data']['previous_attributes']['cancel_at_period_end']:
      if cancel_at_period_end:
        self.send_slack_message(
          text="%s's subscription will be cancelled on %s" % (
            self.summarize_customer(event['data']['object']['customer']),
            self.month_and_day(event['data']['object']['current_period_end'])
          ),
          attachments=self.create_report_attachments()
        )
      else:
        self.send_slack_message(
          text="%s's subscription will no longer be cancelled." % self.summarize_customer(event['data']['object']['customer']),
          attachments=self.create_report_attachments()
        )

  @stripe_event_processor('invoice.payment_failed')
  def process_invoice_payment_failed(self, event):
    self.send_slack_message(
      text="%s's payment failed :alert:" % self.summarize_customer(event['data']['object']['customer']),
      attachments=self.create_report_attachments()
    )

  @stripe_event_processor('charge.dispute.created')
  def process_charge_dispute_created(self, event):
    self.send_slack_message(
      text=":beaker: A charge has been disputed :alert2:"
    )

  def summarize_customer(self, customer):
    # Fetch the customer if we were given an id
    if isinstance(customer, str):
      try:
        customer = stripe.Customer.retrieve(customer)
      except stripe.error.InvalidRequestError:
        # probably a webhook test or something, in which case we get a customer id that doesn't actually exist
        return customer

    # Paid Memberships Pro creates customer descriptions of the form "name (email)" while MemberPress just sets them
    # to "name". Detect the former and avoid duplicating the email address.
    if customer.email in customer.description:
      return customer.description
    else:
      return '%s (%s)' % (customer.description, customer.email)

  def month_and_day(self, epoch_time):
    # strftime on Windows doesn't support the - in %-d. Might want to format this a different way...
    return time.strftime('%B %-d', time.gmtime(epoch_time))

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
