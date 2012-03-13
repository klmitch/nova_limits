import StringIO
import sys
import time
import unittest

import argparse
from nova.api.openstack import wsgi
import stubout
from turnstile import limits
from turnstile import tools

import nova_limits


class FakeDatabase(object):
    def __init__(self, fake_db=None):
        self.fake_db = fake_db or {}
        self.actions = []

    def get(self, key):
        self.actions.append(('get', key))
        return self.fake_db.get(key)

    def set(self, key, value):
        self.actions.append(('set', key, value))
        self.fake_db[key] = value

    def delete(self, key):
        self.actions.append(('delete', key))
        if key in self.fake_db:
            del self.fake_db[key]


class FakeMiddleware(object):
    def __init__(self, db, limits):
        self.db = db
        self.limits = limits


class FakeObject(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestPreprocess(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()

        self.stubs.Set(time, 'time', lambda: 1000000000)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_basic(self):
        db = FakeDatabase()
        midware = FakeMiddleware(db, [])
        environ = {}
        nova_limits.nova_preprocess(midware, environ)

        self.assertEqual(environ, {
                'turnstile.nova.tenant': '<NONE>',
                'turnstile.nova.limitclass': 'default',
                'nova.limits': [],
                })
        self.assertEqual(db.actions, [
                ('get', 'limit-class:<NONE>'),
                ])

    def test_tenant(self):
        db = FakeDatabase()
        midware = FakeMiddleware(db, [])
        environ = {
            'nova.context': FakeObject(project_id='spam'),
            }
        nova_limits.nova_preprocess(midware, environ)

        self.assertEqual(environ['turnstile.nova.tenant'], 'spam')
        self.assertEqual(environ['turnstile.nova.limitclass'], 'default')
        self.assertEqual(environ['nova.limits'], [])
        self.assertEqual(db.actions, [
                ('get', 'limit-class:spam'),
                ])

    def test_configured_class(self):
        db = FakeDatabase({'limit-class:spam': 'lim_class'})
        midware = FakeMiddleware(db, [])
        environ = {
            'nova.context': FakeObject(project_id='spam'),
            }
        nova_limits.nova_preprocess(midware, environ)

        self.assertEqual(environ['turnstile.nova.tenant'], 'spam')
        self.assertEqual(environ['turnstile.nova.limitclass'], 'lim_class')
        self.assertEqual(environ['nova.limits'], [])
        self.assertEqual(db.actions, [
                ('get', 'limit-class:spam'),
                ])

    def test_class_no_override(self):
        db = FakeDatabase({'limit-class:spam': 'lim_class'})
        midware = FakeMiddleware(db, [])
        environ = {
            'nova.context': FakeObject(project_id='spam'),
            'turnstile.nova.limitclass': 'override',
            }
        nova_limits.nova_preprocess(midware, environ)

        self.assertEqual(environ['turnstile.nova.tenant'], 'spam')
        self.assertEqual(environ['turnstile.nova.limitclass'], 'override')
        self.assertEqual(environ['nova.limits'], [])
        self.assertEqual(db.actions, [
                ('get', 'limit-class:spam'),
                ])

    def test_limits(self):
        db = FakeDatabase({'limit-class:spam': 'lim_class'})
        midware = FakeMiddleware(db, [
                FakeObject(
                    queries=[],
                    verbs=['GET', 'PUT'],
                    unit='minute',
                    uri='/spam/uri',
                    value=23),
                FakeObject(
                    queries=[],
                    verbs=[],
                    unit='second',
                    uri='/spam/uri2',
                    value=18),
                FakeObject(
                    rate_class='spam',
                    queries=[],
                    verbs=['GET'],
                    unit='hour',
                    uri='/spam/uri3',
                    value=17),
                FakeObject(
                    rate_class='lim_class',
                    queries=[],
                    verbs=['GET'],
                    unit='day',
                    uri='/spam/uri4',
                    value=1),
                FakeObject(
                    queries=[],
                    verbs=['GET'],
                    unit='1234',
                    uri='/spam/uri5',
                    value=183),
                FakeObject(
                    queries=['bravo', 'alfa'],
                    verbs=['GET'],
                    unit='day',
                    uri='/spam/uri6',
                    value=1),
                ])
        environ = {
            'nova.context': FakeObject(project_id='spam'),
            }
        nova_limits.nova_preprocess(midware, environ)

        self.assertEqual(environ['turnstile.nova.tenant'], 'spam')
        self.assertEqual(environ['turnstile.nova.limitclass'], 'lim_class')
        self.assertEqual(environ['nova.limits'], [
                dict(
                    verb='GET',
                    URI='/spam/uri',
                    regex='/spam/uri',
                    value=23,
                    unit='MINUTE',
                    remaining=23,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='PUT',
                    URI='/spam/uri',
                    regex='/spam/uri',
                    value=23,
                    unit='MINUTE',
                    remaining=23,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='GET',
                    URI='/spam/uri2',
                    regex='/spam/uri2',
                    value=18,
                    unit='SECOND',
                    remaining=18,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='HEAD',
                    URI='/spam/uri2',
                    regex='/spam/uri2',
                    value=18,
                    unit='SECOND',
                    remaining=18,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='POST',
                    URI='/spam/uri2',
                    regex='/spam/uri2',
                    value=18,
                    unit='SECOND',
                    remaining=18,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='PUT',
                    URI='/spam/uri2',
                    regex='/spam/uri2',
                    value=18,
                    unit='SECOND',
                    remaining=18,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='DELETE',
                    URI='/spam/uri2',
                    regex='/spam/uri2',
                    value=18,
                    unit='SECOND',
                    remaining=18,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='GET',
                    URI='/spam/uri4',
                    regex='/spam/uri4',
                    value=1,
                    unit='DAY',
                    remaining=1,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='GET',
                    URI='/spam/uri5',
                    regex='/spam/uri5',
                    value=183,
                    unit='UNKNOWN',
                    remaining=183,
                    resetTime=1000000000,
                    ),
                dict(
                    verb='GET',
                    URI='/spam/uri6?alfa={alfa}&bravo={bravo}',
                    regex='/spam/uri6?alfa={alfa}&bravo={bravo}',
                    value=1,
                    unit='DAY',
                    remaining=1,
                    resetTime=1000000000,
                    ),
                ])
        self.assertEqual(db.actions, [
                ('get', 'limit-class:spam'),
                ])


class TestNovaClassLimit(unittest.TestCase):
    def setUp(self):
        self.lim = nova_limits.NovaClassLimit('db', uri='/spam', value=18,
                                              unit='second',
                                              rate_class='lim_class')

    def test_route_base(self):
        route_args = {}
        result = self.lim.route('/spam', route_args)

        self.assertEqual(result, '/spam')

    def test_route_v1(self):
        route_args = {}
        result = self.lim.route('/v1.1/spam', route_args)

        self.assertEqual(result, '/spam')

    def test_route_v2(self):
        route_args = {}
        result = self.lim.route('/v2/spam', route_args)

        self.assertEqual(result, '/spam')

    def test_route_v1_base(self):
        route_args = {}
        result = self.lim.route('/v1.1', route_args)

        self.assertEqual(result, '/v1.1')

    def test_route_v2_base(self):
        route_args = {}
        result = self.lim.route('/v2', route_args)

        self.assertEqual(result, '/v2')

    def test_filter_noclass(self):
        environ = {
            'turnstile.nova.tenant': 'tenant',
            }
        params = {}
        unused = {}
        with self.assertRaises(limits.DeferLimit):
            self.lim.filter(environ, params, unused)

        self.assertEqual(environ, {
                'turnstile.nova.tenant': 'tenant',
                })
        self.assertEqual(params, {})
        self.assertEqual(unused, {})

    def test_filter_notenant(self):
        environ = {
            'turnstile.nova.limitclass': 'lim_class',
            }
        params = {}
        unused = {}
        with self.assertRaises(limits.DeferLimit):
            self.lim.filter(environ, params, unused)

        self.assertEqual(environ, {
                'turnstile.nova.limitclass': 'lim_class',
                })
        self.assertEqual(params, {})
        self.assertEqual(unused, {})

    def test_filter_wrong_class(self):
        environ = {
            'turnstile.nova.limitclass': 'spam',
            'turnstile.nova.tenant': 'tenant',
            }
        params = {}
        unused = {}
        with self.assertRaises(limits.DeferLimit):
            self.lim.filter(environ, params, unused)

        self.assertEqual(environ, {
                'turnstile.nova.limitclass': 'spam',
                'turnstile.nova.tenant': 'tenant',
                })
        self.assertEqual(params, {})
        self.assertEqual(unused, {})

    def test_filter(self):
        environ = {
            'turnstile.nova.limitclass': 'lim_class',
            'turnstile.nova.tenant': 'tenant',
            }
        params = {}
        unused = {}
        self.lim.filter(environ, params, unused)

        self.assertEqual(environ, {
                'turnstile.nova.limitclass': 'lim_class',
                'turnstile.nova.tenant': 'tenant',
                })
        self.assertEqual(params, dict(tenant='tenant'))
        self.assertEqual(unused, {})


class StubNovaTurnstileMiddleware(nova_limits.NovaTurnstileMiddleware):
    def __init__(self):
        pass


class TestNovaTurnstileMiddleware(unittest.TestCase):
    def setUp(self):
        self.midware = StubNovaTurnstileMiddleware()
        self.stubs = stubout.StubOutForTesting()

        def fake_over_limit_fault(msg, err, retry):
            def inner(environ, start_response):
                return (msg, err, retry, environ, start_response)
            return inner

        self.stubs.Set(wsgi, 'OverLimitFault', fake_over_limit_fault)
        self.stubs.Set(time, 'time', lambda: 1000000000)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_format_delay(self):
        lim = FakeObject(value=23, uri='/spam', unit='second')
        environ = dict(REQUEST_METHOD='SPAM')
        start_response = lambda: None
        result = self.midware.format_delay(18, lim, None,
                                           environ, start_response)

        self.assertEqual(result[0], 'This request was rate-limited.')
        self.assertEqual(result[1],
                         'Only 23 SPAM request(s) can be made to /spam '
                         'every SECOND.')
        self.assertEqual(result[2], 1000000018)
        self.assertEqual(id(result[3]), id(environ))
        self.assertEqual(id(result[4]), id(start_response))


class TestLimitClass(unittest.TestCase):
    def setUp(self):
        self.fake_db = FakeDatabase()
        self.stubs = stubout.StubOutForTesting()

        def fake_parse_config(config):
            self.assertEqual(config, 'config_file')
            return self.fake_db, 'limits', 'control'

        self.stubs.Set(tools, 'parse_config', fake_parse_config)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get(self):
        self.fake_db.fake_db['limit-class:spam'] = 'lim_class'
        old_klass = nova_limits._limit_class('config_file', 'spam')

        self.assertEqual(self.fake_db.fake_db, {
                'limit-class:spam': 'lim_class',
                })
        self.assertEqual(self.fake_db.actions, [
                ('get', 'limit-class:spam'),
                ])
        self.assertEqual(old_klass, 'lim_class')

    def test_get_undeclared(self):
        old_klass = nova_limits._limit_class('config_file', 'spam')

        self.assertEqual(self.fake_db.fake_db, {})
        self.assertEqual(self.fake_db.actions, [
                ('get', 'limit-class:spam'),
                ])
        self.assertEqual(old_klass, 'default')

    def test_set(self):
        self.fake_db.fake_db['limit-class:spam'] = 'old_class'
        old_klass = nova_limits._limit_class('config_file', 'spam',
                                             'new_class')

        self.assertEqual(self.fake_db.fake_db, {
                'limit-class:spam': 'new_class',
                })
        self.assertEqual(self.fake_db.actions, [
                ('get', 'limit-class:spam'),
                ('set', 'limit-class:spam', 'new_class'),
                ])
        self.assertEqual(old_klass, 'old_class')

    def test_set_undeclared(self):
        old_klass = nova_limits._limit_class('config_file', 'spam',
                                             'new_class')

        self.assertEqual(self.fake_db.fake_db, {
                'limit-class:spam': 'new_class',
                })
        self.assertEqual(self.fake_db.actions, [
                ('get', 'limit-class:spam'),
                ('set', 'limit-class:spam', 'new_class'),
                ])
        self.assertEqual(old_klass, 'default')

    def test_set_unchanged(self):
        self.fake_db.fake_db['limit-class:spam'] = 'lim_class'
        old_klass = nova_limits._limit_class('config_file', 'spam',
                                             'lim_class')

        self.assertEqual(self.fake_db.fake_db, {
                'limit-class:spam': 'lim_class',
                })
        self.assertEqual(self.fake_db.actions, [
                ('get', 'limit-class:spam'),
                ])
        self.assertEqual(old_klass, 'lim_class')

    def test_delete(self):
        self.fake_db.fake_db['limit-class:spam'] = 'old_class'
        old_klass = nova_limits._limit_class('config_file', 'spam', 'default')

        self.assertEqual(self.fake_db.fake_db, {})
        self.assertEqual(self.fake_db.actions, [
                ('get', 'limit-class:spam'),
                ('delete', 'limit-class:spam'),
                ])
        self.assertEqual(old_klass, 'old_class')

    def test_delete_undeclared(self):
        old_klass = nova_limits._limit_class('config_file', 'spam', 'default')

        self.assertEqual(self.fake_db.fake_db, {})
        self.assertEqual(self.fake_db.actions, [
                ('get', 'limit-class:spam'),
                ])
        self.assertEqual(old_klass, 'default')


class FakeNamespace(object):
    config = 'config'
    tenant_id = 'spam'
    debug = False
    klass = None

    def __init__(self, nsdict):
        self.__dict__.update(nsdict)


class FakeArgumentParser(object):
    def __init__(self, nsdict):
        self._namespace = FakeNamespace(nsdict)

    def add_argument(self, *args, **kwargs):
        pass

    def parse_args(self):
        return self._namespace


class TestToolLimitClass(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()

        self.limit_class_result = None
        self.limit_class_args = None

        self.args_dict = {}

        self.stdout = StringIO.StringIO()

        def fake_limit_class(config, tenant_id, klass=None):
            self.limit_class_args = (config, tenant_id, klass)
            if isinstance(self.limit_class_result, Exception):
                raise self.limit_class_result
            return self.limit_class_result

        def fake_argument_parser(*args, **kwargs):
            return FakeArgumentParser(self.args_dict)

        self.stubs.Set(nova_limits, '_limit_class', fake_limit_class)
        self.stubs.Set(argparse, 'ArgumentParser', fake_argument_parser)
        self.stubs.Set(sys, 'stdout', self.stdout)

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_noargs(self):
        self.limit_class_result = 'default'
        result = nova_limits.limit_class()

        self.assertEqual(self.limit_class_args, ('config', 'spam', None))
        self.assertEqual(self.stdout.getvalue(),
                         'Tenant spam:\n'
                         '  Configured rate-limit class: default\n')
        self.assertEqual(result, None)

    def test_failure(self):
        self.limit_class_result = Exception("foobar")
        result = nova_limits.limit_class()

        self.assertEqual(result, "foobar")
        self.assertEqual(self.stdout.getvalue(), '')

    def test_failure_debug(self):
        class AnException(Exception):
            pass

        self.args_dict['debug'] = True
        self.limit_class_result = AnException("foobar")
        with self.assertRaises(AnException):
            nova_limits.limit_class()
        self.assertEqual(self.stdout.getvalue(), '')

    def test_update(self):
        self.args_dict['klass'] = 'new_class'
        self.limit_class_result = 'old_class'
        nova_limits.limit_class()

        self.assertEqual(self.limit_class_args,
                         ('config', 'spam', 'new_class'))
        self.assertEqual(self.stdout.getvalue(),
                         'Tenant spam:\n'
                         '  Previous rate-limit class: old_class\n'
                         '  New rate-limit class: new_class\n')
