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
