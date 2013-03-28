# Copyright 2012 Rackspace
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import string
import time

from nova.api.openstack import wsgi
from turnstile import config
from turnstile import limits
from turnstile import tools


class ParamsDict(dict):
    """
    Special dictionary for use with our URI formatter below.  Unknown
    keys default to '{key}'.
    """

    def __missing__(self, key):
        """
        If the key is unknown, return it surrounded by braces.
        """

        return '{%s}' % key


def nova_preprocess(midware, environ):
    """
    Pre-process requests to nova.  The tenant name is extracted from
    the nova context, and the applicable rate limit class is looked up
    in the database.  Both pieces of data are attached to the request
    environment.  This preprocessor must be present to use the
    NovaClassLimit rate limiting class.
    """

    # First, figure out the tenant
    context = environ.get('nova.context')
    if context:
        tenant = context.project_id
    else:
        # There *should* be a tenant by now, but let's be liberal
        # in what we accept
        tenant = '<NONE>'
    environ['turnstile.nova.tenant'] = tenant

    # Now, figure out the rate limit class
    klass = midware.db.get('limit-class:%s' % tenant) or 'default'
    klass = environ.setdefault('turnstile.nova.limitclass', klass)

    # Set up the nova quota class, if possible
    if (context and hasattr(context, 'quota_class') and
            context.quota_class is None):
        context.quota_class = klass

    # Tell Turnstile where to store the bucket keys
    bucket_set = 'bucket_set:%s' % tenant
    environ['turnstile.bucket_set'] = bucket_set

    # Trim off expired buckets...
    midware.db.zremrangebyscore(bucket_set, 0, time.time())


def nova_postprocess(midware, environ):
    """
    Post-process requests to nova.  This processes all the buckets
    associated with the rate limit class and inserts a nova-compatible
    representation into the environment.  This allows the nova /limits
    endpoint to report the rate limits and current usage.
    """

    # Get some handy information from the environment
    klass = environ['turnstile.nova.limitclass']
    bucket_set = environ['turnstile.bucket_set']

    # We may need a formatter later on, so set one up
    fmt = string.Formatter()

    # Grab a list of the available buckets and index them by UUID
    buckets = {}
    for key in midware.db.zrange(bucket_set, 0, -1):
        decoded_key = limits.BucketKey.decode(key)

        # Store the bucket key in the dictionary
        buckets.setdefault(decoded_key.uuid, [])
        buckets[decoded_key.uuid].append(decoded_key)

    # Finally, translate Turnstile limits into Nova limits, so we can
    # use Nova's /limits endpoint
    lims = []
    for turns_lim in midware.limits:
        # If the limit has a rate_class, ensure it equals the
        # appropriate one for the user.  If the limit does not have a
        # rate_class, we want to include it in the final list.
        if getattr(turns_lim, 'rate_class', klass) != klass:
            continue

        # Load up any available buckets
        buck_list = []
        for key in buckets.get(turns_lim.uuid, []):
            # Load the bucket and save it
            buck_list.append((ParamsDict(key.params), turns_lim.load(key)))

        # Account for queries for the uri...
        uri = turns_lim.uri
        if turns_lim.queries:
            uri = ('%s?%s' % (uri,
                              '&'.join('%s={%s}' % (qstr, qstr) for qstr in
                                       sorted(turns_lim.queries))))

        # Translate some information squirreled away in the limit
        verbs = turns_lim.verbs or ['GET', 'HEAD', 'POST', 'PUT', 'DELETE']
        unit = turns_lim.unit.upper()
        if unit.isdigit():
            unit = 'UNKNOWN'

        # Figure out remaining and resetTime
        if buck_list:
            remaining = min(bucket.messages for _params, bucket in buck_list)
            resetTime = max(bucket.expire for _params, bucket in buck_list)
        else:
            remaining = turns_lim.value
            resetTime = time.time()

        # Now, build a representation of the limit
        for verb in verbs:
            if len(buck_list) > 1:
                # Generate one entry for each bucket
                for params, bucket in buck_list:
                    # Substitute (some of) the values in params to
                    # make the URI more specific
                    buck_uri = fmt.vformat(uri, (), params)
                    lims.append(dict(
                        verb=verb,
                        URI=buck_uri,
                        regex=buck_uri,
                        value=turns_lim.value,
                        unit=unit,
                        remaining=bucket.messages,
                        resetTime=bucket.expire,
                    ))

            lims.append(dict(
                verb=verb,
                URI=uri,
                regex=uri,
                value=turns_lim.value,
                unit=unit,

                # These values are computed from the buckets...
                remaining=remaining,
                resetTime=resetTime,
            ))

    # Save the limits for Nova to use
    environ['nova.limits'] = lims


class NovaClassLimit(limits.Limit):
    """
    Rate limiting class for applying rate limits to classes of Nova
    tenants.  The nova_limits:nova_preprocess preprocessor must be
    configured for this limit class to match.
    """

    attrs = dict(
        rate_class=dict(
            desc=('The rate limiting class this limit applies to.  Required.'),
            type=str,
        ),
    )

    def route(self, uri, route_args):
        """
        Filter version identifiers off of the URI.
        """

        if uri.startswith('/v1.1/'):
            return uri[5:]
        elif uri.startswith('/v2/'):
            return uri[3:]

        return uri

    def filter(self, environ, params, unused):
        """
        Determines whether this limit applies to this request and
        attaches the tenant name to the params.
        """

        # Do we match?
        if ('turnstile.nova.tenant' not in environ or
                'turnstile.nova.limitclass' not in environ or
                self.rate_class != environ['turnstile.nova.limitclass']):
            raise limits.DeferLimit()

        # OK, add the tenant to the params
        params['tenant'] = environ['turnstile.nova.tenant']


def nova_formatter(status, delay, limit, bucket, environ, start_response):
    """
    Formats the over-limit response for the request.  This variant
    utilizes Nova's OverLimitFault for consistency with Nova's
    rate-limiting.
    """

    # Build the error message based on the limit's values
    args = dict(
        value=limit.value,
        verb=environ['REQUEST_METHOD'],
        uri=limit.uri,
        unit_string=limit.unit.upper(),
    )
    error = _("Only %(value)s %(verb)s request(s) can be "
              "made to %(uri)s every %(unit_string)s.") % args

    # Set up the rest of the arguments for wsgi.OverLimitFault
    msg = _("This request was rate-limited.")
    retry = time.time() + delay

    # Convert to a fault class
    fault = wsgi.OverLimitFault(msg, error, retry)

    # Now let's call it and return the result
    return fault(environ, start_response)


def _report_limit_class(args, result):
    """
    Report the rate-limit class for the tenant.  This is a
    postprocessor for the limit_class() function, when being called in
    console script mode.

    :param args: A Namespace object containing a 'tenant_id' attribute
                 and a desired rate-limit class in the 'klass'
                 attribute (which should be None if no change was
                 requested).
    :param result: The result of the limit_class() function call.
                   This will be the previously configured rate-limit
                   class for the tenant.

    :returns: None to indicate success.
    """

    print "Tenant %s:" % args.tenant_id
    if args.klass:
        print "  Previous rate-limit class: %s" % result
        print "  New rate-limit class: %s" % args.klass
    else:
        print "  Configured rate-limit class: %s" % result

    return None


@tools.add_argument('conf_file',
                    metavar='config',
                    help="Name of the configuration file, for connecting "
                    "to the Redis database.")
@tools.add_argument('tenant_id',
                    help="ID of the tenant.")
@tools.add_argument('--debug', '-d',
                    dest='debug',
                    action='store_true',
                    default=False,
                    help="Run the tool in debug mode.")
@tools.add_argument('--class', '-c',
                    dest='klass',
                    action='store',
                    default=None,
                    help="If specified, sets the class associated with "
                    "the given tenant ID.")
@tools.add_postprocessor(_report_limit_class)
def limit_class(conf_file, tenant, klass=None):
    """
    Set up or query limit classes associated with tenants.

    :param conf_file: Name of the configuration file, for connecting
                      to the Redis database.
    :param tenant: The ID of the tenant.
    :param klass: If provided, the name of the class to map the tenant
                  to.

    Returns the class associated with the given tenant.
    """

    # Connect to the database...
    conf = config.Config(conf_file=conf_file)
    db = conf.get_database()

    # Get the key for the limit class...
    key = 'limit-class:%s' % tenant

    # Now, look up the tenant's current class
    old_klass = db.get(key) or 'default'

    # Do we need to change it?
    if klass and klass != old_klass:
        if klass == 'default':
            # Resetting to the default
            db.delete(key)
        else:
            # Changing to a new value
            db.set(key, klass)

    return old_klass


# For backwards compatibility
_limit_class = limit_class
