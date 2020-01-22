import sys
from setuptools import setup
from setuptools.command.test import test as TestCommand

install_requires = ['beautifulsoup4',
                    'slackclient',
                    'requests',
                    'Flask',
                    'gunicorn[eventlet]<=19.9.0']

tests_require = ['pytest', 'pytest-flake8']


class PyTest(TestCommand):
    """Ref: https://pytest.readthedocs.io/en/2.7.3/goodpractises.html"""
    def run_tests(self):
        import pytest
        errno = pytest.main(['--flake8'])
        sys.exit(errno)


setup(name='linkbot',
      install_requires=install_requires,
      tests_require=tests_require,
      cmdclass={'test': PyTest},
      description='slackbot listening for mentions of jira issues, etc')
