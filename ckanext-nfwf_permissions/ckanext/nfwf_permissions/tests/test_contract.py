# encoding: utf-8
"""Tests for the Task 117/126 API contract.

These pin the *shape* of the contract, not the data behind it. They were
written against the stub implementation and kept deliberately when the bodies
started reading the database -- if one of them fails now, the contract has been
broken and the front end will break with it.

What changed when the stubs went away is only the setup: the `population`
fixture builds real programs, grants and accounts where the fixture module used
to supply them. The assertions are the same.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles
from ckanext.nfwf_permissions.logic import validators


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


class Population(object):
    """A small but complete site: every role and every account status."""

    def __init__(self):
        self.program_a = factories.Group(title=u'Program A')
        self.program_b = factories.Group(title=u'Program B')

        self.grant_1 = self._grant(self.program_a[u'id'], u'Grant One')
        self.grant_2 = self._grant(self.program_a[u'id'], u'Grant Two')

        # A Grant Editor with two grants, so switching roles has something to
        # clear and promoting to Platform Administrator has something to retain.
        self.editor = factories.User(name=u'reditor', email=u'editor@example.org')
        _assign(self.grant_1[u'id'], self.editor[u'name'],
                roles.CAPACITY_EDITOR)
        _assign(self.grant_2[u'id'], self.editor[u'name'],
                roles.CAPACITY_EDITOR)

        # Awaiting review: a new sign-in that has not been approved.
        self.pending = factories.User(name=u'rpending')
        model.User.get(self.pending[u'id']).set_pending()
        model.Session.commit()

        # One of each remaining status, so the filters have something to find.
        self.sysadmin = factories.Sysadmin()
        self.deactivated = factories.User(name=u'rdeactivated')
        helpers.call_action(
            u'nfwf_user_deactivate', id=self.deactivated[u'name'])

        # An @nfwf.org address, for the email search.
        self.nfwf_staff = factories.User(email=u'staff@example.org')

    @staticmethod
    def _grant(program_id, title):
        return factories.Organization(title=title, extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': program_id}])


@pytest.fixture
def population(clean_db):
    return Population()


class TestRolesVocabulary(object):
    """The role tables have to stay in step with each other."""

    def test_every_role_has_a_label_and_a_scope(self):
        assert set(roles.ROLE_LABELS) == set(roles.ROLES)
        assert set(roles.ROLE_SCOPE) == set(roles.ROLES)
        assert set(roles.ROLE_STORAGE) == set(roles.ROLES)

    def test_every_status_has_a_label_and_a_storage_mapping(self):
        assert set(roles.STATUS_LABELS) == set(roles.STATUSES)
        assert set(roles.STATUS_STORAGE) == set(roles.STATUSES)

    def test_exactly_one_role_takes_no_assignments(self):
        siteless = [r for r in roles.ROLES if roles.ROLE_SCOPE[r] is None]
        assert siteless == [roles.PLATFORM_ADMIN]

    def test_platform_admin_assignments_are_not_consulted(self):
        assert roles.assignments_in_effect(roles.PLATFORM_ADMIN) is False
        assert roles.assignments_in_effect(roles.GRANT_EDITOR) is True

    def test_default_visible_statuses_hide_the_gone_accounts(self):
        assert roles.STATUS_DEACTIVATED not in roles.DEFAULT_VISIBLE_STATUSES
        assert roles.STATUS_REJECTED not in roles.DEFAULT_VISIBLE_STATUSES


class TestValidators(object):

    @pytest.mark.parametrize(u'value,expected', [
        (u'a,b', [u'a', u'b']),
        ([u'a', u'b'], [u'a', u'b']),
        (u'', []),
        (None, []),
    ])
    def test_id_list_coercion(self, value, expected):
        assert validators.nfwf_id_list(value) == expected

    def test_id_list_rejects_non_strings(self):
        with pytest.raises(toolkit.Invalid):
            validators.nfwf_id_list([{u'id': u'a'}])

    def test_status_list_rejects_unknown_status(self):
        with pytest.raises(toolkit.Invalid):
            validators.nfwf_status_list([u'archived'])

    def test_role_rejects_retired_role(self):
        with pytest.raises(toolkit.Invalid):
            validators.nfwf_role(u'grant_admin')


@pytest.mark.usefixtures(u'with_plugins')
class TestUserList(object):

    def test_hides_deactivated_and_rejected_by_default(self, population):
        result = helpers.call_action(u'nfwf_user_list')
        statuses = {user[u'status'] for user in result[u'results']}
        assert roles.STATUS_DEACTIVATED not in statuses
        assert roles.STATUS_REJECTED not in statuses

    def test_statuses_filter_opts_them_back_in(self, population):
        result = helpers.call_action(
            u'nfwf_user_list', statuses=[roles.STATUS_DEACTIVATED])
        assert result[u'count'] >= 1
        assert all(user[u'status'] == roles.STATUS_DEACTIVATED
                   for user in result[u'results'])

    def test_default_page_size_is_twenty(self, population):
        result = helpers.call_action(u'nfwf_user_list')
        assert result[u'limit'] == 20

    def test_count_is_the_total_not_the_page(self, population):
        everything = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES)
        paged = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES, limit=1)
        assert paged[u'count'] == everything[u'count']
        assert len(paged[u'results']) == 1

    def test_offset_pages_through(self, population):
        first = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES, limit=1)
        second = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES, limit=1, offset=1)
        assert first[u'results'][0][u'id'] != second[u'results'][0][u'id']

    def test_role_filter(self, population):
        result = helpers.call_action(
            u'nfwf_user_list', role=roles.GRANT_EDITOR)
        assert result[u'count'] >= 1
        assert all(user[u'role'] == roles.GRANT_EDITOR
                   for user in result[u'results'])

    def test_search_matches_email(self, population):
        result = helpers.call_action(u'nfwf_user_list', q=u'nfwf.org')
        assert result[u'count'] >= 1

    def test_program_filter(self, population):
        """Now that memberships are real, this can be asserted properly."""
        _assign(population.program_a[u'id'], population.nfwf_staff[u'name'],
                roles.CAPACITY_MEMBER)
        result = helpers.call_action(
            u'nfwf_user_list', program_id=population.program_a[u'id'])

        names = {user[u'name'] for user in result[u'results']}
        assert population.nfwf_staff[u'name'] in names
        assert population.editor[u'name'] not in names

    def test_rejects_unknown_role_filter(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_list', role=u'grant_admin')

    def test_rejects_negative_limit(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_list', limit=-1)

    def test_every_row_has_the_columns_the_screen_needs(self, population):
        result = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES)
        expected = {
            u'id', u'name', u'display_name', u'email', u'status',
            u'status_label', u'last_login', u'role', u'role_label',
            u'programs', u'grants',
        }
        assert result[u'results']
        for user in result[u'results']:
            assert expected.issubset(set(user))

    def test_no_stub_marker_survives(self, population):
        """The stub bodies flagged themselves; the real ones must not."""
        result = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES)
        assert u'stub' not in result
        assert all(u'stub' not in user for user in result[u'results'])


@pytest.mark.usefixtures(u'with_plugins')
class TestRoleOptions(object):

    def test_returns_every_role_with_its_label(self, population):
        result = helpers.call_action(u'nfwf_role_options')
        assert [option[u'value'] for option in result[u'roles']] == roles.ROLES
        assert all(option[u'label'] for option in result[u'roles'])

    def test_returns_programs_for_the_checkbox_list(self, population):
        result = helpers.call_action(u'nfwf_role_options')
        assert result[u'programs']
        assert all({u'id', u'title'}.issubset(set(program))
                   for program in result[u'programs'])

    def test_returns_programs_not_grants(self, population):
        """~570 grants is not a checkbox list; only programs come back."""
        result = helpers.call_action(u'nfwf_role_options')
        ids = {program[u'id'] for program in result[u'programs']}
        assert population.program_a[u'id'] in ids
        assert population.grant_1[u'id'] not in ids


@pytest.mark.usefixtures(u'with_plugins')
class TestRoleSet(object):

    def test_assigns_a_program_role(self, population):
        program_id = population.program_a[u'id']

        result = helpers.call_action(
            u'nfwf_user_role_set', id=population.editor[u'name'],
            role=roles.PROGRAM_READER, program_ids=[program_id])

        assert result[u'role'] == roles.PROGRAM_READER
        assert [p[u'id'] for p in result[u'programs']] == [program_id]
        assert result[u'assignments_in_effect'] is True

    def test_the_assignment_is_actually_stored(self, population):
        """Not just echoed back: re-read it through a separate action."""
        program_id = population.program_b[u'id']
        helpers.call_action(
            u'nfwf_user_role_set', id=population.editor[u'name'],
            role=roles.PROGRAM_ADMIN, program_ids=[program_id])

        shown = helpers.call_action(
            u'nfwf_user_role_show', id=population.editor[u'name'])

        assert shown[u'role'] == roles.PROGRAM_ADMIN
        assert [p[u'id'] for p in shown[u'programs']] == [program_id]

    def test_switching_away_from_grant_editor_clears_the_grants(
            self, population):
        result = helpers.call_action(
            u'nfwf_user_role_set', id=population.editor[u'name'],
            role=roles.PROGRAM_ADMIN,
            program_ids=[population.program_a[u'id']])

        # Leaving an 'editor' membership behind would leave real edit rights.
        assert result[u'grants'] == []

    def test_platform_admin_retains_assignments_but_they_are_superseded(
            self, population):
        result = helpers.call_action(
            u'nfwf_user_role_set', id=population.editor[u'name'],
            role=roles.PLATFORM_ADMIN)

        assert result[u'role'] == roles.PLATFORM_ADMIN
        assert result[u'grants'], (
            u'grants should be kept so a later demotion restores them')
        assert result[u'assignments_in_effect'] is False

    def test_demoting_a_platform_admin_restores_what_they_had(
            self, population):
        """The point of retaining rather than deleting."""
        grants_before = helpers.call_action(
            u'nfwf_user_role_show', id=population.editor[u'name'])[u'grants']

        helpers.call_action(
            u'nfwf_user_role_set', id=population.editor[u'name'],
            role=roles.PLATFORM_ADMIN)
        restored = helpers.call_action(
            u'nfwf_user_role_set', id=population.editor[u'name'],
            role=roles.GRANT_EDITOR,
            grant_ids=[g[u'id'] for g in grants_before])

        assert restored[u'role'] == roles.GRANT_EDITOR
        assert [g[u'id'] for g in restored[u'grants']] == \
            [g[u'id'] for g in grants_before]

    def test_platform_admin_rejects_assignments(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'],
                role=roles.PLATFORM_ADMIN,
                program_ids=[population.program_a[u'id']])

    def test_program_role_requires_a_program(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'],
                role=roles.PROGRAM_ADMIN)

    def test_grant_editor_requires_a_grant(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'],
                role=roles.GRANT_EDITOR)

    def test_grant_role_rejects_programs(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'],
                role=roles.GRANT_EDITOR,
                grant_ids=[population.grant_1[u'id']],
                program_ids=[population.program_a[u'id']])

    def test_role_is_required(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'])

    def test_unknown_program_id_is_rejected(self, population):
        # Must not save as program_admin-with-no-programs.
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'],
                role=roles.PROGRAM_ADMIN, program_ids=[u'no-such-program'])

    def test_unknown_grant_id_is_rejected(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'],
                role=roles.GRANT_EDITOR,
                grant_ids=[population.grant_1[u'id'], u'no-such-grant'])

    def test_a_program_id_is_not_a_grant_id(self, population):
        """The two lists are resolved against different kinds of group."""
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'],
                role=roles.GRANT_EDITOR,
                grant_ids=[population.program_a[u'id']])

    def test_a_partial_failure_saves_nothing(self, population):
        """One bad id must not leave the role half-applied."""
        before = helpers.call_action(
            u'nfwf_user_role_show', id=population.editor[u'name'])

        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=population.editor[u'name'],
                role=roles.PROGRAM_ADMIN,
                program_ids=[population.program_a[u'id'], u'no-such-program'])

        after = helpers.call_action(
            u'nfwf_user_role_show', id=population.editor[u'name'])
        assert after[u'role'] == before[u'role']
        assert after[u'grants'] == before[u'grants']
        assert after[u'programs'] == before[u'programs']

    def test_unknown_user_is_not_found(self, population):
        with pytest.raises(toolkit.ObjectNotFound):
            helpers.call_action(
                u'nfwf_user_role_set', id=u'nobody',
                role=roles.PLATFORM_ADMIN)


@pytest.mark.usefixtures(u'with_plugins')
class TestAccountStatusActions(object):

    def test_approve_makes_an_account_active(self, population):
        result = helpers.call_action(
            u'nfwf_user_approve', id=population.pending[u'name'])
        assert result[u'status'] == roles.STATUS_ACTIVE
        assert result[u'status_label'] == u'Active'

    def test_approval_is_actually_stored(self, population):
        helpers.call_action(
            u'nfwf_user_approve', id=population.pending[u'name'])

        assert model.User.get(population.pending[u'id']).state == u'active'

    def test_reject_is_distinct_from_deactivate(self, population):
        rejected = helpers.call_action(
            u'nfwf_user_reject', id=population.pending[u'name'])
        deactivated = helpers.call_action(
            u'nfwf_user_deactivate', id=population.pending[u'name'])
        assert rejected[u'status'] != deactivated[u'status']

    def test_both_gone_statuses_share_ckans_deleted_state(self, population):
        """Which is why plugin_extras has to tell them apart."""
        helpers.call_action(
            u'nfwf_user_reject', id=population.pending[u'name'])
        user = model.User.get(population.pending[u'id'])

        assert user.state == u'deleted'
        assert helpers.call_action(
            u'nfwf_user_list', statuses=[roles.STATUS_REJECTED],
            q=population.pending[u'name'])[u'count'] == 1

    def test_id_is_required(self, population):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_approve')


@pytest.mark.usefixtures(u'with_plugins')
class TestAuthorization(object):
    """Closed to an ordinary account, and open to a sysadmin, for every action.

    The middle case -- a Program Administrator, who reaches four of these seven
    and is scoped within them -- is in ``test_spec_compliance.py``. These two
    are the outer bounds and hold whatever that scoping does.
    """

    ACTIONS = [
        u'nfwf_user_list',
        u'nfwf_user_role_show',
        u'nfwf_user_role_set',
        u'nfwf_user_approve',
        u'nfwf_user_reject',
        u'nfwf_user_deactivate',
        u'nfwf_role_options',
    ]

    @pytest.mark.parametrize(u'action', ACTIONS)
    def test_ordinary_user_is_refused(self, action, population):
        user = factories.User()
        with pytest.raises(toolkit.NotAuthorized):
            helpers.call_action(
                action,
                context={u'user': user[u'name'], u'ignore_auth': False},
                id=population.editor[u'name'], role=roles.PLATFORM_ADMIN)

    @pytest.mark.parametrize(u'action', ACTIONS)
    def test_sysadmin_is_allowed(self, action, population):
        # A Platform Administrator is a CKAN sysadmin, and CKAN's sysadmin
        # short-circuit runs before our auth functions. If this ever fails,
        # something has added @auth_sysadmins_check -- see logic/auth.py.
        helpers.call_action(
            action,
            context={u'user': population.sysadmin[u'name'],
                     u'ignore_auth': False},
            id=population.editor[u'name'], role=roles.PLATFORM_ADMIN)
