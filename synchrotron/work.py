
import redis
import os
import time
import slackclient
from contextlib import contextmanager
import requests
import xmlrpc.client
from urllib.parse import urljoin
import enum

InviteStatus = enum.Enum('InviteStatus', 'already_invited already_in_team successful')


class SynchrotronWorker:
  def __init__(self):
    self.slack = slackclient.SlackClient(os.getenv('SLACK_TOKEN'))
    self.slack_channel = os.getenv('SLACK_CHANNEL')
    self.wordpress_url = os.getenv('WP_URL')
    self.wordpress_username = os.getenv('WP_USERNAME')
    self.wordpress_password = os.getenv('WP_PASSWORD')
    self.wordpress_client = xmlrpc.client.ServerProxy(urljoin(self.wordpress_url, 'xmlrpc.php'), allow_none=True)

  @contextmanager
  def setup_wordpress_session(self):
    print('Logging into WordPress...')

    with requests.Session() as session:
      session.headers['Referer'] = self.wordpress_url
      retry(lambda: session.post(urljoin(self.wordpress_url, 'wp-login.php'), data={'log': self.wordpress_username, 'pwd': self.wordpress_password}, timeout=30).raise_for_status())

      self.wordpress_session = session
      print('Logged in.')

      yield

  def run(self):
    r = redis.Redis.from_url(os.getenv('REDIS_URL'), charset='utf-8', decode_responses=True)

    p = r.pubsub(ignore_subscribe_messages=True)
    p.subscribe('trigger', 'sync')

    # fire off initial sync
    self.sync()

    # then listen for requests
    for first_message in p.listen():
      # grab all other messages in line so that we can collapse duplicate sync messages
      messages = [first_message]
      m = p.get_message()
      while m:
        messages.append(m)
        m = p.get_message()

      handled_sync = False

      with self.setup_wordpress_session():
        for message in messages:
          if message['channel'] == 'sync':
            if handled_sync:
              continue
            handled_sync = True
            self.sync()
          elif message['channel'] == 'trigger':
            self.trigger(message['data'])

  def sync(self):
    print('sync at %s' % time.ctime())

  def trigger(self, address):
    user = self.get_wordpress_user_by(email=address)
    if user is None:
      self.send_slack_message("MemberPress told me there's a new user with address %r but WordPress doesn't seem to know about it" % address)
      return

    invite_status = self.invite_to_slack(user)
    invite_observation = {
      InviteStatus.successful: 'Slack invitation sent.',
      InviteStatus.already_invited: 'This person has already received a Slack invitation',
      InviteStatus.already_in_team: 'This person is already a member of the Slack team.'
    }.get(invite_status, 'Slack invitation failed with error %r.' % invite_status)

    self.send_slack_message('New member: %s %s (%s). %s' % (user['first_name'], user['last_name'], user['email'], invite_observation))

  def invite_to_slack(self, user):
    response = self.slack.api_call('users.admin.invite', email=user['email'], first_name=user['first_name'], last_name=user['last_name'], set_active=True)
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

  def get_wordpress_users(self):
    users = retry(lambda: self.wordpress_client.wp.getUsers(1, self.wordpress_username, self.wordpress_password, {'number': 10000}))
    if len(users) >= 10000:
      raise Exception('Congratulations, you have 10,000 users! You should probably go add proper '
                      'pagination support to Synchrotron.')
    return users

  def get_wordpress_user_by(self, **criteria):
    # plz to expose get_user_by via the XML-RPC API...
    users = self.get_wordpress_users()
    for user in users:
      if all(user[k] == criteria[k] for k in criteria):
        return user
    return None

def retry(function, retries=3):
  for i in range(retries):
    try:
      result = function()
    except Exception:
      if i == retries - 1:
        print('try %s failed, bailing' % (i + 1))
        raise
      else:
        print('try %s failed, retrying...' % (i + 1))
    else:
      return result


if __name__ == '__main__':
  SynchrotronWorker().run()
