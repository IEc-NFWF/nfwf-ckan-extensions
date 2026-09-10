# encoding: utf-8
"""Tests for ``ckan nfwf-permissions migrate-roles``.

``--apply`` is the only thing in Task 125 that deletes anything, so its scope
is what these mostly check: it must touch the droppable rows and leave every
other membership exactly as it was.
"""
import csv
import io
import os

import pytest
from click.testing import CliRunner

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model

from ckanext.nfwf_permissions import cli, migration, roles


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


def _memberships():
    """Every user membership, as comparable tuples."""
    return sorted(
        (m.table_id, m.group_id, m.capacity, m.state)
        for m in model.Session.query(model.Member).filter(
            model.Member.table_name == u'user'))


class World(object):
    def __init__(self):
        self.program = factories.Group()
        self.grant = factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': self.program[u'id']}])

        # Droppable: retired capacity on a Platform Administrator.
        self.service = factories.Sysadmin(name=u'service-account')
        _assign(self.grant[u'id'], self.service[u'name'],
                roles.CAPACITY_ADMIN)

        # Must survive: a live capacity, and a retired one on a real person.
        self.editor = factories.User(name=u'an-editor')
        _assign(self.grant[u'id'], self.editor[u'name'],
                roles.CAPACITY_EDITOR)

        self.retired = factories.User(name=u'holds-retired')
        _assign(self.grant[u'id'], self.retired[u'name'],
                roles.CAPACITY_MEMBER)


@pytest.fixture
def world(clean_db):
    return World()


def _run(*args, **kwargs):
    return CliRunner().invoke(cli.nfwf_permissions,
                              [u'migrate-roles'] + list(args), **kwargs)


@pytest.mark.usefixtures(u'with_plugins')
class TestDryRun(object):

    def test_it_is_the_default_and_writes_nothing(self, world):
        before = _memberships()
        result = _run()

        assert result.exit_code == 0, result.output
        assert u'Dry run: nothing was written' in result.output
        assert _memberships() == before

    def test_it_reports_what_it_would_drop(self, world):
        result = _run()

        assert u'drop' in result.output
        assert u'--apply' in result.output


@pytest.mark.usefixtures(u'with_plugins')
class TestReport(object):

    def test_it_writes_a_csv_with_one_row_per_assignment(self, world, tmpdir):
        path = os.path.join(str(tmpdir), u'report.csv')
        result = _run(u'--report', path)

        assert result.exit_code == 0, result.output
        with io.open(path, encoding=u'utf-8') as handle:
            rows = list(csv.DictReader(handle))

        assert len(rows) == migration.plan()[u'totals'][u'assignments']
        assert set(rows[0]) == set(migration.ASSIGNMENT_FIELDS)

    def test_writing_a_report_is_still_a_dry_run(self, world, tmpdir):
        before = _memberships()
        _run(u'--report', os.path.join(str(tmpdir), u'report.csv'))

        assert _memberships() == before


@pytest.mark.usefixtures(u'with_plugins')
class TestApply(object):

    def test_it_removes_only_the_droppable_rows(self, world):
        droppable = migration.droppable(migration.plan())
        assert droppable, u'the fixture must give it something to drop'

        service = model.User.get(world.service[u'id'])
        editor = model.User.get(world.editor[u'id'])
        retired = model.User.get(world.retired[u'id'])

        result = _run(u'--apply', u'--yes')
        assert result.exit_code == 0, result.output

        # The Platform Administrator's retired row is gone.
        assert roles.grants_for_user(service, [roles.CAPACITY_ADMIN]) == \
            frozenset()
        # Everyone else is untouched.
        assert roles.grants_for_user(editor, [roles.CAPACITY_EDITOR]) == \
            frozenset([world.grant[u'id']])
        assert roles.grants_for_user(retired, [roles.CAPACITY_MEMBER]) == \
            frozenset([world.grant[u'id']])

    def test_it_removes_exactly_as_many_rows_as_it_promised(self, world):
        expected = migration.plan()[u'totals'][u'drop']
        before = len([m for m in _memberships() if m[3] == u'active'])

        _run(u'--apply', u'--yes')

        after = len([m for m in _memberships() if m[3] == u'active'])
        assert before - after == expected

    def test_declining_the_prompt_writes_nothing(self, world):
        before = _memberships()
        result = _run(u'--apply', input=u'n\n')

        assert u'Aborted' in result.output
        assert _memberships() == before

    def test_confirming_the_prompt_applies(self, world):
        before = len([m for m in _memberships() if m[3] == u'active'])
        result = _run(u'--apply', input=u'y\n')

        assert result.exit_code == 0, result.output
        after = len([m for m in _memberships() if m[3] == u'active'])
        assert after < before

    def test_it_is_idempotent(self, world):
        _run(u'--apply', u'--yes')
        after_first = _memberships()

        result = _run(u'--apply', u'--yes')

        assert u'Nothing to drop' in result.output
        assert _memberships() == after_first

    def test_it_says_no_reindex_is_needed_and_why(self, world):
        """A wrong answer here either wastes an hour or leaves stale labels."""
        result = _run(u'--apply', u'--yes')

        assert u'No search reindex is needed' in result.output
        assert u'owner_group' in result.output
