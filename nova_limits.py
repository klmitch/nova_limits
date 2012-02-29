from turnstile import limits


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
    klass = self.db.get('limit-class:%s' % tenant) or 'default'
    environ['turnstile.nova.limitclass'] = klass


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

    def filter(self, environ, params):
        """
        Determines whether this limit applies to this request and
        attaches the tenant name to the params.
        """

        # Do we match?
        if ('turnstile.nova.limitclass' not in environ or
            self.rate_class != environ['turnstile.nova.limitclass']):
            raise limits.DeferLimit()

        # OK, add the tenant to the params
        params['tenant'] = environ['turnstile.nova.tenant']
