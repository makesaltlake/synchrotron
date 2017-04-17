
import redis
import os
import stripe

def redis_connection():
  # TODO: Make this a context manager that disconnects eagerly
  return redis.Redis.from_url(os.getenv('REDIS_URL'), charset='utf-8', decode_responses=True)


def setup_stripe():
  stripe.api_version = '2016-10-19'
  stripe.api_key = os.getenv('STRIPE_SECRET_KEY')


def summarize_stripe_customer(customer):
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
