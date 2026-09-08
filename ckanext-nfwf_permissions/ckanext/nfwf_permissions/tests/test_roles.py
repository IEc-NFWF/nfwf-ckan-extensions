# encoding: utf-8
"""Tests for role resolution -- the questions every auth function asks.

These run against real ``group``, ``group_extra`` and ``member`` rows rather
than mocks, because the whole point of this layer is that it agrees with what
CKAN actually stores. The fixtures mirror the production shapes that matter:
a grant whose ``owner_group`` is empty rather than absent, an account holding
both a retired grant capacity and a real one, and a sysadmin who still carries
the program rows they held before promotion.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model

from ckanext.nfwf_permissions import roles


def _program(**kwargs):
    """A CKAN group -- what the redesign calls a program."""
    return factories.Group(**kwargs)


def _grant(program_id=None, **kwargs):
    """A CKAN organization -- what the redesign calls a grant.

    ``program_id=None`` leaves the ``owner_group`` extra off entirely;
    ``program_id=u''`` reproduces the 30 production grants that carry the key
    with an empty value. Both mean "no program", and both have to work.
    """
    if program_id is not None:
        kwargs[u'extras'] = [
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': program_id}]
    return factories.Organization(**kwargs)


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestGrantToProgram(object):

    def test_resolves_by_id_and_by_name(self):
        program = _program()
        grant = _grant(program_id=program[u'id'])

        assert roles.program_id_for_grant(grant[u'id']) == program[u'id']
        assert roles.program_id_for_grant(grant[u'name']) == program[u'id']

    def test_grant_with_no_owner_group_extra_has_no_program(self):
        assert roles.program_id_for_grant(_grant()[u'id']) is None

    def test_empty_owner_group_is_no_program_not_an_empty_id(self):
        """The 30-grant case. An empty value must not resolve to a program."""
        grant = _grant(program_id=u'')

        def stored():
            return model.Session.query(model.GroupExtra).filter(
                model.GroupExtra.group_id == grant[u'id'],
                model.GroupExtra.key == roles.OWNER_GROUP_EXTRA,
                model.GroupExtra.state == u'active').first()

        if stored() is None:
            # CKAN dropped the empty extra on the way in; put it back the way
            # production holds it, since that is the shape under test.
            model.Session.add(model.GroupExtra(
                group_id=grant[u'id'], key=roles.OWNER_GROUP_EXTRA, value=u''))
            model.Session.commit()

        # Guard the guard: without a row carrying an empty value this test
        # would pass for the wrong reason, proving only that a missing extra
        # means no program -- which the test above already covers.
        assert stored().value == u''
        assert roles.program_id_for_grant(grant[u'id']) is None

    def test_unknown_and_empty_references_resolve_to_nothing(self):
        assert roles.program_id_for_grant(u'no-such-grant') is None
        assert roles.program_id_for_grant(None) is None
        assert roles.program_id_for_grant(u'') is None

    def test_a_program_is_not_a_grant(self):
        """Programs and grants share a table; the lookup must not confuse them."""
        program = _program()
        _grant(program_id=program[u'id'])

        assert roles.program_id_for_grant(program[u'id']) is None


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestGrantsInProgram(object):

    def test_returns_only_its_own_grants(self):
        program = _program()
        other = _program()
        mine = [_grant(program_id=program[u'id'])[u'id'] for _ in range(3)]
        _grant(program_id=other[u'id'])
        _grant()

        assert roles.grants_in_program(program[u'id']) == frozenset(mine)

    def test_resolves_the_program_by_name(self):
        program = _program()
        grant = _grant(program_id=program[u'id'])

        assert roles.grants_in_program(program[u'name']) == frozenset(
            [grant[u'id']])

    def test_deleted_grants_drop_out(self):
        program = _program()
        kept = _grant(program_id=program[u'id'])
        gone = _grant(program_id=program[u'id'])
        helpers.call_action(u'organization_delete', id=gone[u'id'])

        assert roles.grants_in_program(program[u'id']) == frozenset(
            [kept[u'id']])

    def test_unknown_program_has_no_grants(self):
        assert roles.grants_in_program(u'no-such-program') == frozenset()

    def test_result_is_immutable_because_it_is_shared(self):
        program = _program()
        _grant(program_id=program[u'id'])

        assert isinstance(roles.grants_in_program(program[u'id']), frozenset)


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestMemberships(object):

    def test_programs_and_grants_are_reported_separately(self):
        user = factories.User()
        program = _program()
        grant = _grant()
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_MEMBER)
        _assign(grant[u'id'], user[u'name'], roles.CAPACITY_EDITOR)

        assert roles.programs_for_user(user[u'name']) == frozenset(
            [program[u'id']])
        assert roles.grants_for_user(user[u'name']) == frozenset(
            [grant[u'id']])

    def test_capacity_filter(self):
        user = factories.User()
        admin_of = _program()
        member_of = _program()
        _assign(admin_of[u'id'], user[u'name'], roles.CAPACITY_ADMIN)
        _assign(member_of[u'id'], user[u'name'], roles.CAPACITY_MEMBER)

        assert roles.programs_for_user(
            user[u'name'], [roles.CAPACITY_ADMIN]) == frozenset(
                [admin_of[u'id']])
        assert roles.programs_for_user(user[u'name']) == frozenset(
            [admin_of[u'id'], member_of[u'id']])

    def test_deleted_memberships_do_not_count(self):
        user = factories.User()
        program = _program()
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_ADMIN)
        helpers.call_action(
            u'member_delete', id=program[u'id'], object=user[u'name'],
            object_type=u'user')

        assert roles.programs_for_user(user[u'name']) == frozenset()

    def test_memberships_on_deleted_groups_do_not_count(self):
        user = factories.User()
        program = _program()
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_ADMIN)
        helpers.call_action(u'group_delete', id=program[u'id'])

        assert roles.programs_for_user(user[u'name']) == frozenset()

    def test_accepts_a_user_object_an_id_or_a_name(self):
        user = factories.User()
        program = _program()
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_MEMBER)
        expected = frozenset([program[u'id']])

        assert roles.programs_for_user(user[u'name']) == expected
        assert roles.programs_for_user(user[u'id']) == expected
        assert roles.programs_for_user(
            model.User.get(user[u'id'])) == expected

    def test_unknown_user_holds_nothing(self):
        assert roles.programs_for_user(u'nobody') == frozenset()
        assert roles.grants_for_user(None) == frozenset()


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestUserRole(object):

    def test_no_assignments_means_no_role(self):
        assert roles.user_role(factories.User()[u'name']) is None

    def test_sysadmin_is_platform_administrator(self):
        assert roles.user_role(
            factories.Sysadmin()[u'name']) == roles.PLATFORM_ADMIN

    def test_program_admin(self):
        user = factories.User()
        _assign(_program()[u'id'], user[u'name'], roles.CAPACITY_ADMIN)

        assert roles.user_role(user[u'name']) == roles.PROGRAM_ADMIN

    def test_program_member_is_program_reader(self):
        user = factories.User()
        _assign(_program()[u'id'], user[u'name'], roles.CAPACITY_MEMBER)

        assert roles.user_role(user[u'name']) == roles.PROGRAM_READER

    def test_grant_editor(self):
        user = factories.User()
        _assign(_grant()[u'id'], user[u'name'], roles.CAPACITY_EDITOR)

        assert roles.user_role(user[u'name']) == roles.GRANT_EDITOR

    def test_retired_grant_capacities_confer_no_role(self):
        """These are the rows the migration report has to flag for a human."""
        for capacity in roles.RETIRED_GRANT_CAPACITIES:
            user = factories.User()
            _assign(_grant()[u'id'], user[u'name'], capacity)

            assert roles.user_role(user[u'name']) is None

    def test_most_privileged_assignment_wins(self):
        """Production holds combinations; resolution has to be deterministic."""
        user = factories.User()
        _assign(_program()[u'id'], user[u'name'], roles.CAPACITY_MEMBER)
        _assign(_grant()[u'id'], user[u'name'], roles.CAPACITY_EDITOR)
        assert roles.user_role(user[u'name']) == roles.PROGRAM_READER

        _assign(_program()[u'id'], user[u'name'], roles.CAPACITY_ADMIN)
        assert roles.user_role(user[u'name']) == roles.PROGRAM_ADMIN

    def test_sysadmin_supersedes_retained_assignments(self):
        """583 of the 585 grant-admin rows belong to accounts already sysadmin."""
        user = factories.Sysadmin()
        program = _program()
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_ADMIN)

        assert roles.user_role(user[u'name']) == roles.PLATFORM_ADMIN
        # Retained, not deleted -- demoting has to give the role back.
        assert roles.programs_for_user(user[u'name']) == frozenset(
            [program[u'id']])
        assert roles.assignments_in_effect(roles.PLATFORM_ADMIN) is False

    def test_a_pending_account_still_reports_its_role(self):
        """The user-management screen lists accounts awaiting approval."""
        user = factories.User()
        _assign(_program()[u'id'], user[u'name'], roles.CAPACITY_ADMIN)
        model.User.get(user[u'id']).set_pending()
        model.Session.commit()

        assert roles.user_role(user[u'name']) == roles.PROGRAM_ADMIN

    def test_unknown_user_has_no_role(self):
        assert roles.user_role(u'no-such-user') is None
        assert roles.user_role(None) is None


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestIsProgramAdminForGrant(object):

    def test_admin_of_the_owning_program(self):
        user = factories.User()
        program = _program()
        grant = _grant(program_id=program[u'id'])
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_ADMIN)

        assert roles.is_program_admin_for_grant(
            user[u'name'], grant[u'id']) is True
        assert roles.is_program_admin_for_grant(
            user[u'name'], grant[u'name']) is True

    def test_admin_of_a_different_program(self):
        user = factories.User()
        _assign(_program()[u'id'], user[u'name'], roles.CAPACITY_ADMIN)
        grant = _grant(program_id=_program()[u'id'])

        assert roles.is_program_admin_for_grant(
            user[u'name'], grant[u'id']) is False

    def test_program_reader_does_not_administer(self):
        user = factories.User()
        program = _program()
        grant = _grant(program_id=program[u'id'])
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_MEMBER)

        assert roles.is_program_admin_for_grant(
            user[u'name'], grant[u'id']) is False

    def test_a_grant_with_no_program_is_administered_by_nobody(self):
        user = factories.User()
        _assign(_program()[u'id'], user[u'name'], roles.CAPACITY_ADMIN)

        assert roles.is_program_admin_for_grant(
            user[u'name'], _grant()[u'id']) is False


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestRequestCache(object):
    """The cache must not outlive the request that filled it."""

    def test_nothing_is_cached_outside_a_request(self):
        assert roles._cache() is None
        assert roles.user_role(factories.User()[u'name']) is None

    def test_a_request_starts_with_an_empty_cache(self, app):
        user = factories.User()
        program = _program()
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_ADMIN)

        with app.flask_app.test_request_context():
            assert roles.user_role(user[u'name']) == roles.PROGRAM_ADMIN
            assert roles._cache()  # the answer was memoized

        # A second request sees none of the first request's answers. This is
        # the property a threading.local() would not have given us: there, the
        # entries above would still be sitting on the worker thread.
        with app.flask_app.test_request_context():
            assert roles._cache() == {}

    def test_a_revoked_role_is_gone_in_the_next_request(self, app):
        user = factories.User()
        program = _program()
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_ADMIN)

        with app.flask_app.test_request_context():
            assert roles.user_role(user[u'name']) == roles.PROGRAM_ADMIN

        helpers.call_action(
            u'member_delete', id=program[u'id'], object=user[u'name'],
            object_type=u'user')

        with app.flask_app.test_request_context():
            assert roles.user_role(user[u'name']) is None

    def test_clear_cache_picks_up_a_change_within_one_request(self, app):
        """What nfwf_user_role_set will need after it writes."""
        user = factories.User()
        program = _program()

        with app.flask_app.test_request_context():
            assert roles.user_role(user[u'name']) is None
            _assign(program[u'id'], user[u'name'], roles.CAPACITY_ADMIN)

            assert roles.user_role(user[u'name']) is None  # still cached
            roles.clear_cache()
            assert roles.user_role(user[u'name']) == roles.PROGRAM_ADMIN

    def test_clear_cache_outside_a_request_is_a_no_op(self):
        roles.clear_cache()
