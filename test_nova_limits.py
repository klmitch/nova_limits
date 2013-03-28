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

import StringIO
import sys

import mock
from nova.api.openstack import wsgi
from turnstile import config
from turnstile import limits
from turnstile import tools
import unittest2

import nova_limits


class TestParamsDict(unittest2.TestCase):
    def test_known_keys(self):
        d = nova_limits.ParamsDict(dict(a=1, bravo=2))

        self.assertEqual(d['a'], 1)
        self.assertEqual(d['bravo'], 2)

    def test_unknown_keys(self):
        d = nova_limits.ParamsDict(dict(a=1, b=2))

        self.assertEqual(d['c'], '{c}')
        self.assertEqual(d['delta'], '{delta}')


class TestPreprocess(unittest2.TestCase):
    @mock.patch('time.time', return_value=1000000.0)
    def test_basic(self, mock_time):
        db = mock.Mock(**{'get.return_value': None})
        midware = mock.Mock(db=db)
        environ = {}

        nova_limits.nova_preprocess(midware, environ)

        self.assertDictContainsSubset({
            'turnstile.nova.tenant': '<NONE>',
            'turnstile.nova.limitclass': 'default',
            'turnstile.bucket_set': 'bucket_set:<NONE>',
        }, environ)
        db.assert_has_calls([
            mock.call.get('limit-class:<NONE>'),
            mock.call.zremrangebyscore('bucket_set:<NONE>', 0, 1000000.0),
        ])

    @mock.patch('time.time', return_value=1000000.0)
    def test_tenant(self, mock_time):
        db = mock.Mock(**{'get.return_value': None})
        midware = mock.Mock(db=db)
        environ = {
            'nova.context': mock.Mock(project_id='spam', spec=['project_id']),
        }

        nova_limits.nova_preprocess(midware, environ)

        self.assertDictContainsSubset({
            'turnstile.nova.tenant': 'spam',
            'turnstile.nova.limitclass': 'default',
            'turnstile.bucket_set': 'bucket_set:spam',
        }, environ)
        db.assert_has_calls([
            mock.call.get('limit-class:spam'),
            mock.call.zremrangebyscore('bucket_set:spam', 0, 1000000.0),
        ])

    @mock.patch('time.time', return_value=1000000.0)
    def test_configured_class(self, mock_time):
        db = mock.Mock(**{'get.return_value': 'lim_class'})
        midware = mock.Mock(db=db)
        environ = {
            'nova.context': mock.Mock(project_id='spam', spec=['project_id']),
        }

        nova_limits.nova_preprocess(midware, environ)

        self.assertDictContainsSubset({
            'turnstile.nova.tenant': 'spam',
            'turnstile.nova.limitclass': 'lim_class',
            'turnstile.bucket_set': 'bucket_set:spam',
        }, environ)
        db.assert_has_calls([
            mock.call.get('limit-class:spam'),
            mock.call.zremrangebyscore('bucket_set:spam', 0, 1000000.0),
        ])

    @mock.patch('time.time', return_value=1000000.0)
    def test_configured_class_quotaclass(self, mock_time):
        db = mock.Mock(**{'get.return_value': 'lim_class'})
        midware = mock.Mock(db=db)
        environ = {
            'nova.context': mock.Mock(project_id='spam', quota_class=None,
                                      spec=['project_id', 'quota_class']),
        }

        nova_limits.nova_preprocess(midware, environ)

        self.assertDictContainsSubset({
            'turnstile.nova.tenant': 'spam',
            'turnstile.nova.limitclass': 'lim_class',
            'turnstile.bucket_set': 'bucket_set:spam',
        }, environ)
        db.assert_has_calls([
            mock.call.get('limit-class:spam'),
            mock.call.zremrangebyscore('bucket_set:spam', 0, 1000000.0),
        ])
        self.assertEqual(environ['nova.context'].quota_class, 'lim_class')

    @mock.patch('time.time', return_value=1000000.0)
    def test_class_no_override(self, mock_time):
        db = mock.Mock(**{'get.return_value': 'lim_class'})
        midware = mock.Mock(db=db)
        environ = {
            'nova.context': mock.Mock(project_id='spam', spec=['project_id']),
            'turnstile.nova.limitclass': 'override',
        }

        nova_limits.nova_preprocess(midware, environ)

        self.assertDictContainsSubset({
            'turnstile.nova.tenant': 'spam',
            'turnstile.nova.limitclass': 'override',
            'turnstile.bucket_set': 'bucket_set:spam',
        }, environ)
        db.assert_has_calls([
            mock.call.get('limit-class:spam'),
            mock.call.zremrangebyscore('bucket_set:spam', 0, 1000000.0),
        ])

    @mock.patch('time.time', return_value=1000000.0)
    def test_class_no_override_quotaclass(self, mock_time):
        db = mock.Mock(**{'get.return_value': 'lim_class'})
        midware = mock.Mock(db=db)
        environ = {
            'nova.context': mock.Mock(project_id='spam', quota_class=None,
                                      spec=['project_id', 'quota_class']),
            'turnstile.nova.limitclass': 'override',
        }

        nova_limits.nova_preprocess(midware, environ)

        self.assertDictContainsSubset({
            'turnstile.nova.tenant': 'spam',
            'turnstile.nova.limitclass': 'override',
            'turnstile.bucket_set': 'bucket_set:spam',
        }, environ)
        db.assert_has_calls([
            mock.call.get('limit-class:spam'),
            mock.call.zremrangebyscore('bucket_set:spam', 0, 1000000.0),
        ])
        self.assertEqual(environ['nova.context'].quota_class, 'override')


class TestPostprocess(unittest2.TestCase):
    def _make_limit(self, **kwargs):
        attrs = kwargs.keys() + ['load']
        kwargs['load.side_effect'] = lambda key: mock.Mock(**key.bucket)
        return mock.Mock(spec=attrs, **kwargs)

    @mock.patch('time.time', return_value=1000000.0)
    @mock.patch('turnstile.limits.BucketKey.decode',
                side_effect=lambda key: mock.Mock(**key))
    def test_limits(self, mock_decode, mock_time):
        db = mock.Mock(**{'zrange.return_value': []})
        limits = [
            self._make_limit(
                uuid='uuid',
                queries=[],
                verbs=['GET', 'PUT'],
                unit='minute',
                uri='/spam/uri',
                value=23,
            ),
            self._make_limit(
                uuid='uuid2',
                queries=[],
                verbs=[],
                unit='second',
                uri='/spam/uri2',
                value=18,
            ),
            self._make_limit(
                uuid='uuid3',
                rate_class='spam',
                queries=[],
                verbs=['GET'],
                unit='hour',
                uri='/spam/uri3',
                value=17,
            ),
            self._make_limit(
                uuid='uuid4',
                rate_class='lim_class',
                queries=[],
                verbs=['GET'],
                unit='day',
                uri='/spam/uri4',
                value=1,
            ),
            self._make_limit(
                uuid='uuid5',
                queries=[],
                verbs=['GET'],
                unit='1234',
                uri='/spam/uri5',
                value=183,
            ),
            self._make_limit(
                uuid='uuid6',
                queries=['bravo', 'alfa'],
                verbs=['GET'],
                unit='day',
                uri='/spam/uri6',
                value=1,
            ),
        ]
        midware = mock.Mock(db=db, limits=limits)
        environ = {
            'turnstile.nova.limitclass': 'lim_class',
            'turnstile.bucket_set': 'bucket_set:spam',
        }

        nova_limits.nova_postprocess(midware, environ)

        self.assertEqual(environ['nova.limits'], [
            dict(
                verb='GET',
                URI='/spam/uri',
                regex='/spam/uri',
                value=23,
                unit='MINUTE',
                remaining=23,
                resetTime=1000000.0,
            ),
            dict(
                verb='PUT',
                URI='/spam/uri',
                regex='/spam/uri',
                value=23,
                unit='MINUTE',
                remaining=23,
                resetTime=1000000.0,
            ),
            dict(
                verb='GET',
                URI='/spam/uri2',
                regex='/spam/uri2',
                value=18,
                unit='SECOND',
                remaining=18,
                resetTime=1000000.0,
            ),
            dict(
                verb='HEAD',
                URI='/spam/uri2',
                regex='/spam/uri2',
                value=18,
                unit='SECOND',
                remaining=18,
                resetTime=1000000.0,
            ),
            dict(
                verb='POST',
                URI='/spam/uri2',
                regex='/spam/uri2',
                value=18,
                unit='SECOND',
                remaining=18,
                resetTime=1000000.0,
            ),
            dict(
                verb='PUT',
                URI='/spam/uri2',
                regex='/spam/uri2',
                value=18,
                unit='SECOND',
                remaining=18,
                resetTime=1000000.0,
            ),
            dict(
                verb='DELETE',
                URI='/spam/uri2',
                regex='/spam/uri2',
                value=18,
                unit='SECOND',
                remaining=18,
                resetTime=1000000.0,
            ),
            dict(
                verb='GET',
                URI='/spam/uri4',
                regex='/spam/uri4',
                value=1,
                unit='DAY',
                remaining=1,
                resetTime=1000000.0,
            ),
            dict(
                verb='GET',
                URI='/spam/uri5',
                regex='/spam/uri5',
                value=183,
                unit='UNKNOWN',
                remaining=183,
                resetTime=1000000.0,
            ),
            dict(
                verb='GET',
                URI='/spam/uri6?alfa={alfa}&bravo={bravo}',
                regex='/spam/uri6?alfa={alfa}&bravo={bravo}',
                value=1,
                unit='DAY',
                remaining=1,
                resetTime=1000000.0,
            ),
        ])
        db.zrange.assert_called_once_with('bucket_set:spam', 0, -1)

    @mock.patch('time.time', return_value=1000000.0)
    @mock.patch('turnstile.limits.BucketKey.decode',
                side_effect=lambda key: mock.Mock(**key))
    def test_limits_with_buckets(self, mock_decode, mock_time):
        db = mock.Mock(**{'zrange.return_value': [
            dict(
                uuid='uuid',
                params={},
                bucket=dict(messages=2, expire=1000001.0),
            ),
            dict(
                uuid='uuid2',
                params=dict(unused='foo'),
                bucket=dict(messages=5, expire=999999.0),
            ),
            dict(
                uuid='uuid3',
                params=dict(param='foo'),
                bucket=dict(messages=10, expire=1000005.0),
            ),
            dict(
                uuid='uuid3',
                params=dict(param='bar'),
                bucket=dict(messages=5, expire=1000001.0),
            ),
        ]})
        limits = [
            self._make_limit(
                uuid='uuid',
                queries=[],
                verbs=['GET'],
                unit='minute',
                uri='/spam/{uri}',
                value=7,
            ),
            self._make_limit(
                uuid='uuid2',
                queries=[],
                verbs=['GET'],
                unit='minute',
                uri='/spam/{uri2}/{used}',
                value=20,
            ),
            self._make_limit(
                uuid='uuid3',
                queries=[],
                verbs=['GET'],
                unit='minute',
                uri='/spam/{uri3}/{param}',
                value=50,
            ),
            self._make_limit(
                uuid='uuid4',
                queries=[],
                verbs=['GET'],
                unit='minute',
                uri='/spam/{uri4}/{param}',
                value=50,
            ),
            self._make_limit(
                uuid='uuid5',
                queries=[],
                verbs=['GET'],
                unit='minute',
                uri='/spam/{uri5}',
                value=10,
            ),
        ]
        midware = mock.Mock(db=db, limits=limits)
        environ = {
            'turnstile.nova.limitclass': 'lim_class',
            'turnstile.bucket_set': 'bucket_set:spam',
        }

        nova_limits.nova_postprocess(midware, environ)

        self.assertEqual(environ['nova.limits'], [
            dict(
                verb='GET',
                URI='/spam/{uri}',
                regex='/spam/{uri}',
                value=7,
                unit='MINUTE',
                remaining=2,
                resetTime=1000001.0,
            ),
            dict(
                verb='GET',
                URI='/spam/{uri2}/{used}',
                regex='/spam/{uri2}/{used}',
                value=20,
                unit='MINUTE',
                remaining=5,
                resetTime=999999.0,
            ),
            dict(
                verb='GET',
                URI='/spam/{uri3}/foo',
                regex='/spam/{uri3}/foo',
                value=50,
                unit='MINUTE',
                remaining=10,
                resetTime=1000005.0,
            ),
            dict(
                verb='GET',
                URI='/spam/{uri3}/bar',
                regex='/spam/{uri3}/bar',
                value=50,
                unit='MINUTE',
                remaining=5,
                resetTime=1000001.0,
            ),
            dict(
                verb='GET',
                URI='/spam/{uri3}/{param}',
                regex='/spam/{uri3}/{param}',
                value=50,
                unit='MINUTE',
                remaining=5,
                resetTime=1000005.0,
            ),
            dict(
                verb='GET',
                URI='/spam/{uri4}/{param}',
                regex='/spam/{uri4}/{param}',
                value=50,
                unit='MINUTE',
                remaining=50,
                resetTime=1000000.0,
            ),
            dict(
                verb='GET',
                URI='/spam/{uri5}',
                regex='/spam/{uri5}',
                value=10,
                unit='MINUTE',
                remaining=10,
                resetTime=1000000.0,
            ),
        ])


class TestNovaClassLimit(unittest2.TestCase):
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


class TestNovaFormatter(unittest2.TestCase):
    @mock.patch.object(wsgi, 'OverLimitFault',
                       return_value=mock.Mock(return_value='rate-limited'))
    @mock.patch('time.time', return_value=1000000.0)
    def test_formatter(self, mock_time, mock_OverLimitFault):
        fault = mock_OverLimitFault.return_value
        lim = mock.Mock(value=23, uri='/spam', unit='second')
        environ = dict(REQUEST_METHOD='SPAM')

        result = nova_limits.nova_formatter('status', 18, lim, 'bucket',
                                            environ, 'start_response')

        self.assertEqual(result, 'rate-limited')
        mock_OverLimitFault.assert_called_once_with(
            "This request was rate-limited.",
            "Only 23 SPAM request(s) can be made to /spam every SECOND.",
            1000018.0)
        fault.assert_called_once_with(environ, 'start_response')


class TestReportLimitClass(unittest2.TestCase):
    @mock.patch.object(sys, 'stdout', StringIO.StringIO())
    def test_configured(self):
        args = mock.Mock(tenant_id='tenant', klass=None)

        result = nova_limits._report_limit_class(args, 'old_class')

        self.assertEqual(result, None)
        self.assertEqual(sys.stdout.getvalue(),
                         "Tenant tenant:\n"
                         "  Configured rate-limit class: old_class\n")

    @mock.patch.object(sys, 'stdout', StringIO.StringIO())
    def test_updated(self):
        args = mock.Mock(tenant_id='tenant', klass='new_class')

        result = nova_limits._report_limit_class(args, 'old_class')

        self.assertEqual(result, None)
        self.assertEqual(sys.stdout.getvalue(),
                         "Tenant tenant:\n"
                         "  Previous rate-limit class: old_class\n"
                         "  New rate-limit class: new_class\n")


class TestLimitClass(unittest2.TestCase):
    def test_has_arguments(self):
        self.assertIsInstance(nova_limits.limit_class, tools.ScriptAdaptor)
        self.assertGreater(len(nova_limits.limit_class._arguments), 0)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': 'old_class',
        }),
    }))
    def test_get(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = nova_limits.limit_class('config_file', 'spam')

        self.assertEqual(result, 'old_class')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('limit-class:spam')
        self.assertFalse(db.set.called)
        self.assertFalse(db.delete.called)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': None,
        }),
    }))
    def test_get_unset(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = nova_limits.limit_class('config_file', 'spam')

        self.assertEqual(result, 'default')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('limit-class:spam')
        self.assertFalse(db.set.called)
        self.assertFalse(db.delete.called)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': 'old_class',
        }),
    }))
    def test_set(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = nova_limits.limit_class('config_file', 'spam', 'new_class')

        self.assertEqual(result, 'old_class')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('limit-class:spam')
        db.set.assert_called_once_with('limit-class:spam', 'new_class')
        self.assertFalse(db.delete.called)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': None,
        }),
    }))
    def test_set_unset(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = nova_limits.limit_class('config_file', 'spam', 'new_class')

        self.assertEqual(result, 'default')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('limit-class:spam')
        db.set.assert_called_once_with('limit-class:spam', 'new_class')
        self.assertFalse(db.delete.called)

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': 'old_class',
        }),
    }))
    def test_delete(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = nova_limits.limit_class('config_file', 'spam', 'default')

        self.assertEqual(result, 'old_class')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('limit-class:spam')
        self.assertFalse(db.set.called)
        db.delete.assert_called_once_with('limit-class:spam')

    @mock.patch.object(config, 'Config', return_value=mock.Mock(**{
        'get_database.return_value': mock.Mock(**{
            'get.return_value': None,
        }),
    }))
    def test_delete_unset(self, mock_Config):
        db = mock_Config.return_value.get_database.return_value

        result = nova_limits.limit_class('config_file', 'spam', 'default')

        self.assertEqual(result, 'default')
        mock_Config.assert_called_once_with(conf_file='config_file')
        db.get.assert_called_once_with('limit-class:spam')
        self.assertFalse(db.set.called)
        self.assertFalse(db.delete.called)
