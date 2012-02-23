============================================
Nova-specific Rate Limit Class for Turnstile
============================================

This package provides the ``nova_limits`` Python module, which
contains the ``nova_preprocess()`` preprocessor and the
``NovaClassLimit`` limit class for use with Turnstile.  These two
pieces work together to provide class-based rate limiting integration
with nova.  To use, you must configure the Turnstile middleware with
the following configuration::

    [filter:turnstile]
    paste.filter_factory = turnstile.middleware:turnstile_filter
    redis.host = <your Redis database host>
    preprocess = nova_limits:nova_preprocess

Then, simply use the ``nova_limits:NovaClassLimit`` rate limit class
in your configuration.
