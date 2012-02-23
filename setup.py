import os
from setuptools import setup


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name='nova_limits',
    version='0.1',
    author='Kevin L. Mitchell',
    author_email='kevin.mitchell@rackspace.com',
    description="Nova-specific rate-limit class for turnstile",
    license='',
    py_modules=['nova_limits'],
    url='https://github.com/klmitch/nova_limits',
    long_description=read('README.rst'),
    install_requires=[
        'turnstile',
        ],
    )
