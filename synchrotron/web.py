
import flask
from flask import request, abort
import os
import re
from synchrotron.util import redis_connection, setup_stripe
import json
import stripe
import io
import csv
from datetime import datetime

setup_stripe()
app = flask.Flask('synchrotron')


@app.route('/')
def index():
  return 'ohai'


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
  check_token(request.args['token'], 'REPORT_TOKEN')

  events = []
  for subscription in stripe.Subscription.list(status='all', limit=100).auto_paging_iter():
    events.append((datetime.utcfromtimestamp(subscription.start), 1))
    if subscription.ended_at:
      events.append((datetime.utcfromtimestamp(subscription.ended_at), -1))

  events.sort()

  output = io.StringIO()
  writer = csv.writer(output)
  writer.writerow(['Date', 'Membership Change'])

  for date, membership_change in events:
    writer.writerow([date.strftime('%Y-%m-%d %H:%M:%S'), membership_change])

  return flask.Response(output.getvalue(), mimetype='text/csv')


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
