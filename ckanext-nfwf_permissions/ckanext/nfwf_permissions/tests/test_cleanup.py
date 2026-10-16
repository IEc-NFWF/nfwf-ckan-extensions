# encoding: utf-8
"""Tests for ``ckan nfwf-permissions cleanup``.

The module deletes accounts and grants from a hand-written list, so most of
what is worth testing is what it *declines* to delete. Each refusal below
stands for a specific way a list written from a spreadsheet goes wrong, and
each one is checked twice: that the verdict says so, and that ``--apply``
really leaves the thing alone.
"""
import io
import os
import tempfile

import pytest
from click.testing import CliRunner

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model

from ckanext.nfwf_permissions import cleanup, cli, roles, undo


class _Buffer(io.StringIO):
    """A recorder's file that survives being closed, so a test can read it."""

    def close(self):
        pass


def _recorder():
    """A recorder writing to memory. Returns ``(recorder, buffer)``."""
    buf = _Buffer()
    return undo.Recorder(buf, u'test'), buf


def _replay(path):
    """Run an undo script back through the database.

    Statement by statement, the way psql would, because the point of the file
    is that it needs no interpretation.
    """
    from sqlalchemy import text

    with io.open(path, encoding=u'utf-8') as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith(u'--'):
                model.Session.execute(text(line))
    model.Session.commit()
    model.Session.expire_all()


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


def _write(tmp_path, name, lines):
    path = os.path.join(str(tmp_path), name)
    with io.open(path, u'w', encoding=u'utf-8') as handle:
        handle.write(u'\n'.join(lines))
    return path


def _run(*args):
    args = list(args)
    if u'--apply' in args and u'--undo-file' not in args:
        args += [u'--undo-file',
                 os.path.join(tempfile.mkdtemp(), u'undo.sql')]
    return CliRunner().invoke(cli.nfwf_permissions,
                              [u'cleanup'] + args)


class TestReadList(object):
    """The list is pasted out of a spreadsheet, so it arrives untidy."""

    def test_it_ignores_comments_blank_lines_and_a_header(self, tmp_path):
        path = _write(tmp_path, u'accounts.txt', [
            u'# the ones the product owner marked',
            u'username',
            u'',
            u'  alice  ',
            u'bob   # keeps her grant',
            u'',
        ])
        assert cleanup.read_list(path) == [u'alice', u'bob']

    def test_it_takes_the_first_column_of_a_csv_paste(self, tmp_path):
        path = _write(tmp_path, u'accounts.txt', [
            u'alice,Alice Example,alice@example.org',
            u'bob,Bob Example,bob@example.org',
        ])
        assert cleanup.read_list(path) == [u'alice', u'bob']

    def test_it_keeps_the_order_and_drops_repeats(self, tmp_path):
        path = _write(tmp_path, u'accounts.txt',
                      [u'carol', u'alice', u'carol', u'bob'])
        assert cleanup.read_list(path) == [u'carol', u'alice', u'bob']

    def test_a_missing_file_says_so_rather_than_deleting_nothing_quietly(
            self, tmp_path):
        with pytest.raises(IOError):
            cleanup.read_list(os.path.join(str(tmp_path), u'nope.txt'))


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestAccountVerdicts(object):

    def test_an_ordinary_account_is_deletable(self):
        factories.User(name=u'stale-account')
        row, = cleanup.inspect_accounts([u'stale-account'])
        assert row[u'verdict'] == cleanup.DELETE
        assert row[u'reason'] == u''

    def test_the_site_user_is_refused(self):
        """``ckan.site_id`` names the account CKAN acts as internally. It
        looks like a leftover in the user list, which is exactly why a
        hand-written list can pick it up."""
        row, = cleanup.inspect_accounts([cleanup.site_user_name()])
        assert row[u'verdict'] == cleanup.BLOCKED
        assert u'site user' in row[u'reason']

    def test_a_platform_administrator_is_warned_about_not_refused(self):
        factories.Sysadmin(name=u'an-admin')
        row, = cleanup.inspect_accounts([u'an-admin'])
        assert row[u'verdict'] == cleanup.WARN
        assert row[u'sysadmin'] is True
        assert row in cleanup.actionable([row])

    def test_a_recently_used_account_is_warned_about(self):
        import datetime

        factories.User(name=u'still-in-use')
        user = model.User.get(u'still-in-use')
        user.last_active = datetime.datetime.utcnow() - datetime.timedelta(
            days=cleanup.RECENTLY_ACTIVE_DAYS - 1)
        model.Session.commit()

        row, = cleanup.inspect_accounts([u'still-in-use'])
        assert row[u'verdict'] == cleanup.WARN
        assert u'somebody is using it' in row[u'reason']

    def test_an_account_with_no_record_of_use_is_not_warned_about(self):
        """``last_active`` only starts part-way through this site's life, so
        an empty value is no record rather than evidence of abandonment --
        but it must not read as recent activity either."""
        factories.User(name=u'never-recorded')
        row, = cleanup.inspect_accounts([u'never-recorded'])
        assert row[u'verdict'] == cleanup.DELETE

    def test_an_already_closed_account_is_skipped(self):
        factories.User(name=u'gone-already', state=u'deleted')
        row, = cleanup.inspect_accounts([u'gone-already'])
        assert row[u'verdict'] == cleanup.SKIP
        assert cleanup.actionable([row]) == []

    def test_a_name_that_does_not_exist_is_skipped_not_an_error(self):
        row, = cleanup.inspect_accounts([u'never-existed'])
        assert row[u'verdict'] == cleanup.SKIP
        assert row[u'reason'] == u'no such account'

    def test_it_counts_what_the_account_would_take_with_it(self):
        program = factories.Group()
        grant = factories.Organization()
        user = factories.User(name=u'holds-things')
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_MEMBER)
        _assign(grant[u'id'], user[u'name'], roles.CAPACITY_EDITOR)

        row, = cleanup.inspect_accounts([u'holds-things'])
        assert row[u'rows'] == 2


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestGrantVerdicts(object):

    def test_an_empty_grant_is_deletable(self):
        grant = factories.Organization(name=u'grant-00000-nobody')
        row, = cleanup.inspect_grants([u'grant-00000-nobody'])
        assert row[u'verdict'] == cleanup.DELETE
        assert row[u'id'] == grant[u'id']

    def test_a_grant_holding_datasets_is_refused(self):
        """``organization_delete`` would either raise or quietly null
        ``owner_org``, and a dataset belonging to no grant is something no
        screen on this site can show."""
        grant = factories.Organization(name=u'grant-11111-busy')
        factories.Dataset(owner_org=grant[u'id'])

        row, = cleanup.inspect_grants([u'grant-11111-busy'])
        assert row[u'verdict'] == cleanup.BLOCKED
        assert row[u'datasets'] == 1
        assert u'still holds 1 dataset' in row[u'reason']

    def test_a_program_handed_in_as_a_grant_is_refused(self):
        """The two are both CKAN groups and a name can be mistyped. Deleting
        a program would take every grant filed under it."""
        factories.Group(name=u'a-program')
        row, = cleanup.inspect_grants([u'a-program'])
        assert row[u'verdict'] == cleanup.BLOCKED
        assert u'program, not a grant' in row[u'reason']

    def test_an_already_deleted_grant_is_skipped(self):
        factories.Organization(name=u'grant-22222-gone', state=u'deleted')
        row, = cleanup.inspect_grants([u'grant-22222-gone'])
        assert row[u'verdict'] == cleanup.SKIP

    def test_a_name_that_does_not_exist_is_skipped_not_an_error(self):
        row, = cleanup.inspect_grants([u'grant-99999-imaginary'])
        assert row[u'verdict'] == cleanup.SKIP
        assert row[u'reason'] == u'no such grant'


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestApply(object):

    def test_closing_an_account_takes_its_memberships_with_it(self):
        """A closed account still holding rows would keep showing up as a
        member of grants it can no longer reach."""
        grant = factories.Organization()
        factories.User(name=u'to-close')
        _assign(grant[u'id'], u'to-close', roles.CAPACITY_EDITOR)

        rows = cleanup.inspect_accounts([u'to-close'])
        assert cleanup.apply_accounts(rows, _recorder()[0]) == (1, [])

        assert model.User.get(u'to-close').state == u'deleted'
        live = model.Session.query(model.Member).filter(
            model.Member.table_name == u'user',
            model.Member.table_id == model.User.get(u'to-close').id,
            model.Member.state == u'active').count()
        assert live == 0

    def test_deleting_a_grant_takes_its_membership_rows_with_it(self):
        """The grant is passed by id, not name. ``_group_or_org_delete``
        matches the identifier it is handed against ``Member.group_id``, so a
        name deletes the grant and leaves its rows pointing at it -- which is
        what the site's own delete button does."""
        grant = factories.Organization(name=u'grant-33333-doomed')
        factories.User(name=u'a-member')
        _assign(grant[u'id'], u'a-member', roles.CAPACITY_EDITOR)

        rows = cleanup.inspect_grants([u'grant-33333-doomed'])
        assert cleanup.apply_grants(rows, _recorder()[0]) == (1, [])

        assert model.Group.get(grant[u'id']).state == u'deleted'
        live = model.Session.query(model.Member).filter(
            model.Member.group_id == grant[u'id'],
            model.Member.state == u'active').count()
        assert live == 0

    def test_it_never_touches_a_refused_line(self):
        grant = factories.Organization(name=u'grant-44444-busy')
        factories.Dataset(owner_org=grant[u'id'])
        site = cleanup.site_user_name()

        accounts = cleanup.inspect_accounts([site])
        grants = cleanup.inspect_grants([u'grant-44444-busy'])
        recorder = _recorder()[0]
        assert cleanup.apply_accounts(accounts, recorder) == (0, [])
        assert cleanup.apply_grants(grants, recorder) == (0, [])

        assert model.User.get(site).state == u'active'
        assert model.Group.get(grant[u'id']).state == u'active'

    def test_a_warning_does_not_stop_the_deletion(self):
        """A warning is for a person to read, not a veto -- otherwise the
        product owner could never close a stale administrator account."""
        factories.Sysadmin(name=u'stale-admin')
        rows = cleanup.inspect_accounts([u'stale-admin'])
        assert cleanup.apply_accounts(rows, _recorder()[0]) == (1, [])
        assert model.User.get(u'stale-admin').state == u'deleted'

    def test_a_grant_that_gained_a_dataset_since_the_report_is_left_alone(
            self):
        """The report and the confirmation are separated by however long the
        person takes to answer. A grant that was empty then and is not now
        must not be deleted on the strength of the older answer."""
        grant = factories.Organization(name=u'grant-66666-raced')
        rows = cleanup.inspect_grants([u'grant-66666-raced'])
        assert rows[0][u'verdict'] == cleanup.DELETE

        factories.Dataset(owner_org=grant[u'id'])

        done, stale = cleanup.apply_grants(rows, _recorder()[0])
        assert done == 0
        assert [r[u'name'] for r in stale] == [u'grant-66666-raced']
        assert model.Group.get(grant[u'id']).state == u'active'

    def test_an_account_closed_since_the_report_is_not_closed_twice(self):
        factories.User(name=u'closed-meanwhile')
        rows = cleanup.inspect_accounts([u'closed-meanwhile'])

        helpers.call_action(u'user_delete', id=u'closed-meanwhile')

        done, stale = cleanup.apply_accounts(rows, _recorder()[0])
        assert done == 0
        assert [r[u'reason'] for r in stale] == [u'already deleted']


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestCommand(object):

    def test_a_dry_run_writes_nothing(self, tmp_path):
        factories.User(name=u'survives-the-dry-run')
        path = _write(tmp_path, u'a.txt', [u'survives-the-dry-run'])

        result = _run(u'--accounts', path)

        assert result.exit_code == 0, result.output
        assert u'Dry run' in result.output
        assert model.User.get(u'survives-the-dry-run').state == u'active'

    def test_apply_needs_a_confirmation(self, tmp_path):
        factories.User(name=u'not-confirmed')
        path = _write(tmp_path, u'a.txt', [u'not-confirmed'])

        result = CliRunner().invoke(
            cli.nfwf_permissions, [u'cleanup', u'--accounts', path,
                                   u'--apply'], input=u'n\n')

        assert u'Aborted' in result.output
        assert model.User.get(u'not-confirmed').state == u'active'

    def test_apply_with_yes_closes_the_account(self, tmp_path):
        factories.User(name=u'confirmed-gone')
        path = _write(tmp_path, u'a.txt', [u'confirmed-gone'])

        result = _run(u'--accounts', path, u'--apply', u'--yes')

        assert result.exit_code == 0, result.output
        assert u'Closed 1 account(s)' in result.output
        assert model.User.get(u'confirmed-gone').state == u'deleted'

    def test_it_names_every_refusal_in_the_output(self, tmp_path):
        """With --yes nobody reads a prompt, so a refusal has to be in the
        report itself or it goes unnoticed."""
        path = _write(tmp_path, u'a.txt', [cleanup.site_user_name()])

        result = _run(u'--accounts', path, u'--apply', u'--yes')

        assert u'blocked' in result.output
        assert u'REFUSED' in result.output

    def test_it_refuses_to_run_with_no_list_at_all(self):
        result = _run()
        assert result.exit_code != 0
        assert u'nothing to do' in result.output.lower()

    def test_both_lists_run_in_one_pass(self, tmp_path):
        factories.User(name=u'both-at-once')
        factories.Organization(name=u'grant-55555-both')
        accounts = _write(tmp_path, u'a.txt', [u'both-at-once'])
        grants = _write(tmp_path, u'g.txt', [u'grant-55555-both'])

        result = _run(u'--accounts', accounts, u'--grants', grants,
                      u'--apply', u'--yes')

        assert u'Closed 1 account(s), deleted 1 grant(s)' in result.output
        assert u'search-index rebuild' in result.output


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestUndoAndSysadmin(object):
    """What a run records about itself, and the one thing it writes beyond
    the deletes."""

    def test_it_records_the_account_and_every_row_it_takes(self):
        grant = factories.Organization()
        factories.User(name=u'recorded')
        _assign(grant[u'id'], u'recorded', roles.CAPACITY_EDITOR)
        user_id = model.User.get(u'recorded').id

        recorder, buf = _recorder()
        cleanup.apply_accounts(cleanup.inspect_accounts([u'recorded']),
                               recorder)
        recorder.close()

        script = buf.getvalue()
        assert user_id in script
        assert script.count(u"UPDATE member SET state='active'") == 1
        assert script.count(u'UPDATE "user" SET state=\'active\'') == 1

    def test_it_records_a_grant_and_every_row_on_it(self):
        grant = factories.Organization(name=u'grant-88888-recorded')
        factories.User(name=u'on-it')
        _assign(grant[u'id'], u'on-it', roles.CAPACITY_EDITOR)

        # Counted rather than assumed: a factory organization comes with an
        # admin member of its own, so this grant holds more than the one row
        # the test puts on it.
        rows_on_it = model.Session.query(model.Member).filter(
            model.Member.group_id == grant[u'id'],
            model.Member.state == u'active').count()

        recorder, buf = _recorder()
        cleanup.apply_grants(
            cleanup.inspect_grants([u'grant-88888-recorded']), recorder)
        recorder.close()

        script = buf.getvalue()
        assert grant[u'id'] in script
        assert script.count(
            u"UPDATE member SET state='active'") == rows_on_it

    def test_closing_a_platform_administrator_clears_the_sysadmin_flag(self):
        """``user_delete`` leaves it set. The account cannot log in while it
        is deleted, but reactivating it would hand Platform Administrator
        back with nobody having decided to."""
        factories.Sysadmin(name=u'retired-admin')

        recorder, buf = _recorder()
        cleanup.apply_accounts(cleanup.inspect_accounts([u'retired-admin']),
                               recorder)
        recorder.close()

        user = model.User.get(u'retired-admin')
        assert user.state == u'deleted'
        assert bool(user.sysadmin) is False
        assert u'sysadmin = true' in buf.getvalue()

    def test_an_ordinary_account_gets_no_sysadmin_statement(self):
        factories.User(name=u'never-an-admin')

        recorder, buf = _recorder()
        cleanup.apply_accounts(cleanup.inspect_accounts([u'never-an-admin']),
                               recorder)
        recorder.close()

        assert u'sysadmin' not in buf.getvalue()

    def test_the_script_puts_the_account_and_its_rows_back(self, tmp_path):
        grant = factories.Organization(name=u'grant-99999-undone')
        factories.User(name=u'undone')
        _assign(grant[u'id'], u'undone', roles.CAPACITY_EDITOR)
        user_id = model.User.get(u'undone').id
        accounts = _write(tmp_path, u'a.txt', [u'undone'])
        path = os.path.join(str(tmp_path), u'undo.sql')

        _run(u'--accounts', accounts, u'--apply', u'--yes',
             u'--undo-file', path)
        assert model.User.get(u'undone').state == u'deleted'

        _replay(path)

        assert model.User.get(u'undone').state == u'active'
        assert model.Session.query(model.Member).filter(
            model.Member.table_id == user_id,
            model.Member.state == u'active').count() == 1

    def test_the_script_puts_a_platform_administrator_back_as_one(self,
                                                                  tmp_path):
        factories.Sysadmin(name=u'restored-admin')
        accounts = _write(tmp_path, u'a.txt', [u'restored-admin'])
        path = os.path.join(str(tmp_path), u'undo.sql')

        _run(u'--accounts', accounts, u'--apply', u'--yes',
             u'--undo-file', path)
        assert bool(model.User.get(u'restored-admin').sysadmin) is False

        _replay(path)

        user = model.User.get(u'restored-admin')
        assert user.state == u'active'
        assert bool(user.sysadmin) is True

    def test_a_run_that_cannot_record_itself_does_not_start(self, tmp_path):
        factories.User(name=u'unrecorded')
        accounts = _write(tmp_path, u'a.txt', [u'unrecorded'])
        unwritable = os.path.join(str(tmp_path), u'no', u'such', u'undo.sql')

        result = _run(u'--accounts', accounts, u'--apply', u'--yes',
                      u'--undo-file', unwritable)

        assert result.exit_code != 0
        assert model.User.get(u'unrecorded').state == u'active'

    def test_it_refuses_to_overwrite_an_existing_undo_file(self, tmp_path):
        """The second command must not erase the first one's record.

        Both are run against the same database one after the other, and the
        documented paths are fixed, so pointing the second at the file the
        first just wrote is an easy slip -- and it would destroy the only
        record of what the first did.
        """
        factories.User(name=u'first-run')
        factories.User(name=u'second-run')
        path = os.path.join(str(tmp_path), u'undo.sql')

        _run(u'--accounts', _write(tmp_path, u'a.txt', [u'first-run']),
             u'--apply', u'--yes', u'--undo-file', path)
        first = io.open(path, encoding=u'utf-8').read()
        assert model.User.get(u'first-run').state == u'deleted'

        result = _run(u'--accounts', _write(tmp_path, u'b.txt',
                                            [u'second-run']),
                      u'--apply', u'--yes', u'--undo-file', path)

        assert result.exit_code != 0
        # The second run did not start, and the first file is untouched.
        assert model.User.get(u'second-run').state == u'active'
        assert io.open(path, encoding=u'utf-8').read() == first

    def test_a_dry_run_writes_no_undo_file(self, tmp_path):
        factories.User(name=u'not-touched')
        accounts = _write(tmp_path, u'a.txt', [u'not-touched'])
        path = os.path.join(str(tmp_path), u'undo.sql')

        _run(u'--accounts', accounts, u'--undo-file', path)

        assert not os.path.exists(path)
