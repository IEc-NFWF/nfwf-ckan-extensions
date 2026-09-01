# encoding: utf-8
"""Refuse to run the suite against anything but a test database.

``test.ini`` inherits ``sqlalchemy.url = postgres://ckan:ckan@db/ckan_test``
from CKAN's ``test-core.ini``, but CKAN also reads ``CKAN_SQLALCHEMY_URL`` from
the environment and that *wins*. In this dev container the environment says
``.../ckan`` -- the development database -- so a plain
``pytest --ckan-ini=test.ini`` points the whole suite at real data, and the
``clean_db`` fixture then tries to ``DROP`` every table in it.

That is not hypothetical: it happened here. The only reason the development
database survived was that PostGIS's ``spatial_ref_sys`` is owned by
``postgres``, so the ``DROP`` failed and the transaction rolled back.

Every sibling extension's ``test.ini`` has the same shape, so run tests with
the URL pinned:

    CKAN_SQLALCHEMY_URL=postgresql://ckan:ckan@db/ckan_test \
        pytest --ckan-ini=test.ini ckanext/nfwf_permissions/tests
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
