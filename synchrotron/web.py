
import flask
from flask import request, abort
import os
import re
from synchrotron.util import redis_connection, setup_stripe, summarize_stripe_customer
import json
import stripe
import io
import csv
from datetime import datetime, timedelta


# hacky cache for the membership report delta - since we're now timing out computing it live every time. it'll be moved
# into synchrotron3 soon, so no sense doing proper caching here.
membership_delta_cache_date = datetime.utcfromtimestamp(0)
membership_delta_cache_data = None

MEMBERSHIP_DELTA_CACHE_DAYS = 3


setup_stripe()
app = flask.Flask('synchrotron')


@app.route('/')
def index():
  return 'ohai'


@app.route('/robots.txt')
def robots():
  return "User-agent: *\nDisallow: /\n"


@app.route('/trigger', methods=['POST'])
def trigger():
  check_token(request.form['token'], 'TRIGGER_TOKEN')

  address = parse_email(request.form['body'])
  if address is None:
    print('no email address extracted')
    return 'no email address extracted.'

  redis_connection().publish('trigger', address)

  print('triggered %s' % address)
  return 'successful.'


@app.route('/stripe/webhook', methods=['POST'])
def stripe_webhook():
  check_token(request.args['token'], 'TRIGGER_TOKEN')

  redis_connection().publish('stripe_event', json.dumps(request.json))

  return 'ok'


@app.route('/reports/membership_delta')
def membership_delta_report():
  global membership_delta_cache_date
  global membership_delta_cache_data

  check_token(request.args['token'], 'REPORT_TOKEN')

  if membership_delta_cache_date + timedelta(days=MEMBERSHIP_DELTA_CACHE_DAYS) < datetime.utcnow():
    print('recomputing membership delta report')

    include_customers = os.getenv('MEMBERSHIP_REPORTS_INCLUDE_CUSTOMERS') == '1'

    events = []
    for subscription in stripe.Subscription.list(status='all', limit=100, expand=['data.customer']).auto_paging_iter():
      # subscription id is present to break ties between events with the same date
      events.append((datetime.utcfromtimestamp(subscription.start), subscription.id, 1, subscription.customer))
      if subscription.ended_at:
        events.append((datetime.utcfromtimestamp(subscription.ended_at), subscription.id, -1, subscription.customer))

    events.sort()

    output = io.StringIO()
    writer = csv.writer(output)
    if include_customers:
      writer.writerow(['Date', 'Membership Change', 'Description'])
    else:
      writer.writerow(['Date', 'Membership Change'])

    for date, _, membership_change, customer in events:
      if include_customers:
        writer.writerow([date.strftime('%Y-%m-%d %H:%M:%S'), membership_change, summarize_stripe_customer(customer)])
      else:
        writer.writerow([date.strftime('%Y-%m-%d %H:%M:%S'), membership_change])

    membership_delta_cache_data = output.getvalue()
    membership_delta_cache_date = datetime.utcnow()
  else:
    print('using cached membership delta report')

  return flask.Response(membership_delta_cache_data, mimetype='text/csv')


def check_token(token_value, token_env_var_name):
  required_token = os.getenv(token_env_var_name)
  if required_token is None or token_value != required_token:
    abort(403)


def parse_email(body):
  if 'subscription was just created on' not in body:
    return

  match = re.search('Email:\s*([^\s]+)', body)
  if match is None:
    return

  return match.group(1)
