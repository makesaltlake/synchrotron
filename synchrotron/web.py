
import flask
from flask import request
import redis
import os

app = flask.Flask('synchrotron')


@app.route('/')
def index():
  return 'ohai'


@app.route('/trigger', methods=['POST'])
def trigger():
  token = request.form['token']
  required_token = os.getenv('TRIGGER_TOKEN')
  if required_token is None or token != required_token:
    abort(403)

  # TODO: disconnect eagerly
  r = redis.Redis.from_url(os.getenv('REDIS_URL'))
  r.publish('trigger', 'go')
  return 'successful.'
