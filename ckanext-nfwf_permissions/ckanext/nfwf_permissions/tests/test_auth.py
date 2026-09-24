# encoding: utf-8
"""Tests for the permission matrix.

Every check goes through ``authz.is_authorized`` rather than calling an auth
function directly, so the sysadmin short-circuit, the anonymous-access gate and
the plugin registration are all part of what is under test -- calling the
functions directly would test the bodies while skipping the machinery that
decides whether they run at all.

Two kinds of test live here and both matter:

* what the overrides **grant** -- a Program Administrator reaching the grants
  in their program;
* what stock CKAN already gets right, which ``logic/auth.py`` deliberately
  leaves alone. Those are regression guards on the *absence* of an override.
  If a future change makes one of them fail, the file's "deliberately not
  overridden" list has gone stale and needs revisiting.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import authz, model

from ckanext.nfwf_permissions import roles
from ckanext.nfwf_permissions.logic import auth


def _can(user, action, **data_dict):
    """Would ``user`` (a name, or ``None`` for anonymous) be allowed?"""
    user_obj = model.User.get(user) if user else None
    context = {
        u'model': model,
        u'session': model.Session,
        u'user': user_obj.name if user_obj else u'',
        u'auth_user_obj': user_obj,
    }
    return authz.is_authorized_boolean(action, context, dict(data_dict))


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


class World(object):
    """Two programs, three grants, an orphan grant, and one user per role."""

    def __init__(self):
        self.program_a = factories.Group()
        self.program_b = factories.Group()

        self.grant_a1 = self._grant(self.program_a[u'id'])
        self.grant_a2 = self._grant(self.program_a[u'id'])
        self.grant_b1 = self._grant(self.program_b[u'id'])
        # The 30-grant production case: owner_group present but empty.
        self.grant_orphan = self._grant(u'')

        self.platform_admin = factories.Sysadmin()
        self.program_admin = factories.User()
        self.program_reader = factories.User()
        self.grant_editor = factories.User()
        self.nobody = factories.User()

        _assign(self.program_a[u'id'], self.program_admin[u'name'],
                roles.CAPACITY_ADMIN)
        _assign(self.program_a[u'id'], self.program_reader[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(self.grant_a1[u'id'], self.grant_editor[u'name'],
                roles.CAPACITY_EDITOR)

        self.dataset_a1 = factories.Dataset(owner_org=self.grant_a1[u'id'])
        self.dataset_b1 = factories.Dataset(owner_org=self.grant_b1[u'id'])

    @staticmethod
    def _grant(program_id):
        return factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': program_id}])


@pytest.fixture
def world():
    return World()


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestDatasets(object):

    def test_program_admin_edits_datasets_across_their_program(self, world):
        assert _can(world.program_admin[u'name'], u'package_update',
                    id=world.dataset_a1[u'id'])

    def test_program_admin_cannot_edit_another_programs_datasets(self, world):
        assert not _can(world.program_admin[u'name'], u'package_update',
                        id=world.dataset_b1[u'id'])

    def test_program_reader_edits_nothing(self, world):
        """Read-only is the whole point of the role."""
        assert not _can(world.program_reader[u'name'], u'package_update',
                        id=world.dataset_a1[u'id'])

    def test_grant_editor_still_edits_their_own_grant(self, world):
        """Stock CKAN's path, which the override must not have disturbed."""
        assert _can(world.grant_editor[u'name'], u'package_update',
                    id=world.dataset_a1[u'id'])

    def test_grant_editor_cannot_edit_other_grants(self, world):
        assert not _can(world.grant_editor[u'name'], u'package_update',
                        id=world.dataset_b1[u'id'])

    def test_anonymous_edits_nothing(self, world):
        assert not _can(None, u'package_update', id=world.dataset_a1[u'id'])

    def test_program_admin_creates_datasets_in_their_program(self, world):
        assert _can(world.program_admin[u'name'], u'package_create',
                    owner_org=world.grant_a1[u'id'])
        assert _can(world.program_admin[u'name'], u'package_create',
                    owner_org=world.grant_a2[u'id'])

    def test_program_admin_cannot_create_outside_their_program(self, world):
        assert not _can(world.program_admin[u'name'], u'package_create',
                        owner_org=world.grant_b1[u'id'])
        assert not _can(world.program_admin[u'name'], u'package_create',
                        owner_org=world.grant_orphan[u'id'])

    def test_grant_editor_still_creates_in_their_own_grant(self, world):
        assert _can(world.grant_editor[u'name'], u'package_create',
                    owner_org=world.grant_a1[u'id'])

    def test_nobody_creates_nothing(self, world):
        assert not _can(world.nobody[u'name'], u'package_create',
                        owner_org=world.grant_a1[u'id'])


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestDelegatedActions(object):
    """``package_delete`` and the resource actions have no override of their own.

    They reach ``package_update`` through ``authz.is_authorized``, so these
    tests prove the delegation actually happens rather than assuming it.
    """

    def test_package_delete_follows_package_update(self, world):
        assert _can(world.program_admin[u'name'], u'package_delete',
                    id=world.dataset_a1[u'id'])
        assert not _can(world.program_admin[u'name'], u'package_delete',
                        id=world.dataset_b1[u'id'])

    def test_resource_create_follows_package_update(self, world):
        assert _can(world.program_admin[u'name'], u'resource_create',
                    package_id=world.dataset_a1[u'id'])
        assert not _can(world.program_admin[u'name'], u'resource_create',
                        package_id=world.dataset_b1[u'id'])

    def test_resource_update_and_delete_follow_package_update(self, world):
        resource = factories.Resource(package_id=world.dataset_a1[u'id'])

        for action in (u'resource_update', u'resource_delete'):
            assert _can(world.program_admin[u'name'], action,
                        id=resource[u'id']), action
            assert not _can(world.program_reader[u'name'], action,
                            id=resource[u'id']), action


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestPurge(object):

    def test_program_admin_purges_within_their_program(self, world):
        assert _can(world.program_admin[u'name'], u'dataset_purge',
                    id=world.dataset_a1[u'id'])

    def test_program_admin_cannot_purge_elsewhere(self, world):
        assert not _can(world.program_admin[u'name'], u'dataset_purge',
                        id=world.dataset_b1[u'id'])

    def test_grant_editor_cannot_purge_even_their_own(self, world):
        """Stock CKAN is sysadmin-only here and the override must not relax it."""
        assert not _can(world.grant_editor[u'name'], u'dataset_purge',
                        id=world.dataset_a1[u'id'])


@pytest.mark.ckan_config(u'ckan.auth.user_create_organizations', u'false')
@pytest.mark.ckan_config(u'ckan.auth.user_delete_organizations', u'false')
@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestGrants(object):
    """Creating and deleting grants depends on site config, so pin it.

    ``test-core.ini`` leaves CKAN's defaults, where ``user_create_organizations``
    and ``user_delete_organizations`` are *true* and stock lets any logged-in
    user create an organization. Production sets both false (``.env:109,111``),
    which is the posture these overrides were written against and the only one
    in which they are the thing granting access. Without these markers the
    tests pass for the wrong reason.
    """

    def test_program_admin_edits_grants_in_their_program(self, world):
        assert _can(world.program_admin[u'name'], u'organization_update',
                    id=world.grant_a1[u'id'])
        assert _can(world.program_admin[u'name'], u'organization_update',
                    id=world.grant_a2[u'id'])

    def test_program_admin_cannot_edit_other_grants(self, world):
        assert not _can(world.program_admin[u'name'], u'organization_update',
                        id=world.grant_b1[u'id'])
        assert not _can(world.program_admin[u'name'], u'organization_update',
                        id=world.grant_orphan[u'id'])

    def test_grant_editor_cannot_edit_the_grant_itself(self, world):
        """Editor carries update_dataset, not update -- datasets, not the grant."""
        assert not _can(world.grant_editor[u'name'], u'organization_update',
                        id=world.grant_a1[u'id'])

    def test_program_admin_deletes_grants_in_their_program(self, world):
        assert _can(world.program_admin[u'name'], u'organization_delete',
                    id=world.grant_a1[u'id'])
        assert not _can(world.program_admin[u'name'], u'organization_delete',
                        id=world.grant_b1[u'id'])

    def test_program_admin_may_create_a_grant(self, world):
        """Which program it lands in is the chained action's job, not auth's."""
        assert _can(world.program_admin[u'name'], u'organization_create')

    def test_others_may_not_create_a_grant(self, world):
        assert not _can(world.grant_editor[u'name'], u'organization_create')
        assert not _can(world.program_reader[u'name'], u'organization_create')
        assert not _can(world.nobody[u'name'], u'organization_create')


@pytest.mark.ckan_config(u'ckan.auth.user_create_groups', u'false')
@pytest.mark.ckan_config(u'ckan.auth.user_delete_groups', u'false')
@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestProgramsUseStockCkan(object):
    """Regression guards on the *absence* of an override.

    If one of these fails, stock CKAN's behaviour has shifted and the
    "deliberately not overridden" list in ``logic/auth.py`` is out of date.
    """

    def test_program_admin_edits_their_own_program(self, world):
        """Capacity 'admin' satisfies every permission check, so stock allows it."""
        assert _can(world.program_admin[u'name'], u'group_update',
                    id=world.program_a[u'id'])

    def test_program_admin_cannot_edit_another_program(self, world):
        assert not _can(world.program_admin[u'name'], u'group_update',
                        id=world.program_b[u'id'])

    def test_program_reader_cannot_edit_their_program(self, world):
        """'member' carries read and manage_group, but not update."""
        assert not _can(world.program_reader[u'name'], u'group_update',
                        id=world.program_a[u'id'])

    def test_creating_and_deleting_programs_stays_sysadmin_only(self, world):
        assert not _can(world.program_admin[u'name'], u'group_create')
        assert not _can(world.program_admin[u'name'], u'group_delete',
                        id=world.program_a[u'id'])

    def test_program_admin_may_add_readers_to_their_own_program(self, world):
        """Stock: 'admin' has 'membership', 'member' does not."""
        assert _can(world.program_admin[u'name'], u'group_member_create',
                    id=world.program_a[u'id'])
        assert not _can(world.program_reader[u'name'], u'group_member_create',
                        id=world.program_a[u'id'])

    def test_deleting_a_user_stays_sysadmin_only(self, world):
        assert not _can(world.program_admin[u'name'], u'user_delete',
                        id=world.nobody[u'id'])


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestMembership(object):

    def test_program_admin_assigns_editors_on_grants_in_their_program(
            self, world):
        assert _can(world.program_admin[u'name'], u'organization_member_create',
                    id=world.grant_a1[u'id'])
        assert _can(world.program_admin[u'name'], u'member_create',
                    id=world.grant_a1[u'id'], object_type=u'user')

    def test_program_admin_cannot_assign_on_other_grants(self, world):
        assert not _can(
            world.program_admin[u'name'], u'organization_member_create',
            id=world.grant_b1[u'id'])
        assert not _can(world.program_admin[u'name'], u'member_create',
                        id=world.grant_b1[u'id'], object_type=u'user')

    def test_grant_editor_cannot_assign_anyone(self, world):
        assert not _can(
            world.grant_editor[u'name'], u'organization_member_create',
            id=world.grant_a1[u'id'])

    def test_program_admin_manages_their_own_programs_membership(self, world):
        assert _can(world.program_admin[u'name'], u'member_create',
                    id=world.program_a[u'id'], object_type=u'user')
        assert not _can(world.program_admin[u'name'], u'member_create',
                        id=world.program_b[u'id'], object_type=u'user')

    def test_program_reader_cannot_add_datasets_to_their_program(self, world):
        """The hole this override exists to close.

        Stock CKAN asks for 'manage_group' when the member object is a dataset,
        and capacity 'member' carries it -- so stock would let a read-only
        outside contractor rearrange the program's datasets.
        """
        assert not _can(
            world.program_reader[u'name'], u'member_create',
            id=world.program_a[u'id'], object=world.dataset_a1[u'id'],
            object_type=u'package')

    def test_program_reader_cannot_remove_datasets_either(self, world):
        """member_delete defers to member_create, so it inherits the fix."""
        assert not _can(
            world.program_reader[u'name'], u'member_delete',
            id=world.program_a[u'id'], object=world.dataset_a1[u'id'],
            object_type=u'package')

    def test_program_admin_may_still_add_datasets_to_their_program(self, world):
        assert _can(
            world.program_admin[u'name'], u'member_create',
            id=world.program_a[u'id'], object=world.dataset_a1[u'id'],
            object_type=u'package')


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestUserRecords(object):

    def test_only_platform_admins_list_users(self, world):
        assert _can(world.platform_admin[u'name'], u'user_list')
        for user in (world.program_admin, world.program_reader,
                     world.grant_editor, world.nobody):
            assert not _can(user[u'name'], u'user_list'), user[u'name']

    def test_program_admins_may_look_a_user_up(self, world):
        """Otherwise they hold a membership permission they cannot exercise.

        Stock defers user_autocomplete to user_list, and denying both left a
        Program Administrator authorized to add members with no way to find
        anyone -- the member screens have no user picker but this one.
        """
        assert _can(world.program_admin[u'name'], u'user_autocomplete', q=u'a')
        assert _can(world.platform_admin[u'name'], u'user_autocomplete', q=u'a')

    def test_lookup_is_open_but_the_list_is_not(self, world):
        """The split is the whole point: find a named person, not browse all.

        user_list returns whole user records; user_autocomplete returns id,
        name and fullname, and never a deleted account.
        """
        assert not _can(world.program_admin[u'name'], u'user_list')
        assert _can(world.program_admin[u'name'], u'user_autocomplete', q=u'a')

    def test_roles_that_cannot_add_anyone_cannot_look_anyone_up(self, world):
        """Neither may assign membership, so neither needs the lookup."""
        for user in (world.program_reader, world.grant_editor, world.nobody):
            assert not _can(user[u'name'], u'user_autocomplete',
                            q=u'a'), user[u'name']
        assert not _can(None, u'user_autocomplete', q=u'a')

    def test_a_user_may_view_their_own_account(self, world):
        assert _can(world.program_reader[u'name'], u'user_show',
                    id=world.program_reader[u'name'])
        assert _can(world.program_reader[u'name'], u'user_show',
                    id=world.program_reader[u'id'])

    def test_a_missing_id_means_yourself(self, world):
        assert _can(world.program_reader[u'name'], u'user_show')

    def test_a_user_may_not_view_someone_elses_account(self, world):
        assert not _can(world.program_reader[u'name'], u'user_show',
                        id=world.grant_editor[u'name'])

    def test_platform_admins_view_any_account(self, world):
        assert _can(world.platform_admin[u'name'], u'user_show',
                    id=world.program_reader[u'name'])


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestPlatformAdministrator(object):
    """Nothing in logic/auth.py mentions sysadmins, so prove the bypass holds."""

    def test_platform_admin_may_do_everything_overridden(self, world):
        checks = [
            (u'package_update', {u'id': world.dataset_b1[u'id']}),
            (u'package_create', {u'owner_org': world.grant_orphan[u'id']}),
            (u'dataset_purge', {u'id': world.dataset_b1[u'id']}),
            (u'organization_create', {}),
            (u'organization_update', {u'id': world.grant_orphan[u'id']}),
            (u'organization_delete', {u'id': world.grant_orphan[u'id']}),
            (u'member_create', {u'id': world.program_b[u'id'],
                                u'object_type': u'user'}),
            (u'organization_member_create', {u'id': world.grant_b1[u'id']}),
            (u'user_list', {}),
            (u'user_autocomplete', {u'q': u'a'}),
            (u'user_show', {u'id': world.nobody[u'name']}),
        ]
        for action, data_dict in checks:
            assert _can(world.platform_admin[u'name'], action,
                        **data_dict), action


class TestRegistrationIsSafe(object):
    """Structural guards. No database, no plugin loading -- just the module."""

    def test_no_function_suppresses_the_sysadmin_bypass(self):
        """@auth_sysadmins_check would lock Platform Administrators out."""
        suppressing = [
            name for name in auth.__all__
            if getattr(getattr(auth, name), u'auth_sysadmins_check', False)]
        assert suppressing == []

    def test_the_oauth2_owned_functions_are_not_registered(self):
        """CKAN refuses a duplicate non-chained auth function.

        ``ckanext-oauth2`` registers these four, so claiming any of them here
        would break authorization with both plugins enabled -- which is
        exactly how it runs.

        This guard matters more than it looks, because the failure is not at
        boot: the registry is assembled lazily (``ckan/authz.py:46-56``), so a
        collision surfaces on the first request that checks anything, not on
        startup. A clean start is no evidence that a new registration is safe,
        which leaves this test as the thing that would actually catch it.
        """
        owned_by_oauth2 = {
            u'user_create', u'user_update', u'user_reset', u'request_reset'}
        assert owned_by_oauth2.isdisjoint(auth.__all__)

    def test_every_registered_name_exists(self):
        assert [n for n in auth.__all__ if not hasattr(auth, n)] == []


@pytest.mark.ckan_config(u'ckan.auth.create_unowned_dataset', u'false')
@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestPackageCreateOnTheFormPath(object):
    """package_create is asked twice per dataset, and in two different shapes.

    The config pin matters and one pin is enough, which was checked rather than
    assumed. ``test-core.ini`` sets both ``create_unowned_dataset`` and
    ``create_dataset_if_not_in_organization`` to true where this deployment has
    both false, but core reads them together --
    ``all(check_config_permission(p) for p in (...))``,
    ckan/logic/auth/create.py:24-28 -- so falsifying either one reproduces the
    live answer. Every *bare* ``package_create`` assertion in this file lives in
    this class; the rest pass ``owner_org``, where ``_check_group_auth`` decides
    and neither setting is consulted.

    ``CreateView._prepare`` (ckan/views/dataset.py:516-527) asks it with no
    data_dict at all and aborts 403 if the answer is no, long before the form
    that would supply owner_org is rendered. Checking only the owner_org shape
    left the override working for API callers and unreachable through the UI.

    ``create_unowned_dataset`` is pinned because CKAN's ``test-core.ini``
    sets it to *true* while this deployment's ``ckan.ini`` sets it to
    ``false``. Left alone, stock's first check passes for any logged-in user
    and every assertion below succeeds without exercising anything. Pin it and
    the tests describe the site we actually run.
    """

    def test_program_admin_may_reach_the_add_dataset_form(self, world):
        assert _can(world.program_admin[u'name'], u'package_create')

    def test_and_still_may_create_in_their_own_program(self, world):
        assert _can(world.program_admin[u'name'], u'package_create',
                    owner_org=world.grant_a1[u'id'])

    def test_the_general_answer_does_not_widen_the_specific_one(self, world):
        """Reaching the form is not permission to file it anywhere."""
        assert not _can(world.program_admin[u'name'], u'package_create',
                        owner_org=world.grant_b1[u'id'])
        assert not _can(world.program_admin[u'name'], u'package_create',
                        owner_org=world.grant_orphan[u'id'])

    def test_it_does_not_let_everyone_in(self, world):
        """Stock still decides for anyone who administers no program.

        A Grant Editor is not in this list on purpose: stock already lets them
        reach the form, because ``has_user_permission_for_some_org`` finds
        their ``editor`` row on a real organization. Asserting otherwise would
        be asserting that this override took a permission away.
        """
        for user in (world.program_reader, world.nobody):
            assert not _can(user[u'name'], u'package_create'), user[u'name']
        assert not _can(None, u'package_create')

    def test_a_grant_editor_reaches_the_form_through_stock(self, world):
        assert _can(world.grant_editor[u'name'], u'package_create')

    def test_a_grant_editor_is_unaffected(self, world):
        """Stock already grants them this; the override must not shadow it."""
        assert _can(world.grant_editor[u'name'], u'package_create',
                    owner_org=world.grant_a1[u'id'])
