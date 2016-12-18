
import flask
from flask import request, abort
import os
import re
from synchrotron.util import redis_connection
import json

app = flask.Flask('synchrotron')


@app.route('/')
def index():
  return 'ohai'


@app.route('/trigger', methods=['POST'])
def trigger():
  check_token(request.form['token'])

  address = parse_email(request.form['body'])
  if address is None:
    print('no email address extracted')
    return 'no email address extracted.'

  redis_connection().publish('trigger', address)

  print('triggered %s' % address)
  return 'successful.'


@app.route('/stripe/webhook', methods=['POST'])
def stripe_webhook():
  check_token(request.args['token'])

  redis_connection().publish('stripe_event', json.dumps(request.json))

  return 'ok'


def check_token(token):
  required_token = os.getenv('TRIGGER_TOKEN')
  if required_token is None or token != required_token:
    abort(403)


def parse_email(body):
  if 'subscription was just created on' not in body:
    return

  match = re.search('Email:\s*([^\s]+)', body)
  if match is None:
    return

  return match.group(1)
