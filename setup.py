#!/usr/bin/env python

import os

from setuptools import setup


def readreq(filename):
    result = []
    with open(filename) as f:
        for req in f:
            req = req.lstrip()
            if req.startswith('-e ') or req.startswith('http:'):
                idx = req.find('#egg=')
                if idx >= 0:
                    req = req[idx + 5:].partition('#')[0].strip()
                else:
                    pass
            else:
                req = req.partition('#')[0].strip()
            if not req:
                continue
            result.append(req)
    return result


def readfile(filename):
    with open(filename) as f:
        return f.read()


setup(
    name='nova_limits',
    version='0.7.0b1',
    author='Kevin L. Mitchell',
    author_email='kevin.mitchell@rackspace.com',
    url='https://github.com/klmitch/nova_limits',
    description="Nova-specific rate-limit class for turnstile",
    long_description=readfile('README.rst'),
    license='Apache License (2.0)',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Paste',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Middleware',
    ],
    py_modules=['nova_limits'],
    install_requires=readreq('.requires'),
    tests_require=readreq('.test-requires'),
    entry_points={
        'console_scripts': [
            'limit_class = nova_limits:limit_class.console',
        ],
        'turnstile.formatter': [
            'nova_limits = nova_limits:nova_formatter',
        ],
        'turnstile.limit': [
            'nova_limits = nova_limits:NovaClassLimit',
        ],
        'turnstile.postprocessor': [
            'nova_limits = nova_limits:nova_postprocess',
        ],
        'turnstile.preprocessor': [
            'nova_limits = nova_limits:nova_preprocess',
        ],
    },
)
