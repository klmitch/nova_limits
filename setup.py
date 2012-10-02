import os
from setuptools import setup


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name='nova_limits',
    version='0.6.1',
    author='Kevin L. Mitchell',
    author_email='kevin.mitchell@rackspace.com',
    description="Nova-specific rate-limit class for turnstile",
    license='Apache License (2.0)',
    py_modules=['nova_limits'],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Paste',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Middleware',
        ],
    url='https://github.com/klmitch/nova_limits',
    long_description=read('README.rst'),
    entry_points={
        'console_scripts': [
            'limit_class = nova_limits:limit_class',
            ],
        },
    install_requires=[
        'argparse',
        'msgpack-python',
        'nova',
        'turnstile>=0.6.1',
        ],
    tests_require=[
        'mox',
        'nose',
        'unittest2>=0.5.1',
        ],
    )
