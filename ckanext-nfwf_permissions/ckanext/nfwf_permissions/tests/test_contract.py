# encoding: utf-8
"""Tests for the Task 117/126 API contract.

These pin the *shape* of the contract, not the stub data. They should keep
passing unchanged when the fixture bodies are replaced with real database
access -- if one of them starts failing then, the contract has been broken and
the front end will break with it.
"""
import pytest

import ckan.tests.helpers as helpers
import ckan.tests.factories as factories
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles
from ckanext.nfwf_permissions.logic import validators


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
        (None, []),
        (u'', []),
        (u'a', [u'a']),
        (u'a,b', [u'a', u'b']),
        (u' a , b ', [u'a', u'b']),
        ([u'a', u'b'], [u'a', u'b']),
        ([u'a', u'a'], [u'a']),
    ])
    def test_id_list_coercion(self, value, expected):
        assert validators.nfwf_id_list(value) == expected

    def test_id_list_rejects_non_strings(self):
        with pytest.raises(toolkit.Invalid):
            validators.nfwf_id_list([1, 2])

    def test_status_list_rejects_unknown_status(self):
        with pytest.raises(toolkit.Invalid):
            validators.nfwf_status_list([u'active', u'banished'])

    def test_role_rejects_retired_role(self):
        # "Grant Admin" and "Grant Member" are retired by the redesign.
        with pytest.raises(toolkit.Invalid):
            validators.nfwf_role(u'grant_admin')


@pytest.mark.usefixtures(u'with_plugins')
class TestUserList(object):

    def test_hides_deactivated_and_rejected_by_default(self):
        result = helpers.call_action(u'nfwf_user_list')
        statuses = {user[u'status'] for user in result[u'results']}
        assert roles.STATUS_DEACTIVATED not in statuses
        assert roles.STATUS_REJECTED not in statuses

    def test_statuses_filter_opts_them_back_in(self):
        result = helpers.call_action(
            u'nfwf_user_list', statuses=[roles.STATUS_DEACTIVATED])
        assert result[u'count'] >= 1
        assert all(user[u'status'] == roles.STATUS_DEACTIVATED
                   for user in result[u'results'])

    def test_default_page_size_is_twenty(self):
        result = helpers.call_action(u'nfwf_user_list')
        assert result[u'limit'] == 20

    def test_count_is_the_total_not_the_page(self):
        everything = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES)
        paged = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES, limit=1)
        assert paged[u'count'] == everything[u'count']
        assert len(paged[u'results']) == 1

    def test_offset_pages_through(self):
        first = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES, limit=1)
        second = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES, limit=1, offset=1)
        assert first[u'results'][0][u'id'] != second[u'results'][0][u'id']

    def test_role_filter(self):
        result = helpers.call_action(
            u'nfwf_user_list', role=roles.GRANT_EDITOR)
        assert result[u'count'] >= 1
        assert all(user[u'role'] == roles.GRANT_EDITOR
                   for user in result[u'results'])

    def test_search_matches_email(self):
        result = helpers.call_action(u'nfwf_user_list', q=u'nfwf.org')
        assert result[u'count'] >= 1

    def test_rejects_unknown_role_filter(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_list', role=u'grant_admin')

    def test_rejects_negative_limit(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_list', limit=-1)

    def test_every_row_has_the_columns_the_screen_needs(self):
        result = helpers.call_action(
            u'nfwf_user_list', statuses=roles.STATUSES)
        expected = {
            u'id', u'name', u'display_name', u'email', u'status',
            u'status_label', u'last_login', u'role', u'role_label',
            u'programs', u'grants',
        }
        for user in result[u'results']:
            assert expected.issubset(set(user))


@pytest.mark.usefixtures(u'with_plugins')
class TestRoleOptions(object):

    def test_returns_every_role_with_its_label(self):
        result = helpers.call_action(u'nfwf_role_options')
        assert [option[u'value'] for option in result[u'roles']] == roles.ROLES
        assert all(option[u'label'] for option in result[u'roles'])

    def test_returns_programs_for_the_checkbox_list(self):
        result = helpers.call_action(u'nfwf_role_options')
        assert result[u'programs']
        assert all({u'id', u'title'}.issubset(set(program))
                   for program in result[u'programs'])


@pytest.mark.usefixtures(u'with_plugins')
class TestRoleSet(object):

    def test_assigns_a_program_role(self):
        options = helpers.call_action(u'nfwf_role_options')
        program_id = options[u'programs'][0][u'id']

        result = helpers.call_action(
            u'nfwf_user_role_set', id=u'dyork',
            role=roles.PROGRAM_READER, program_ids=[program_id])

        assert result[u'role'] == roles.PROGRAM_READER
        assert [p[u'id'] for p in result[u'programs']] == [program_id]
        assert result[u'assignments_in_effect'] is True

    def test_switching_away_from_grant_editor_clears_the_grants(self):
        options = helpers.call_action(u'nfwf_role_options')
        program_id = options[u'programs'][0][u'id']

        result = helpers.call_action(
            u'nfwf_user_role_set', id=u'dyork',
            role=roles.PROGRAM_ADMIN, program_ids=[program_id])

        # Leaving an 'editor' membership behind would leave real edit rights.
        assert result[u'grants'] == []

    def test_platform_admin_retains_assignments_but_they_are_superseded(self):
        result = helpers.call_action(
            u'nfwf_user_role_set', id=u'dyork', role=roles.PLATFORM_ADMIN)

        assert result[u'role'] == roles.PLATFORM_ADMIN
        assert result[u'grants'], (
            u'grants should be kept so a later demotion restores them')
        assert result[u'assignments_in_effect'] is False

    def test_platform_admin_rejects_assignments(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=u'dyork',
                role=roles.PLATFORM_ADMIN, program_ids=[u'fixture-program-ncrf'])

    def test_program_role_requires_a_program(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=u'dyork', role=roles.PROGRAM_ADMIN)

    def test_grant_editor_requires_a_grant(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=u'dyork', role=roles.GRANT_EDITOR)

    def test_grant_role_rejects_programs(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=u'dyork', role=roles.GRANT_EDITOR,
                grant_ids=[u'fixture-grant-66072'],
                program_ids=[u'fixture-program-ncrf'])

    def test_role_is_required(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_role_set', id=u'dyork')

    def test_unknown_program_id_is_rejected(self):
        # Must not save as program_admin-with-no-programs.
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=u'dyork', role=roles.PROGRAM_ADMIN,
                program_ids=[u'no-such-program'])

    def test_unknown_grant_id_is_rejected(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_role_set', id=u'dyork', role=roles.GRANT_EDITOR,
                grant_ids=[u'fixture-grant-66072', u'no-such-grant'])

    def test_unknown_user_is_not_found(self):
        with pytest.raises(toolkit.ObjectNotFound):
            helpers.call_action(
                u'nfwf_user_role_set', id=u'nobody',
                role=roles.PLATFORM_ADMIN)


@pytest.mark.usefixtures(u'with_plugins')
class TestAccountStatusActions(object):

    def test_approve_makes_an_account_active(self):
        result = helpers.call_action(u'nfwf_user_approve', id=u'aquimby')
        assert result[u'status'] == roles.STATUS_ACTIVE
        assert result[u'status_label'] == u'Active'

    def test_reject_is_distinct_from_deactivate(self):
        rejected = helpers.call_action(u'nfwf_user_reject', id=u'aquimby')
        deactivated = helpers.call_action(
            u'nfwf_user_deactivate', id=u'aquimby')
        assert rejected[u'status'] != deactivated[u'status']

    def test_id_is_required(self):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_approve')


@pytest.mark.usefixtures(u'with_plugins', u'clean_db')
class TestAuthorization(object):
    """Platform Administrator only, for every action in the contract."""

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
    def test_ordinary_user_is_refused(self, action):
        user = factories.User()
        with pytest.raises(toolkit.NotAuthorized):
            helpers.call_action(
                action,
                context={u'user': user[u'name'], u'ignore_auth': False},
                id=u'dyork', role=roles.PLATFORM_ADMIN)

    @pytest.mark.parametrize(u'action', ACTIONS)
    def test_sysadmin_is_allowed(self, action):
        # A Platform Administrator is a CKAN sysadmin, and CKAN's sysadmin
        # short-circuit runs before our auth functions. If this ever fails,
        # something has added @auth_sysadmins_check -- see logic/auth.py.
        sysadmin = factories.Sysadmin()
        helpers.call_action(
            action,
            context={u'user': sysadmin[u'name'], u'ignore_auth': False},
            id=u'dyork', role=roles.PLATFORM_ADMIN)
