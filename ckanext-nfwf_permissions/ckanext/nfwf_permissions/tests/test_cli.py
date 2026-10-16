# encoding: utf-8
"""Tests for ``ckan nfwf-permissions migrate-roles``.

``--apply`` is the only thing in Task 125 that deletes anything, so its scope
is what these mostly check: it must touch the droppable rows and leave every
other membership exactly as it was.
"""
import csv
import io
import os
import tempfile

import pytest
from click.testing import CliRunner

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model

from ckanext.nfwf_permissions import cli, migration, roles
from ckanext.nfwf_permissions.tests.test_cleanup import _replay


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

        # Droppable for the other reason: a legacy program membership, held by
        # an ordinary person rather than a service account.
        self.old_reader = factories.User(name=u'old-program-member')
        _assign(self.program[u'id'], self.old_reader[u'name'],
                roles.CAPACITY_MEMBER)


@pytest.fixture
def world(clean_db):
    return World()


def _run(*args, **kwargs):
    args = list(args)
    if u'--apply' in args and u'--undo-file' not in args:
        # Out of the working directory. A run that writes nothing writes no
        # undo file either, so this only ever lands on the applying tests.
        args += [u'--undo-file',
                 os.path.join(tempfile.mkdtemp(), u'undo.sql')]
    return CliRunner().invoke(cli.nfwf_permissions,
                              [u'migrate-roles'] + args, **kwargs)


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
        # So is the real person's, since 2026-10-13: Grant Member is not a
        # role in the new model and the product owner settled that these are
        # removed rather than promoted.
        assert roles.grants_for_user(retired, [roles.CAPACITY_MEMBER]) == \
            frozenset()
        # A real role is untouched.
        assert roles.grants_for_user(editor, [roles.CAPACITY_EDITOR]) == \
            frozenset([world.grant[u'id']])

    def test_it_removes_a_legacy_membership_from_an_ordinary_account(
            self, world):
        """The second drop rule, which nearly shipped as a silent no-op.

        ``--apply`` re-reads ``user.sysadmin`` before each delete, because the
        first rule ("nothing to restore it to") only holds while the account
        is still a Platform Administrator. Applied to this rule that check
        would skip every row, since legacy memberships are by definition held
        by ordinary people.
        """
        reader = model.User.get(world.old_reader[u'id'])
        assert roles.programs_for_user(reader, [roles.CAPACITY_MEMBER])

        result = _run(u'--apply', u'--yes')
        assert result.exit_code == 0, result.output

        assert roles.programs_for_user(reader, [roles.CAPACITY_MEMBER]) == \
            frozenset()
        assert u'skipped' not in result.output.lower(), result.output

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


@pytest.mark.usefixtures(u'with_plugins')
class TestUndoFile(object):
    """``--apply`` soft deletes, which makes the data recoverable but not the
    run: ``member`` has no timestamp, so afterwards nothing says which rows
    this run flipped. The undo file is the only thing that does."""

    def test_it_writes_one_statement_per_row_it_removed(self, world, tmpdir):
        path = os.path.join(str(tmpdir), u'undo.sql')
        expected = len(migration.droppable(migration.plan()))

        result = _run(u'--apply', u'--yes', u'--undo-file', path)

        assert result.exit_code == 0, result.output
        script = io.open(path, encoding=u'utf-8').read()
        assert script.count(u"UPDATE member SET state='active'") == expected
        assert u'Undo script written to' in result.output

    def test_the_script_puts_every_row_back(self, world, tmpdir):
        path = os.path.join(str(tmpdir), u'undo.sql')
        before = _memberships()

        _run(u'--apply', u'--yes', u'--undo-file', path)
        assert _memberships() != before

        _replay(path)

        assert _memberships() == before

    def test_a_run_that_cannot_record_itself_does_not_start(self, world,
                                                            tmpdir):
        """The whole argument for applying these changes is that they can be
        undone, so a run that cannot write its undo file must not happen."""
        before = _memberships()
        unwritable = os.path.join(str(tmpdir), u'no', u'such', u'undo.sql')

        result = _run(u'--apply', u'--yes', u'--undo-file', unwritable)

        assert result.exit_code != 0
        assert _memberships() == before

    def test_it_refuses_to_overwrite_an_existing_undo_file(self, tmp_path):
        """migrate-roles must not erase the cleanup's undo file.

        The two run back to back against the same database, so the second
        being pointed at the first one's path is an easy slip.
        """
        path = os.path.join(str(tmp_path), u'undo.sql')
        io.open(path, u'w', encoding=u'utf-8').write(u'-- an earlier run\n')

        result = _run(u'--apply', u'--yes', u'--undo-file', path)

        assert result.exit_code != 0
        assert io.open(path, encoding=u'utf-8').read() == u'-- an earlier run\n'
