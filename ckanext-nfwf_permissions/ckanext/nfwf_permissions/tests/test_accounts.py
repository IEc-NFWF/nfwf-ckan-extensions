# encoding: utf-8
"""Tests for account status storage and the chained membership guards.

The contract tests cover the ``nfwf_user_*`` actions from the outside. These
cover the two things item 4 added underneath that the contract does not reach:
the four-statuses-onto-three-states mapping, and the guards that stop the role
model being broken by the stock Members screens or a direct API call.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import accounts, roles


def _assign(group_id, user_name, capacity):
    """Add a membership the internal way, bypassing the guards."""
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


def _as(user_name, action, **data_dict):
    """Call an action with the guards actually enforced."""
    return helpers.call_action(
        action, context={u'user': user_name, u'ignore_auth': False},
        **data_dict)


class World(object):
    def __init__(self):
        self.program = factories.Group()
        self.grant = factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': u''}])
        self.sysadmin = factories.Sysadmin()
        self.user = factories.User()


@pytest.fixture
def world(clean_db):
    return World()


@pytest.mark.usefixtures(u'with_plugins')
class TestStatusStorage(object):
    """Four mockup statuses over three CKAN states."""

    def test_every_status_round_trips(self, world):
        """status_of must invert STATUS_STORAGE for all four."""
        for status in roles.STATUSES:
            user = model.User.get(world.user[u'id'])
            accounts.set_status(
                {u'user': world.sysadmin[u'name']}, user, status)

            assert accounts.status_of(
                model.User.get(world.user[u'id'])) == status, status

    def test_the_two_gone_statuses_share_deleted(self, world):
        user = model.User.get(world.user[u'id'])
        accounts.set_status({u'user': world.sysadmin[u'name']}, user,
                            roles.STATUS_REJECTED)
        rejected_state = model.User.get(world.user[u'id']).state

        accounts.set_status({u'user': world.sysadmin[u'name']},
                            model.User.get(world.user[u'id']),
                            roles.STATUS_DEACTIVATED)
        deactivated_state = model.User.get(world.user[u'id']).state

        assert rejected_state == deactivated_state == u'deleted'

    def test_reactivating_clears_the_marker(self, world):
        """Otherwise a reactivated account would still read as rejected."""
        context = {u'user': world.sysadmin[u'name']}
        accounts.set_status(context, model.User.get(world.user[u'id']),
                            roles.STATUS_REJECTED)
        accounts.set_status(context, model.User.get(world.user[u'id']),
                            roles.STATUS_ACTIVE)

        user = model.User.get(world.user[u'id'])
        assert accounts.status_of(user) == roles.STATUS_ACTIVE
        assert not (user.plugin_extras or {}).get(
            roles.PLUGIN_EXTRAS_KEY, {}).get(accounts.ACCOUNT_STATUS)

    def test_a_deleted_account_with_no_marker_reads_as_deactivated(self, world):
        """Accounts closed before this feature existed."""
        user = model.User.get(world.user[u'id'])
        user.delete()
        model.Session.commit()

        assert accounts.status_of(
            model.User.get(world.user[u'id'])) == roles.STATUS_DEACTIVATED


@pytest.mark.usefixtures(u'with_plugins')
class TestRetiredGrantCapacities(object):
    """Grant `member` and grant `admin` are gone; only Grant Editor remains."""

    @pytest.mark.parametrize(u'capacity', [u'member', u'admin'])
    def test_member_create_refuses_them_on_a_grant(self, capacity, world):
        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'], u'member_create',
                id=world.grant[u'id'], object=world.user[u'name'],
                object_type=u'user', capacity=capacity)

    @pytest.mark.parametrize(u'role', [u'member', u'admin'])
    def test_organization_member_create_refuses_them(self, role, world):
        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'], u'organization_member_create',
                id=world.grant[u'id'], username=world.user[u'name'],
                role=role)

    def test_editor_is_still_allowed_on_a_grant(self, world):
        _as(world.sysadmin[u'name'], u'organization_member_create',
            id=world.grant[u'id'], username=world.user[u'name'],
            role=roles.CAPACITY_EDITOR)

        assert world.grant[u'id'] in roles.grants_for_user(
            world.user[u'name'])

    def test_admin_is_still_allowed_on_a_program(self, world):
        """The capacities are retired on grants only -- a program has admins."""
        _as(world.sysadmin[u'name'], u'group_member_create',
            id=world.program[u'id'], username=world.user[u'name'],
            role=roles.CAPACITY_ADMIN)

        assert world.program[u'id'] in roles.programs_for_user(
            world.user[u'name'])

    def test_creating_a_grant_still_works(self, world):
        """CKAN makes the creator a grant `admin`, via member_create.

        It passes ignore_auth, which is the exemption that keeps this possible
        -- without honouring it, refusing retired capacities would make grants
        impossible to create at all.
        """
        result = _as(world.sysadmin[u'name'], u'organization_create',
                     name=u'a-brand-new-grant')

        assert result[u'name'] == u'a-brand-new-grant'


@pytest.mark.usefixtures(u'with_plugins')
class TestOneRolePerUser(object):
    """Settled 2026-08-19, and a conflict-of-interest control, not a nicety."""

    def test_a_program_member_cannot_also_be_a_grant_editor(self, world):
        _assign(world.program[u'id'], world.user[u'name'],
                roles.CAPACITY_MEMBER)

        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'], u'organization_member_create',
                id=world.grant[u'id'], username=world.user[u'name'],
                role=roles.CAPACITY_EDITOR)

    def test_a_grant_editor_cannot_also_join_a_program(self, world):
        _assign(world.grant[u'id'], world.user[u'name'],
                roles.CAPACITY_EDITOR)

        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'], u'group_member_create',
                id=world.program[u'id'], username=world.user[u'name'],
                role=roles.CAPACITY_MEMBER)

    def test_a_second_grant_is_fine(self, world):
        """One role, but a Grant Editor may hold several grants."""
        other = factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': u''}])
        _assign(world.grant[u'id'], world.user[u'name'],
                roles.CAPACITY_EDITOR)

        _as(world.sysadmin[u'name'], u'organization_member_create',
            id=other[u'id'], username=world.user[u'name'],
            role=roles.CAPACITY_EDITOR)

        assert len(roles.grants_for_user(world.user[u'name'])) == 2

    def test_a_second_program_is_fine(self, world):
        other = factories.Group()
        _assign(world.program[u'id'], world.user[u'name'],
                roles.CAPACITY_MEMBER)

        _as(world.sysadmin[u'name'], u'group_member_create',
            id=other[u'id'], username=world.user[u'name'],
            role=roles.CAPACITY_MEMBER)

        assert len(roles.programs_for_user(world.user[u'name'])) == 2

    def test_role_set_can_still_switch_scope(self, world):
        """The sanctioned path must not be blocked by the guard.

        nfwf_user_role_set clears the other scope before writing the new one,
        and uses an internal context for its member writes, so moving a Grant
        Editor to a program role has to work even though the intermediate state
        would otherwise look like a conflict.
        """
        _assign(world.grant[u'id'], world.user[u'name'],
                roles.CAPACITY_EDITOR)

        result = _as(world.sysadmin[u'name'], u'nfwf_user_role_set',
                     id=world.user[u'name'], role=roles.PROGRAM_READER,
                     program_ids=[world.program[u'id']])

        assert result[u'role'] == roles.PROGRAM_READER
        assert result[u'grants'] == []
        assert roles.grants_for_user(world.user[u'name']) == frozenset()

    def test_the_guard_is_bypassed_for_internal_callers(self, world):
        """The migration, the factories and CKAN itself rely on this."""
        _assign(world.program[u'id'], world.user[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(world.grant[u'id'], world.user[u'name'],
                roles.CAPACITY_EDITOR)

        assert roles.programs_for_user(world.user[u'name'])
        assert roles.grants_for_user(world.user[u'name'])


class LastAdmin(object):
    """Exactly one active Platform Administrator, whatever else exists."""

    def __init__(self):
        self.only = factories.Sysadmin()
        self.ordinary = factories.User()
        self.program = factories.Group()
        # CKAN's own site user carries the flag, so make "the last one" true
        # rather than assume the factory produced the only one.
        others = model.Session.query(model.User).filter(
            model.User.sysadmin.is_(True),
            model.User.state == u'active',
            model.User.id != self.only[u'id']).all()
        for user in others:
            user.sysadmin = False
        model.repo.commit()


@pytest.fixture
def last_admin(clean_db):
    return LastAdmin()


@pytest.mark.usefixtures(u'with_plugins')
class TestPlatformAdministratorsCannotAllBeRemoved(object):
    """Every action in logic/action.py is Platform-Administrator-only.

    So removing the last one is not a recoverable mistake from inside the
    product: it takes ``ckan sysadmin add`` on the server to undo.
    """

    def test_the_last_one_cannot_be_demoted(self, last_admin):
        """Defence in depth -- reachable through an internal context.

        A caller who is not themselves a Platform Administrator cannot get
        here through the auth function; this guards the case where something
        bypasses it, which the chained membership guards also have to allow.
        """
        with pytest.raises(toolkit.ValidationError) as caught:
            helpers.call_action(
                u'nfwf_user_role_set',
                context={u'user': last_admin.ordinary[u'name']},
                id=last_admin.only[u'id'], role=roles.PROGRAM_ADMIN,
                program_ids=[last_admin.program[u'id']])

        assert u'only Platform Administrator' in str(caught.value)

    def test_a_platform_admin_cannot_demote_themselves(self, last_admin):
        """The likelier accident: their own row looks like everyone else's."""
        with pytest.raises(toolkit.ValidationError) as caught:
            _as(last_admin.only[u'name'], u'nfwf_user_role_set',
                id=last_admin.only[u'name'], role=roles.PROGRAM_ADMIN,
                program_ids=[last_admin.program[u'id']])

        assert u'your own Platform Administrator role' in str(caught.value)

    def test_another_one_may_be_demoted_while_someone_remains(self, world):
        """The guard must not make the role unusable in the normal case."""
        spare = factories.Sysadmin()

        result = _as(world.sysadmin[u'name'], u'nfwf_user_role_set',
                     id=spare[u'id'], role=roles.PROGRAM_ADMIN,
                     program_ids=[world.program[u'id']])

        assert result[u'role'] == roles.PROGRAM_ADMIN

    def test_promotion_is_never_blocked(self, last_admin):
        result = helpers.call_action(
            u'nfwf_user_role_set',
            context={u'user': last_admin.only[u'name']},
            id=last_admin.ordinary[u'id'], role=roles.PLATFORM_ADMIN)

        assert result[u'role'] == roles.PLATFORM_ADMIN


@pytest.mark.usefixtures(u'with_plugins')
class TestSearchEscapesLikeWildcards(object):
    """An underscore in a search term is a literal, not "any character"."""

    def test_underscore_does_not_match_any_character(self, world):
        factories.User(name=u'a_b', fullname=u'Literal Underscore')
        factories.User(name=u'axb', fullname=u'Wildcard Match')

        found = {user.name for user in accounts.search_users(q=u'a_b')}

        assert u'a_b' in found
        assert u'axb' not in found

    def test_percent_does_not_match_everything(self, world):
        factories.User(name=u'plain-name')

        assert accounts.search_users(q=u'%') == []
