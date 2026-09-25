# encoding: utf-8
"""Tests for the Q3 migration report.

The report is the artifact the product owner and the UI developer sign off
on, so what matters is
that it classifies each assignment the way the decisions in the plan say it
should, and that it never overstates what a migration would actually write.

``migration`` only reads. The one thing that writes is ``--apply``, and its
scope is tested here too: it must touch the droppable rows and nothing else.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model

from ckanext.nfwf_permissions import migration, roles


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


class World(object):
    """One account per interesting shape."""

    def __init__(self):
        self.program = factories.Group(title=u'A Program')
        self.other_program = factories.Group(title=u'Another Program')
        self.grant = self._grant(self.program[u'id'], u'In Program')
        self.grant_2 = self._grant(self.program[u'id'], u'Also In Program')
        self.orphan = self._grant(u'', u'No Program')

        # Straightforward: one role, nothing to decide.
        self.editor = factories.User(name=u'plain-editor')
        _assign(self.grant[u'id'], self.editor[u'name'],
                roles.CAPACITY_EDITOR)

        self.reader = factories.User(name=u'plain-reader')
        _assign(self.program[u'id'], self.reader[u'name'],
                roles.CAPACITY_MEMBER)

        self.program_admin = factories.User(name=u'plain-program-admin')
        _assign(self.program[u'id'], self.program_admin[u'name'],
                roles.CAPACITY_ADMIN)

        # Holds both scopes: the 116-account case.
        self.dual = factories.User(name=u'dual-scope')
        _assign(self.program[u'id'], self.dual[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(self.grant[u'id'], self.dual[u'name'],
                roles.CAPACITY_EDITOR)

        # A retired capacity on a real person.
        self.retired = factories.User(name=u'holds-retired')
        _assign(self.grant[u'id'], self.retired[u'name'],
                roles.CAPACITY_MEMBER)

        # A retired capacity on a Platform Administrator: droppable.
        self.service = factories.Sysadmin(name=u'service-account')
        _assign(self.grant[u'id'], self.service[u'name'],
                roles.CAPACITY_ADMIN)
        _assign(self.grant_2[u'id'], self.service[u'name'],
                roles.CAPACITY_ADMIN)

    @staticmethod
    def _grant(program_id, title):
        return factories.Organization(title=title, extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': program_id}])


@pytest.fixture
def world(clean_db):
    return World()


def _rows_for(plan_data, account_name):
    return [row for row in plan_data[u'assignments']
            if row[u'account'] == account_name]


def _account(plan_data, account_name):
    for account in plan_data[u'accounts']:
        if account[u'account'] == account_name:
            return account
    raise AssertionError(u'no such account in the plan: %s' % account_name)


@pytest.mark.usefixtures(u'with_plugins')
class TestDispositions(object):

    def test_a_grant_editor_is_kept_untouched(self, world):
        rows = _rows_for(migration.plan(), world.editor[u'name'])

        assert [row[u'disposition'] for row in rows] == [migration.KEEP]
        assert rows[0][u'proposed_role'] == u'Grant Editor'

    def test_a_program_member_becomes_a_program_reader(self, world):
        rows = _rows_for(migration.plan(), world.reader[u'name'])

        assert rows[0][u'disposition'] == migration.KEEP
        assert rows[0][u'proposed_role'] == u'Program Reader/Member'

    def test_a_program_admin_becomes_a_program_administrator(self, world):
        rows = _rows_for(migration.plan(), world.program_admin[u'name'])

        assert rows[0][u'disposition'] == migration.KEEP
        assert rows[0][u'proposed_role'] == u'Program Administrator'

    def test_a_retired_capacity_on_a_real_person_needs_a_decision(self, world):
        rows = _rows_for(migration.plan(), world.retired[u'name'])

        assert rows[0][u'disposition'] == migration.DECIDE
        assert rows[0][u'proposed_role'] == u''

    def test_a_retired_capacity_on_a_platform_admin_is_dropped(self, world):
        rows = _rows_for(migration.plan(), world.service[u'name'])

        assert {row[u'disposition'] for row in rows} == {migration.DROP}
        assert len(rows) == 2

    def test_dropping_is_justified_by_there_being_nothing_to_restore(
            self, world):
        """The settled rule retains a Platform Admin's assignments.

        These are the exception, and the note has to say why: a capacity the
        model no longer has cannot be restored to anything.
        """
        rows = _rows_for(migration.plan(), world.service[u'name'])
        assert u'nothing to restore' in rows[0][u'note']


@pytest.mark.usefixtures(u'with_plugins')
class TestAccountLevelDecisions(object):

    def test_a_dual_scope_account_needs_a_decision(self, world):
        account = _account(migration.plan(), world.dual[u'name'])

        assert account[u'dual_scope'] is True
        assert account[u'disposition'] == migration.DECIDE
        assert u'both a program and a grant' in account[u'reason']

    def test_the_decision_propagates_to_every_row(self, world):
        """A row that looks fine alone is still contingent on the account."""
        rows = _rows_for(migration.plan(), world.dual[u'name'])

        assert len(rows) == 2
        assert {row[u'disposition'] for row in rows} == {migration.DECIDE}

    def test_it_reports_what_each_side_of_the_decision_costs(self, world):
        """The whole point: make the trade concrete rather than abstract."""
        account = _account(migration.plan(), world.dual[u'name'])

        # Two grants sit in that program, and one of them is editable.
        assert account[u'grants_visible_via_programs'] == 2
        assert account[u'grants_editable'] == 1

    def test_a_single_scope_account_needs_no_decision(self, world):
        for user in (world.editor, world.reader, world.program_admin):
            account = _account(migration.plan(), user[u'name'])
            assert account[u'disposition'] == migration.KEEP, user[u'name']
            assert account[u'dual_scope'] is False

    def test_a_platform_admin_is_never_a_decision(self, world):
        account = _account(migration.plan(), world.service[u'name'])

        assert account[u'disposition'] == migration.KEEP
        assert u'retained but not consulted' in account[u'reason']


@pytest.mark.usefixtures(u'with_plugins')
class TestTheOtherLists(object):

    def test_orphan_grants_are_reported(self, world):
        names = {grant[u'group_name']
                 for grant in migration.plan()[u'orphan_grants']}

        assert world.orphan[u'name'] in names
        assert world.grant[u'name'] not in names

    def test_an_empty_owner_group_counts_as_orphaned(self, world):
        """Production's 31 are all this spelling, not a missing row."""
        assert world.orphan[u'name'] in {
            g[u'group_name'] for g in migration.orphan_grants()}

    def test_non_active_holders_are_reported(self, world):
        model.User.get(world.reader[u'id']).delete()
        model.Session.commit()

        holders = {a[u'account']
                   for a in migration.plan()[u'inactive_holders']}
        assert world.reader[u'name'] in holders

    def test_rows_on_deleted_groups_are_excluded_but_counted(self, world):
        """Otherwise the totals will not reconcile with a plain SQL count.

        The group's state is set directly rather than through
        ``organization_delete``, which also marks the member rows deleted and
        so cannot produce this shape. Production nonetheless has 13 active
        member rows sitting on deleted groups -- 11 of them grant-``admin`` on
        the two service accounts -- so however they arose, the report has to
        account for them.
        """
        before = migration.plan()
        group = model.Group.get(world.grant_2[u'id'])
        group.state = u'deleted'
        model.Session.commit()
        after = migration.plan()

        assert after[u'totals'][u'assignments'] < \
            before[u'totals'][u'assignments']
        assert after[u'totals'][u'excluded_rows'] > \
            before[u'totals'][u'excluded_rows']


@pytest.mark.usefixtures(u'with_plugins')
class TestTotals(object):

    def test_the_dispositions_account_for_every_row(self, world):
        totals = migration.plan()[u'totals']

        assert (totals[u'keep'] + totals[u'drop'] + totals[u'decide'] ==
                totals[u'assignments'])

    def test_droppable_is_exactly_the_drop_rows(self, world):
        plan_data = migration.plan()

        assert len(migration.droppable(plan_data)) == \
            plan_data[u'totals'][u'drop']
        assert all(row[u'disposition'] == migration.DROP
                   for row in migration.droppable(plan_data))

    def test_dual_scope_count_excludes_platform_admins(self, world):
        """A sysadmin holding both scopes is not a decision."""
        _assign(world.other_program[u'id'], world.service[u'name'],
                roles.CAPACITY_MEMBER)
        totals = migration.plan()[u'totals']

        assert totals[u'dual_scope_accounts'] == 1  # only `dual-scope`


@pytest.mark.usefixtures(u'with_plugins')
class TestAnalysisNeverWrites(object):

    def test_building_the_plan_changes_nothing(self, world):
        def snapshot():
            return sorted(
                (m.table_id, m.group_id, m.capacity, m.state)
                for m in model.Session.query(model.Member).filter(
                    model.Member.table_name == u'user'))

        before = snapshot()
        migration.plan()
        migration.orphan_grants()
        migration.excluded_rows()

        assert snapshot() == before
