
import flask
from flask import request, abort
import redis
import os
import re

app = flask.Flask('synchrotron')


@app.route('/')
def index():
  return 'ohai'


@app.route('/trigger', methods=['POST'])
def trigger():
  params = {**request.args, **request.form}
  print('params are %s, form is %s, and args are %s' % (params, request.form, request.args))

  token = params['token']
  required_token = os.getenv('TRIGGER_TOKEN')
  if required_token is None or token != required_token:
    abort(403)

  address = parse_email(params['body'])
  if address is None:
    print('no email address extracted')
    return 'no email address extracted.'

  # TODO: disconnect eagerly
  r = redis.Redis.from_url(os.getenv('REDIS_URL'))
  r.publish('trigger', address)

  print('triggered %s' % address)
  return 'successful.'


def parse_email(body):
  if 'subscription was just created on' not in body:
    return

  match = re.search('Email:\s*([^\s]+)', body)
  if match is None:
    return

  return match.group(1)
