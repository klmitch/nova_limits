============================================
Nova-specific Rate Limit Class for Turnstile
============================================

This package provides the ``nova_limits`` Python module, which
contains the ``nova_preprocess()`` preprocessor, the
``nova_postprocess()`` postprocessor, the ``NovaClassLimit`` limit
class, and the ``nova_formatter()`` replacement delay formatter, all
for use with Turnstile.  These pieces work together to provide
class-based rate limiting integration with nova.  To use, you must
configure the Turnstile middleware with the following configuration::

    [filter:turnstile]
    use = egg:turnstile#turnstile
    enable = nova_limits
    formatter = nova_limits
    redis.host = <your Redis database host>

Then, simply use the ``nova_limits`` rate limit class in your limits
configuration.

Using ``NovaClassLimit``
========================

In addition to the other attributes provided by
``turnstile.limits:Limit``, the ``NovaClassLimit`` limit class
provides one additional required argument: the ``rate_class``.  Each
tenant is associated with a given rate-limit class through the Redis
database.  (If no such association is present, the rate-limit class
for a tenant is ``default``.)  Setting ``rate_class`` on
``NovaClassLimit`` restricts the limiting action to only those tenants
in the given rate-limit class.

Also note that, for nova, the URIs used in configuring rate limiting
must include the version identifier, i.e.,
"/v2/{tenant}/servers/detail".
