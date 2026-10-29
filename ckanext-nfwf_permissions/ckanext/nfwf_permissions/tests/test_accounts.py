# encoding: utf-8
"""Tests for account status storage and the chained membership guards.

The contract tests cover the ``nfwf_user_*`` actions from the outside. These
cover the two things item 4 added underneath that the contract does not reach:
the four-statuses-onto-three-states mapping, and the guards that stop the role
model being broken by the stock Members screens or a direct API call.
"""
import threading

import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import authz, model
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import accounts, roles
from ckanext.nfwf_permissions.logic import action


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
    """Only a Platform Administrator can appoint a Platform Administrator.

    A Program Administrator reaches ``nfwf_user_role_set`` but cannot assign
    that role -- ``roles.PROGRAM_ADMIN_ASSIGNABLE_ROLES`` leaves it out -- so
    removing the last one is not a recoverable mistake from inside the product:
    it takes ``ckan sysadmin add`` on the server to undo.
    """

    def test_the_last_one_cannot_be_demoted(self, last_admin):
        """Defense in depth -- reachable through an internal context.

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

        assert u'your own Platform Administrator account' in str(caught.value)

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


@pytest.mark.usefixtures(u'with_plugins')
class TestClosingAnAccountCannotStrandTheSite(object):
    """The status actions reach the same lockout as a demotion.

    Deactivating the last two Platform Administrators locks the site exactly
    as demoting them would, and leaves nothing for the demotion guard's own
    "remaining" count to find, since a deleted account is not an active one.
    """

    def test_the_last_administrator_cannot_be_deactivated(self, last_admin):
        with pytest.raises(toolkit.ValidationError) as caught:
            helpers.call_action(
                u'nfwf_user_deactivate',
                context={u'user': last_admin.ordinary[u'name']},
                id=last_admin.only[u'id'])

        assert u'only Platform Administrator' in str(caught.value)

    def test_an_administrator_cannot_close_their_own_account(self, last_admin):
        with pytest.raises(toolkit.ValidationError) as caught:
            _as(last_admin.only[u'name'], u'nfwf_user_deactivate',
                id=last_admin.only[u'name'])

        assert u'your own Platform Administrator account' in str(caught.value)

    def test_rejecting_is_guarded_too(self, last_admin):
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_reject',
                context={u'user': last_admin.ordinary[u'name']},
                id=last_admin.only[u'id'])

    def test_an_ordinary_account_closes_normally(self, last_admin):
        """The guard must not make the action unusable in the normal case."""
        result = _as(last_admin.only[u'name'], u'nfwf_user_deactivate',
                     id=last_admin.ordinary[u'id'])

        assert result[u'status'] == roles.STATUS_DEACTIVATED

    def test_approving_is_never_blocked(self, last_admin):
        """Approve only ever restores access, so it needs no guard."""
        result = _as(last_admin.only[u'name'], u'nfwf_user_approve',
                     id=last_admin.only[u'name'])

        assert result[u'status'] == roles.STATUS_ACTIVE


@pytest.mark.usefixtures(u'with_plugins')
class TestListFilteringByGroup(object):

    def _list(self, world, **kwargs):
        return _as(world.sysadmin[u'name'], u'nfwf_user_list', **kwargs)

    def test_a_grant_may_be_named_rather_than_given_by_id(self, world):
        """grant_id went into the query raw, so a name matched nothing."""
        _assign(world.grant[u'id'], world.user[u'name'],
                roles.CAPACITY_EDITOR)

        by_id = self._list(world, grant_id=world.grant[u'id'])
        by_name = self._list(world, grant_id=world.grant[u'name'])

        # Counts rather than a fixed number: CKAN's site user is made an admin
        # of every group the factories build, so it matches these filters too.
        assert world.user[u'name'] in [r[u'name'] for r in by_id[u'results']]
        assert by_name[u'count'] == by_id[u'count']
        assert [r[u'name'] for r in by_name[u'results']] == \
            [r[u'name'] for r in by_id[u'results']]

    def test_both_filters_apply_rather_than_one_winning(self, world):
        """Supplying both used to drop the grant and return the program."""
        in_program_only = factories.User()
        _assign(world.program[u'id'], in_program_only[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(world.program[u'id'], world.user[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(world.grant[u'id'], world.user[u'name'],
                roles.CAPACITY_EDITOR)

        both = self._list(world, program_id=world.program[u'id'],
                          grant_id=world.grant[u'id'])
        names = [row[u'name'] for row in both[u'results']]

        # Holds both, so survives both filters.
        assert world.user[u'name'] in names
        # Holds the program only. Under the old behavior the grant filter was
        # dropped entirely and this user came back as well.
        assert in_program_only[u'name'] not in names

    def test_an_unknown_reference_matches_nothing(self, world):
        assert self._list(world, grant_id=u'no-such-grant')[u'count'] == 0
        assert self._list(world, program_id=u'no-such-program')[u'count'] == 0

    def test_a_program_is_not_a_grant(self, world):
        """Each reference has to name the right kind of group."""
        assert self._list(world, grant_id=world.program[u'id'])[u'count'] == 0
        assert self._list(world, program_id=world.grant[u'id'])[u'count'] == 0

    def test_a_limit_of_zero_is_refused(self, world):
        """Otherwise it returns no rows while count says there are some."""
        with pytest.raises(toolkit.ValidationError) as caught:
            self._list(world, limit=0)

        assert u'limit' in str(caught.value)


@pytest.mark.usefixtures(u'with_plugins')
class TestGroupToGroupMembershipIsRefused(object):
    """The role model has no concept of a CKAN group hierarchy.

    A grant points at its program through the ``owner_group`` extra precisely
    *because* it is not a hierarchy -- that is why ``logic/auth.py`` needs its
    Program Administrator overrides at all. A ``Member`` row with
    ``table_name='group'`` reintroduces CKAN's native cascading underneath the
    model, and nothing here audits it: ``migration.py`` filters on
    ``table_name == 'user'`` throughout.

    Demonstrated before the guard existed: a Program Administrator wrote
    ``member_create(id=<a grant in their program>, object=<another grant>,
    object_type='group')`` -- ``member_create``'s auth checks only ``id``,
    never ``object``, so the parent could even be a grant from another
    program -- and a holder of the retired grant ``admin`` capacity on that
    parent, an account ``user_role`` reports as holding *no role*, gained full
    ``update`` authority over the child grant.

    Note ``world.grant`` is deliberately not used here: it has an empty
    ``owner_group``, so auth would refuse a Program Administrator on it before
    this guard was ever reached.
    """

    def _in_program(self, world):
        return factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': world.program[u'id']}])

    def _program_admin(self, world):
        user = factories.User()
        _assign(world.program[u'id'], user[u'name'], roles.CAPACITY_ADMIN)
        return user

    def test_a_program_administrator_may_not_write_one(self, world):
        child, parent = self._in_program(world), self._in_program(world)
        padmin = self._program_admin(world)

        with pytest.raises(toolkit.ValidationError) as caught:
            _as(padmin[u'name'], u'member_create',
                id=child[u'id'], object=parent[u'id'],
                object_type=u'group', capacity=u'parent')

        assert u'group membership' in str(caught.value)

    def test_the_cascade_it_would_have_opened_stays_shut(self, world):
        """The consequence, stated as the thing that must not happen."""
        child, parent = self._in_program(world), self._in_program(world)
        padmin = self._program_admin(world)
        stale = factories.User()
        _assign(parent[u'id'], stale[u'name'], roles.CAPACITY_ADMIN)

        with pytest.raises(toolkit.ValidationError):
            _as(padmin[u'name'], u'member_create',
                id=child[u'id'], object=parent[u'id'],
                object_type=u'group', capacity=u'parent')
        roles.clear_cache()

        assert roles.user_role(stale[u'name']) is None
        assert not authz.has_user_permission_for_group_or_org(
            child[u'id'], stale[u'name'], u'update')

    def test_a_parent_from_another_program_is_refused_too(self, world):
        """auth never inspects ``object``, so the guard has to."""
        child = self._in_program(world)
        foreign = factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA,
             u'value': factories.Group()[u'id']}])
        padmin = self._program_admin(world)

        with pytest.raises(toolkit.ValidationError):
            _as(padmin[u'name'], u'member_create',
                id=child[u'id'], object=foreign[u'id'],
                object_type=u'group', capacity=u'parent')

    def test_user_rows_are_unaffected(self, world):
        """The guard must not catch the membership writes that are the point."""
        child = self._in_program(world)
        padmin = self._program_admin(world)
        editor = factories.User()

        _as(padmin[u'name'], u'member_create',
            id=child[u'id'], object=editor[u'name'],
            object_type=u'user', capacity=roles.CAPACITY_EDITOR)

        assert roles.user_role(editor[u'name']) == roles.GRANT_EDITOR

    def test_a_platform_administrator_is_exempt(self, world):
        """Deliberate: stock CKAN's hierarchy feature stays theirs to use.

        Creating one really does open the cascade -- that is why it is refused
        for everyone else -- so this is a capability reserved to the role that
        already holds every other one.
        """
        child, parent = self._in_program(world), self._in_program(world)

        _as(world.sysadmin[u'name'], u'member_create',
            id=child[u'id'], object=parent[u'id'],
            object_type=u'group', capacity=u'parent')

    def test_internal_callers_are_exempt(self, world):
        """ignore_auth, matching the other chained guards in this file."""
        child, parent = self._in_program(world), self._in_program(world)

        helpers.call_action(
            u'member_create', context={u'user': world.user[u'name']},
            id=child[u'id'], object=parent[u'id'],
            object_type=u'group', capacity=u'parent')


def _auth0_style_user(name=u'someone@example.gov'):
    """An account shaped the way the real ones are, written past the validators.

    Every account on the production site is created by ``ckanext-oauth2`` from
    Auth0 and named after the person's email address. ``factories.User()``
    cannot produce one -- it goes through ``user_create``, whose
    ``name_validator`` rejects ``@`` and ``.`` -- which is exactly why a suite
    of several hundred tests ran for weeks against names that resemble no real
    account, and why the status actions were broken for all but one of them
    without anything failing.
    """
    user = model.User(name=name, email=name)
    user.state = u'active'
    model.Session.add(user)
    model.Session.commit()
    return model.User.get(name)


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestLegacyUsernames(object):
    """CKAN's ``name_validator`` rejects the usernames this site actually has.

    It runs on every update, because ``user_patch`` merges over ``user_show``
    and that always carries ``name`` -- omitting it or passing ``ignore_auth``
    makes no difference, both were probed. So ``accounts.patch`` relaxes the
    format checks for a field it only ever writes back unchanged.
    """

    def test_every_status_is_reachable_on_an_email_named_account(self):
        sysadmin = factories.Sysadmin()
        user = _auth0_style_user()
        ctx = {u'user': sysadmin[u'name']}

        for status in roles.STATUSES:
            accounts.set_status(ctx, model.User.get(user.id), status)

            assert accounts.status_of(model.User.get(user.id)) == status, status

    def test_the_name_itself_is_never_altered(self):
        """The relaxation must not become a way to rewrite names."""
        sysadmin = factories.Sysadmin()
        user = _auth0_style_user()

        accounts.set_status({u'user': sysadmin[u'name']},
                            model.User.get(user.id), roles.STATUS_DEACTIVATED)

        assert model.User.get(user.id).name == u'someone@example.gov'

    def test_the_actions_work_end_to_end(self):
        """Through the API, not just the helper -- this is what Task 117's
        screen calls, and what was failing for every real account."""
        sysadmin = factories.Sysadmin()
        user = _auth0_style_user(u'another.person@example.gov')

        result = helpers.call_action(
            u'nfwf_user_deactivate',
            context={u'user': sysadmin[u'name'], u'ignore_auth': False},
            id=user.name)

        assert result[u'status'] == roles.STATUS_DEACTIVATED
        assert model.User.get(user.id).name == u'another.person@example.gov'

    def test_renaming_still_goes_through_stock_validation(self):
        """Only `accounts.patch` relaxes this. A genuine rename is unaffected,
        so the relaxation cannot be reached as a way past `name_validator`."""
        sysadmin = factories.Sysadmin()
        user = factories.User()

        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'user_update',
                context={u'user': sysadmin[u'name'], u'ignore_auth': False},
                id=user[u'id'], name=u'not a valid name!',
                email=user[u'email'])


@pytest.mark.usefixtures(u'with_plugins')
class TestOneRolePerUserUnderConcurrency(object):
    """One role per user is a conflict-of-interest control, so it has to hold
    when two administrators act at the same moment, not only when they take
    turns.

    It did not. `_assert_membership_is_allowed` reads what the account holds
    and the action then writes, with nothing in between; two requests each read
    "holds nothing" and each proceeded. The modal had the same hole one layer
    up, because it reaches the member actions with `ignore_auth` and so skips
    the guard entirely -- and there it was worse, since every save *replaces*
    the assignments, so interleaving produced a combination neither caller
    asked for.

    The barriers below do not invent a race. They force an interleaving the
    code permits, which is how you show a check-then-act window without
    relying on timing luck. `_lock_account` is what closes it.

    **What the barrier does once the lock is in place, which is not what it
    looks like.** Against the fixed code these barriers never trip. The first
    thread takes the row lock inside `_assert_membership_is_allowed` and then
    waits; the second blocks on that lock *before* reaching the barrier, so it
    can never reach two participants. The wait ends in `BrokenBarrierError`,
    which is caught and ignored, the first thread commits, and the second then
    reads the committed row and refuses. So these tests pass because the
    barrier *fails* -- the interleaving is forced only against the unfixed
    code, which is how the defect was demonstrated in the first place.

    That makes the timeout pure dead time on every run, which is why it is
    short. Both threads reach the barrier in well under a second when the lock
    is removed -- the whole suite fails in about four seconds in that state --
    so five is already generous for the only case where the barrier does any
    work. Raise it if these ever go flaky on a loaded machine; the cost is
    that much idle time twice per run.

    Both tests were confirmed discriminating on 2026-09-25 by disabling
    `_lock_account`: both fail, on the assertion that the account ends up
    holding both scopes.
    """

    @staticmethod
    def _run_together(first, second):
        threads = [threading.Thread(target=first),
                   threading.Thread(target=second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        model.Session.remove()
        roles.clear_cache()

    def test_two_membership_writes_cannot_both_land(self, world,
                                                    monkeypatch):
        barrier = threading.Barrier(2, timeout=5)
        original = action._assert_membership_is_allowed

        def checked_then_paused(context, group_ref, user_ref, capacity):
            original(context, group_ref, user_ref, capacity)
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass

        monkeypatch.setattr(
            action, u'_assert_membership_is_allowed', checked_then_paused)
        outcomes = {}

        def add(key, action_name, **kwargs):
            def go():
                try:
                    _as(world.sysadmin[u'name'], action_name,
                        username=world.user[u'name'], **kwargs)
                    outcomes[key] = None
                except Exception as exc:
                    outcomes[key] = type(exc).__name__
                finally:
                    model.Session.remove()
            return go

        self._run_together(
            add(u'grant', u'organization_member_create',
                id=world.grant[u'id'], role=roles.CAPACITY_EDITOR),
            add(u'program', u'group_member_create',
                id=world.program[u'id'], role=roles.CAPACITY_MEMBER))

        assert not roles.holds_both_scopes(world.user[u'name']), (
            u'both writes landed and the account now holds both scopes')
        assert u'ValidationError' in set(
            v for v in outcomes.values() if v), outcomes

    def test_two_role_changes_leave_one_coherent_role(self, world,
                                                      monkeypatch):
        """The modal path. Both callers may succeed -- each replaces the lot,
        so last-writer-wins is the right answer -- but the account must end up
        in one of the two states they asked for, not a mixture of both."""
        barrier = threading.Barrier(2, timeout=5)
        original = action._apply_role

        def paused_then_applied(context, user, role, programs, grants):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return original(context, user, role, programs, grants)

        monkeypatch.setattr(action, u'_apply_role', paused_then_applied)

        # CKAN builds its auth registry lazily and not thread-safely; in a
        # running site the first request has already done it.
        try:
            toolkit.check_access(u'nfwf_user_role_set',
                                 {u'user': world.sysadmin[u'name']}, {})
        except Exception:
            pass

        def set_role(**kwargs):
            def go():
                try:
                    _as(world.sysadmin[u'name'], u'nfwf_user_role_set',
                        id=world.user[u'name'], **kwargs)
                except Exception:
                    pass
                finally:
                    model.Session.remove()
            return go

        self._run_together(
            set_role(role=roles.GRANT_EDITOR, grant_ids=[world.grant[u'id']]),
            set_role(role=roles.PROGRAM_READER,
                     program_ids=[world.program[u'id']]))

        assert not roles.holds_both_scopes(world.user[u'name'])
        assert roles.user_role(world.user[u'name']) in (
            roles.GRANT_EDITOR, roles.PROGRAM_READER)


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestTheStatusStateMachine(object):
    """Which status each lifecycle action may act on.

    Confirmed with the product owner 2026-09-28, after measuring that
    `nfwf_user_reject` accepted *any* account: an account active for a year
    could be rejected, which set CKAN's state to `deleted`, and nothing in
    this API could undo it. Two changes came out of that -- reject is now
    restricted to accounts awaiting review, and `nfwf_user_reactivate` exists.

    ==================  =====================  ========================
    Action              From                   To
    ==================  =====================  ========================
    ``approve``         anything               Active
    ``reject``          Needs Review only      Account request rejected
    ``deactivate``      anything               Deactivated
    ``reactivate``      Deactivated only       Active
    ==================  =====================  ========================

    `approve` and `deactivate` stay unrestricted deliberately: approve is how
    a rejected *request* is let in after a second look, and deactivate has to
    work on anything that can currently be used.
    """

    def _sysadmins(self):
        first = factories.Sysadmin()
        factories.Sysadmin()  # so closing an account never strands the site
        return {u'user': first[u'name'], u'ignore_auth': False}

    def _status(self, user_id):
        roles.clear_cache()
        return accounts.status_of(model.User.get(user_id))

    def test_reject_refuses_an_active_account(self):
        """The defect this class exists for."""
        ctx = self._sysadmins()
        user = factories.User()

        with pytest.raises(toolkit.ValidationError) as caught:
            helpers.call_action(u'nfwf_user_reject', context=ctx,
                                id=user[u'name'])

        assert u'id' in caught.value.error_dict
        assert self._status(user[u'id']) == roles.STATUS_ACTIVE, (
            u'the refused reject must not have changed anything')

    def test_reject_still_works_on_a_pending_account(self):
        ctx = self._sysadmins()
        user = factories.User()
        helpers.call_action(u'nfwf_user_deactivate', context=ctx,
                            id=user[u'name'])
        accounts.set_status(dict(ctx), model.User.get(user[u'id']),
                            roles.STATUS_NEEDS_REVIEW)
        roles.clear_cache()

        helpers.call_action(u'nfwf_user_reject', context=ctx,
                            id=user[u'name'])

        assert self._status(user[u'id']) == roles.STATUS_REJECTED

    def test_reactivate_restores_a_deactivated_account(self):
        ctx = self._sysadmins()
        user = factories.User()
        helpers.call_action(u'nfwf_user_deactivate', context=ctx,
                            id=user[u'name'])
        assert self._status(user[u'id']) == roles.STATUS_DEACTIVATED

        helpers.call_action(u'nfwf_user_reactivate', context=ctx,
                            id=user[u'name'])

        assert self._status(user[u'id']) == roles.STATUS_ACTIVE
        assert model.User.get(user[u'id']).state == u'active', (
            u'CKAN state has to come back too, or the account still cannot '
            u'log in')

    def test_deactivate_removes_every_assignment(self):
        """Task 117 testing, 2026-10-28: a deactivated account keeps no role.
        Both scopes, including a retired grant capacity, which confers no
        role but still grants CKAN access."""
        ctx = self._sysadmins()
        program = factories.Group()
        grant = factories.Organization()
        retired = factories.Organization()
        user = factories.User()
        _assign(program[u'id'], user[u'name'], roles.CAPACITY_MEMBER)
        _assign(grant[u'id'], user[u'name'], roles.CAPACITY_EDITOR)
        _assign(retired[u'id'], user[u'name'], roles.CAPACITY_ADMIN)
        roles.clear_cache()

        result = helpers.call_action(u'nfwf_user_deactivate', context=ctx,
                                     id=user[u'name'])

        assert result[u'role'] is None
        assert result[u'programs'] == [] and result[u'grants'] == []
        roles.clear_cache()
        assert not roles.programs_for_user(user[u'id'])
        assert not roles.grants_for_user(user[u'id'])

    def test_deactivate_removes_platform_administrator(self):
        """Including any assignments a promotion had retained, so that
        reactivating cannot hand them back."""
        ctx = self._sysadmins()
        grant = factories.Organization()
        user = factories.Sysadmin()
        _assign(grant[u'id'], user[u'name'], roles.CAPACITY_EDITOR)
        roles.clear_cache()

        helpers.call_action(u'nfwf_user_deactivate', context=ctx,
                            id=user[u'name'])
        helpers.call_action(u'nfwf_user_reactivate', context=ctx,
                            id=user[u'name'])

        roles.clear_cache()
        assert not model.User.get(user[u'id']).sysadmin
        assert roles.user_role(user[u'id']) is None
        assert not roles.grants_for_user(user[u'id'])

    def test_a_refused_deactivation_removes_nothing(self, last_admin):
        """The administrator guard runs first, so the last Platform
        Administrator keeps the role as well as the account."""
        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(
                u'nfwf_user_deactivate',
                context={u'user': last_admin.ordinary[u'name']},
                id=last_admin.only[u'id'])

        assert model.User.get(last_admin.only[u'id']).sysadmin

    def test_reactivate_refuses_a_rejected_account(self):
        """Letting a rejected request in is approving it, and `approve` is
        the action that leaves the right word in the audit trail."""
        ctx = self._sysadmins()
        user = factories.User()
        accounts.set_status(dict(ctx), model.User.get(user[u'id']),
                            roles.STATUS_REJECTED)
        roles.clear_cache()

        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_reactivate', context=ctx,
                                id=user[u'name'])

        assert self._status(user[u'id']) == roles.STATUS_REJECTED

    def test_reactivate_refuses_an_already_active_account(self):
        ctx = self._sysadmins()
        user = factories.User()

        with pytest.raises(toolkit.ValidationError):
            helpers.call_action(u'nfwf_user_reactivate', context=ctx,
                                id=user[u'name'])

    def test_approve_still_lets_a_rejected_request_in(self):
        """The intended route back from a rejection."""
        ctx = self._sysadmins()
        user = factories.User()
        accounts.set_status(dict(ctx), model.User.get(user[u'id']),
                            roles.STATUS_REJECTED)
        roles.clear_cache()

        helpers.call_action(u'nfwf_user_approve', context=ctx,
                            id=user[u'name'])

        assert self._status(user[u'id']) == roles.STATUS_ACTIVE

    def test_reactivate_is_platform_administrator_only(self):
        """Account lifecycle stays closed to Program Administrators -- the
        document lists "Approve new/remove user accounts" under Platform
        Administrator alone."""
        program = factories.Group()
        padmin = factories.User()
        helpers.call_action(u'group_member_create', id=program[u'id'],
                            username=padmin[u'name'], role=u'admin')
        target = factories.User()
        roles.clear_cache()

        with pytest.raises(toolkit.NotAuthorized):
            helpers.call_action(
                u'nfwf_user_reactivate',
                context={u'user': padmin[u'name'], u'ignore_auth': False},
                id=target[u'name'])
