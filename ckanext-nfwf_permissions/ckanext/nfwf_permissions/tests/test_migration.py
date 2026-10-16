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

        # A program membership beside a grant: the 114-account case. The
        # membership is dropped, so this resolves to Grant Editor by rule and
        # is nobody's decision.
        self.member_and_grant = factories.User(name=u'member-and-grant')
        _assign(self.program[u'id'], self.member_and_grant[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(self.grant[u'id'], self.member_and_grant[u'name'],
                roles.CAPACITY_EDITOR)

        # Holds both scopes in a way the rule cannot settle: administering a
        # program while also editing a grant.
        self.dual = factories.User(name=u'dual-scope')
        _assign(self.program[u'id'], self.dual[u'name'],
                roles.CAPACITY_ADMIN)
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

    def test_the_old_program_member_role_is_dropped(self, world):
        """Settled 2026-10-02: the stopgap does not carry over.

        It used to become Program Reader, which would have handed every holder
        program-wide read of private datasets the moment the model was
        switched on -- the opposite of what the role is for.
        """
        rows = _rows_for(migration.plan(), world.reader[u'name'])

        assert rows[0][u'disposition'] == migration.DROP
        assert rows[0][u'proposed_role'] == u''
        assert u'stopgap' in rows[0][u'note']

    def test_program_reader_itself_is_not_retired(self, world):
        """Only the inheritance ends. The role is still in the model, and is
        still what a program ``member`` row means once somebody assigns one."""
        assert roles.PROGRAM_READER in roles.PROGRAM_ADMIN_ASSIGNABLE_ROLES
        assert roles.role_label(roles.PROGRAM_READER)

    def test_every_dropped_row_says_which_rule_dropped_it(self, world):
        """``--apply`` branches on this, so the three must stay apart.

        The retired-capacity rule holds only while the account is a Platform
        Administrator and is re-checked before each delete; the other two do
        not depend on the account at all. Deciding that from the row's scope
        or its note would work today and break quietly the first time either
        changes. The report needs the distinction for a second reason: two of
        the three take access away from somebody, and it has to be able to
        say which one did.
        """
        plan_data = migration.plan()
        by_rule = {}
        for row in migration.droppable(plan_data):
            by_rule.setdefault(row[u'drop_rule'], set()).add(row[u'account'])

        assert set(by_rule) == {migration.DROP_RETIRED_ON_ADMIN,
                                migration.DROP_LEGACY_MEMBERSHIP,
                                migration.DROP_RETIRED_GRANT_ROLE}
        # Membership, not equality: CKAN's built-in ``default`` sysadmin is in
        # this database too and carries rows of its own.
        assert world.service[u'name'] in by_rule[
            migration.DROP_RETIRED_ON_ADMIN]
        assert world.reader[u'name'] in by_rule[
            migration.DROP_LEGACY_MEMBERSHIP]
        assert world.retired[u'name'] in by_rule[
            migration.DROP_RETIRED_GRANT_ROLE]
        assert all(row[u'drop_rule'] == u''
                   for row in plan_data[u'assignments']
                   if row[u'disposition'] != migration.DROP)

    def test_a_program_admin_becomes_a_program_administrator(self, world):
        rows = _rows_for(migration.plan(), world.program_admin[u'name'])

        assert rows[0][u'disposition'] == migration.KEEP
        assert rows[0][u'proposed_role'] == u'Program Administrator'

    def test_a_retired_capacity_on_a_real_person_is_dropped(self, world):
        """Was a decision until 2026-10-13, when the product owner settled
        every one of them: removed, not promoted to Grant Editor."""
        rows = _rows_for(migration.plan(), world.retired[u'name'])

        assert rows[0][u'disposition'] == migration.DROP
        assert rows[0][u'drop_rule'] == migration.DROP_RETIRED_GRANT_ROLE
        assert rows[0][u'proposed_role'] == u''

    def test_an_unexpected_capacity_on_a_grant_is_asked_about_not_dropped(
            self, world):
        """No row in the real data has one, and that is the point.

        Every rule here is written for a capacity somebody chose. A value
        nobody has seen cannot be dropped as "Grant Member and Grant Admin
        are not roles in the new model", because that would not be true of
        it -- so it is reported and the row is left alone.
        """
        stranger = factories.User(name=u'holds-something-odd')
        _assign(world.grant[u'id'], stranger[u'name'], roles.CAPACITY_EDITOR)
        model.Session.query(model.Member).filter(
            model.Member.table_id == model.User.get(
                stranger[u'name']).id,
            model.Member.group_id == world.grant[u'id']).update(
                {u'capacity': u'curator'})
        model.Session.commit()

        rows = _rows_for(migration.plan(), stranger[u'name'])

        assert rows[0][u'disposition'] == migration.DECIDE
        assert rows[0][u'drop_rule'] == u''
        assert u'curator' in rows[0][u'note']

    def test_an_account_left_holding_nothing_is_said_so_not_asked_about(
            self, world):
        """Its only row is dropped, so it ends up with no role. That is the
        rule working, not a question for anybody."""
        account = _account(migration.plan(), world.retired[u'name'])

        assert account[u'disposition'] == migration.KEEP
        assert u'left with no role' in account[u'reason']
        assert account[u'retired_rows'] == 1

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

    def test_administering_a_program_while_editing_a_grant_is_a_decision(
            self, world):
        account = _account(migration.plan(), world.dual[u'name'])

        assert account[u'dual_scope'] is True
        assert account[u'disposition'] == migration.DECIDE
        assert u'Program Administrator row and a grant' in account[u'reason']

    def test_a_program_membership_beside_a_grant_is_not_a_decision(
            self, world):
        """The large group, settled by the rule rather than by a person.

        The membership is dropped and the grant row stands, so the account is
        a Grant Editor and nobody has to be asked. Before the membership was
        retired this was the single biggest source of decisions in the report.
        """
        plan_data = migration.plan()
        account = _account(plan_data, world.member_and_grant[u'name'])

        assert account[u'dual_scope'] is False
        assert account[u'disposition'] == migration.KEEP

        dispositions = {row[u'capacity']: row[u'disposition']
                        for row in _rows_for(plan_data,
                                             world.member_and_grant[u'name'])}
        assert dispositions == {roles.CAPACITY_MEMBER: migration.DROP,
                                roles.CAPACITY_EDITOR: migration.KEEP}

    def test_an_account_left_with_no_role_says_so(self, world):
        """Dropping the membership can empty an account out entirely.

        Five accounts in the production snapshot are in this position on
        2026-10-06, four of them active. It is not a decision -- the rule
        settles it -- but a report that stayed silent about it would be hiding
        the one surprising consequence.
        """
        account = _account(migration.plan(), world.reader[u'name'])

        assert account[u'disposition'] == migration.KEEP
        assert u'left with no role' in account[u'reason']

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
