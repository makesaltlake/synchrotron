
import flask

app = flask.Flask('synchrotron')

@app.route('/')
def index():
  return 'ohai'

