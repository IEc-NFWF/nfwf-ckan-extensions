# encoding: utf-8
"""Refuse to run the suite against anything but a test database.
"""
import pytest

from ckan.common import config


def _database_name(url):
    return url.split(u'/')[-1].split(u'?')[0]


@pytest.fixture(scope=u'session', autouse=True)
def refuse_non_test_database():
    url = config.get(u'sqlalchemy.url') or u''
    name = _database_name(url)
    if not name.endswith(u'_test'):
        pytest.exit(
            u'Refusing to run: sqlalchemy.url points at database %r, which is '
            u'not a test database. The clean_db fixture drops every table it '
            u'can reach. CKAN_SQLALCHEMY_URL in the environment overrides '
            u'test.ini -- pin it to ...@db/ckan_test and try again.' % name,
            returncode=1)
