# encoding: utf-8
"""Tests for the four gaps found by the 2026-09-22 spec-compliance pass.

Each class here corresponds to one paragraph of "Open Data Platform User Roles
and Permissions Redesign" (or, for the user table's scoping, one line item of
the estimates document) that the code did not previously satisfy. The class
docstring quotes the sentence, so if NFWF reads one differently the test to
change is the one that quotes it.

Two of these readings are open rather than settled, and the tests that pin them
say so in their own names -- ``..._is_the_narrower_reading`` and
``..._is_deliberate``. A change to either should change that test and its
docstring together; a reading nobody can find the argument for is how the
previous round of comments in this extension went stale.

Where a rule is defined once and read from several places, the test asks the
definition (``roles.PROGRAM_ADMIN_ASSIGNABLE_ROLES``, ``PROGRAM_CAPACITIES``)
rather than repeating the literal values, so widening one of those lists does
not leave a test asserting the old contents.
"""
import re

import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles
from ckanext.nfwf_permissions.logic import action


def _assign(group_id, user_name, capacity):
    """Add a membership the internal way, bypassing the guards."""
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


def _as(user_name, action, **data_dict):
    """Call an action with authorization and the guards actually enforced."""
    return helpers.call_action(
        action, context={u'user': user_name, u'ignore_auth': False},
        **data_dict)


class World(object):
    """Two programs, each with a grant, and one account per interesting case."""

    def __init__(self):
        self.program_a = factories.Group()
        self.program_b = factories.Group()
        self.grant_a = self._grant(self.program_a[u'id'])
        self.grant_b = self._grant(self.program_b[u'id'])

        self.sysadmin = factories.Sysadmin()
        self.admin_a = factories.User()      # Program Administrator of A
        self.reader_a = factories.User()     # Program Reader in A
        self.editor_a = factories.User()     # Grant Editor on a grant in A
        self.reader_b = factories.User()     # Program Reader in B, out of reach
        self.newcomer = factories.User()     # registered, no assignment at all

        _assign(self.program_a[u'id'], self.admin_a[u'name'],
                roles.CAPACITY_ADMIN)
        _assign(self.program_a[u'id'], self.reader_a[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(self.grant_a[u'id'], self.editor_a[u'name'],
                roles.CAPACITY_EDITOR)
        _assign(self.program_b[u'id'], self.reader_b[u'name'],
                roles.CAPACITY_MEMBER)

        # The writes above changed what `roles` would answer, and it memoizes.
        roles.clear_cache()

    @staticmethod
    def _grant(program_id):
        return factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': program_id}])


@pytest.fixture
def world(clean_db):
    return World()


def _names(result):
    return {record[u'name'] for record in result[u'results']}


@pytest.mark.usefixtures(u'with_plugins')
class TestProgramAdminsMayAssignRoles(object):
    """Redesign, Program Administrator:

    "Assign user permissions for their program-associated grants/program
    reader."

    Before 2026-09-22 every ``nfwf_user_*`` action was Platform Administrator
    only, so a Program Administrator could not open the Manage Roles modal at
    all -- not even to read the role vocabulary.
    """

    def test_they_can_reach_the_user_list(self, world):
        result = _as(world.admin_a[u'name'], u'nfwf_user_list')

        assert world.reader_a[u'name'] in _names(result)

    def test_they_can_read_the_role_vocabulary(self, world):
        options = _as(world.admin_a[u'name'], u'nfwf_role_options')

        assert options[u'roles']

    def test_they_can_make_someone_a_grant_editor_in_their_program(
            self, world):
        result = _as(
            world.admin_a[u'name'], u'nfwf_user_role_set',
            id=world.newcomer[u'name'], role=roles.GRANT_EDITOR,
            grant_ids=[world.grant_a[u'id']])

        assert result[u'role'] == roles.GRANT_EDITOR
        assert [grant[u'id'] for grant in result[u'grants']] == [
            world.grant_a[u'id']]

    def test_they_can_make_someone_a_program_reader(self, world):
        result = _as(
            world.admin_a[u'name'], u'nfwf_user_role_set',
            id=world.newcomer[u'name'], role=roles.PROGRAM_READER,
            program_ids=[world.program_a[u'id']])

        assert result[u'role'] == roles.PROGRAM_READER

    def test_account_approval_is_still_platform_administrator_only(
            self, world):
        """The document lists "Approve new/remove user accounts" under
        Platform Administrator alone, and does not repeat it under Program
        Administrator. That asymmetry is the reason `logic/auth.py` keeps two
        helpers rather than one."""
        for action in (u'nfwf_user_approve', u'nfwf_user_reject',
                       u'nfwf_user_deactivate'):
            with pytest.raises(toolkit.NotAuthorized):
                _as(world.admin_a[u'name'], action,
                    id=world.newcomer[u'name'])

    def test_someone_with_no_role_is_still_refused(self, world):
        with pytest.raises(toolkit.NotAuthorized):
            _as(world.newcomer[u'name'], u'nfwf_user_list')

    def test_a_program_reader_is_still_refused(self, world):
        """Read-only is the whole point of the role."""
        with pytest.raises(toolkit.NotAuthorized):
            _as(world.reader_a[u'name'], u'nfwf_user_list')


@pytest.mark.usefixtures(u'with_plugins')
class TestTheScopeOfThatPermission(object):
    """Estimates, Task 117: "Platform Admin sees all; Program Admin sees their
    program".

    An auth function can only answer all-or-nothing, so this half of the rule
    lives in the actions. Letting a Program Administrator in without it would
    have handed them every account on the site.
    """

    def test_they_do_not_see_another_programs_users(self, world):
        result = _as(world.admin_a[u'name'], u'nfwf_user_list')

        assert world.reader_b[u'name'] not in _names(result)

    def test_they_do_not_see_platform_administrators(self, world):
        """A Platform Administrator's program rows are retained but not
        consulted, so without the sysadmin check in `roles.is_within_scope`
        one of them assigned to program A would appear here -- and be
        demotable."""
        _assign(world.program_a[u'id'], world.sysadmin[u'name'],
                roles.CAPACITY_MEMBER)
        roles.clear_cache()

        result = _as(world.admin_a[u'name'], u'nfwf_user_list')

        assert world.sysadmin[u'name'] not in _names(result)

    def test_they_do_see_accounts_with_no_assignment_yet_which_is_deliberate(
            self, world):
        """OPEN. Hiding them is the literal reading of "sees their program",
        but it would leave a Program Administrator unable to give anyone a
        first role. The two lines that decide it are marked in
        `roles.is_within_scope`."""
        result = _as(world.admin_a[u'name'], u'nfwf_user_list')

        assert world.newcomer[u'name'] in _names(result)

    def test_a_platform_administrator_still_sees_everyone(self, world):
        result = _as(world.sysadmin[u'name'], u'nfwf_user_list')

        assert world.reader_b[u'name'] in _names(result)

    def test_reading_an_out_of_scope_account_is_a_404_not_a_403(self, world):
        """Deliberate: the caller has no business learning whether an id they
        cannot act on exists, and a wrong id looks the same as a forbidden
        one."""
        with pytest.raises(toolkit.ObjectNotFound):
            _as(world.admin_a[u'name'], u'nfwf_user_role_show',
                id=world.reader_b[u'name'])

    def test_they_cannot_touch_an_out_of_scope_account(self, world):
        with pytest.raises(toolkit.ObjectNotFound):
            _as(world.admin_a[u'name'], u'nfwf_user_role_set',
                id=world.reader_b[u'name'], role=roles.GRANT_EDITOR,
                grant_ids=[world.grant_a[u'id']])

    def test_they_cannot_assign_another_programs_grant(self, world):
        with pytest.raises(toolkit.ValidationError):
            _as(world.admin_a[u'name'], u'nfwf_user_role_set',
                id=world.newcomer[u'name'], role=roles.GRANT_EDITOR,
                grant_ids=[world.grant_b[u'id']])

    def test_they_cannot_assign_another_program(self, world):
        with pytest.raises(toolkit.ValidationError):
            _as(world.admin_a[u'name'], u'nfwf_user_role_set',
                id=world.newcomer[u'name'], role=roles.PROGRAM_READER,
                program_ids=[world.program_b[u'id']])

    def test_they_cannot_appoint_a_platform_administrator(self, world):
        """The document reserves "including other Platform Administrators" to
        Platform Administrators, and this is the check that means it."""
        with pytest.raises(toolkit.ValidationError):
            _as(world.admin_a[u'name'], u'nfwf_user_role_set',
                id=world.newcomer[u'name'], role=roles.PLATFORM_ADMIN)

    def test_they_cannot_appoint_a_peer_which_is_the_narrower_reading(
            self, world):
        """OPEN. The document names Grant Editor and Program Reader/Member and
        is silent on whether a Program Administrator may appoint another one,
        so `roles.PROGRAM_ADMIN_ASSIGNABLE_ROLES` leaves it out.

        If NFWF says they may, add PROGRAM_ADMIN to that list and turn this
        into its mirror image -- the modal narrows itself from the same list,
        so nothing else changes.
        """
        assert roles.PROGRAM_ADMIN not in roles.PROGRAM_ADMIN_ASSIGNABLE_ROLES

        with pytest.raises(toolkit.ValidationError):
            _as(world.admin_a[u'name'], u'nfwf_user_role_set',
                id=world.newcomer[u'name'], role=roles.PROGRAM_ADMIN,
                program_ids=[world.program_a[u'id']])

    def test_the_modal_is_offered_only_what_it_may_save(self, world):
        options = _as(world.admin_a[u'name'], u'nfwf_role_options')

        assert {option[u'value'] for option in options[u'roles']} == set(
            roles.PROGRAM_ADMIN_ASSIGNABLE_ROLES)
        assert [program[u'id'] for program in options[u'programs']] == [
            world.program_a[u'id']]

    def test_a_platform_administrator_is_offered_everything(self, world):
        options = _as(world.sysadmin[u'name'], u'nfwf_role_options')

        assert {option[u'value']
                for option in options[u'roles']} == set(roles.ROLES)
        assert len(options[u'programs']) == 2


@pytest.mark.usefixtures(u'with_plugins')
class TestProgramCapacities(object):
    """Redesign: a program carries Program Administrator and Program
    Reader/Member. CKAN also offers ``editor``, which is not a role here.

    An ``editor`` row on a program used to be accepted. It resolves to no role
    through ``roles.user_role`` and earns no permission labels, so the account
    read as roleless on the user-management screen while holding CKAN's
    ``manage_group`` on the program.
    """

    def test_editor_is_refused_on_a_program(self, world):
        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'], u'group_member_create',
                id=world.program_a[u'id'], username=world.newcomer[u'name'],
                role=roles.CAPACITY_EDITOR)

    def test_member_create_refuses_it_too(self, world):
        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'], u'member_create',
                id=world.program_a[u'id'], object=world.newcomer[u'name'],
                object_type=u'user', capacity=roles.CAPACITY_EDITOR)

    @pytest.mark.parametrize(u'capacity', [u'admin', u'member'])
    def test_the_two_real_program_roles_still_work(self, capacity, world):
        _as(world.sysadmin[u'name'], u'group_member_create',
            id=world.program_a[u'id'], username=world.newcomer[u'name'],
            role=capacity)

        assert world.program_a[u'id'] in roles.programs_for_user(
            world.newcomer[u'name'])

    def test_a_grant_is_unaffected(self, world):
        """The grant rule is the retired-capacity one and is older than this;
        this only checks the new branch did not swallow it."""
        _as(world.sysadmin[u'name'], u'organization_member_create',
            id=world.grant_a[u'id'], username=world.newcomer[u'name'],
            role=roles.CAPACITY_EDITOR)

        assert world.grant_a[u'id'] in roles.grants_for_user(
            world.newcomer[u'name'])


@pytest.mark.usefixtures(u'with_plugins')
class TestMemberRoleOptions(object):
    """The Role dropdown on both stock Members screens.

    Presentation only: every server-side guard above stays in place whatever
    this returns. It exists so the screens stop offering choices that are then
    refused on save.
    """

    def test_a_grant_offers_only_grant_editor(self, world):
        options = helpers.call_action(
            u'member_roles_list', group_type=u'organization')

        assert [option[u'value']
                for option in options] == roles.GRANT_CAPACITIES

    def test_a_program_offers_its_two_roles_and_not_editor(self, world):
        options = helpers.call_action(
            u'member_roles_list', group_type=u'group')
        values = [option[u'value'] for option in options]

        assert roles.CAPACITY_EDITOR not in values
        assert set(values) == set(roles.PROGRAM_CAPACITIES)

    def test_nothing_is_ever_offered_that_the_guards_refuse(self, world):
        """The point of the whole class, stated once as a property.

        Every capacity the grant screen offers must survive
        `organization_member_create`, and the same for the program screen.
        """
        offered = [option[u'value'] for option in helpers.call_action(
            u'member_roles_list', group_type=u'organization')]

        assert not set(offered) & set(roles.RETIRED_GRANT_CAPACITIES)


@pytest.mark.usefixtures(u'with_plugins')
class TestGrantEditorDeletes(object):
    """Redesign, Grant Editor: "Add/edit/**delete** datasets and resources
    under the grant."

    Add and edit were covered; delete was the one verb in the document with no
    test behind it. Nothing is overridden for it -- CKAN's ``editor`` capacity
    carries ``delete_dataset`` and ``package_delete`` defers to
    ``package_update`` -- so this is a regression guard on an *absence*, like
    the others in ``test_auth.py``.
    """

    def test_they_can_delete_in_their_own_grant(self, world):
        dataset = factories.Dataset(owner_org=world.grant_a[u'id'])

        assert helpers.call_auth(
            u'package_delete',
            {u'model': model, u'user': world.editor_a[u'name'],
             u'auth_user_obj': model.User.get(world.editor_a[u'id'])},
            id=dataset[u'id'])

    def test_they_cannot_delete_in_a_grant_they_do_not_hold(self, world):
        dataset = factories.Dataset(owner_org=world.grant_b[u'id'])

        with pytest.raises(toolkit.NotAuthorized):
            helpers.call_auth(
                u'package_delete',
                {u'model': model, u'user': world.editor_a[u'name'],
                 u'auth_user_obj': model.User.get(world.editor_a[u'id'])},
                id=dataset[u'id'])


@pytest.mark.usefixtures(u'with_plugins')
class TestRoleChangeIsNotAtomic(object):
    """`_apply_role` clears one scope then writes the other, and each half
    commits. A failure between them used to leave the account holding nothing,
    silently -- the cleared rows were marked `deleted`, so the information
    survived, but nobody was told where to look.

    Reordering is not the fix and an earlier docstring was wrong about why: the
    guards it said would refuse a write-first order are bypassed by the
    `ignore_auth` that same path passes. Writing first is allowed; it just
    leaves the account holding both scopes instead, which is the
    conflict-of-interest state the one-role rule exists to prevent.
    """

    def _explode_on_the_second_call(self, monkeypatch):
        real = action._replace_memberships
        calls = []

        def exploding(context, user, is_organization, groups, capacity):
            calls.append(is_organization)
            if len(calls) == 2:
                raise RuntimeError(u'simulated failure writing the new scope')
            return real(context, user, is_organization, groups, capacity)

        monkeypatch.setattr(action, u'_replace_memberships', exploding)

    def test_the_previous_role_is_put_back(self, world, monkeypatch):
        assert roles.user_role(world.reader_a[u'name']) == roles.PROGRAM_READER
        self._explode_on_the_second_call(monkeypatch)

        with pytest.raises(RuntimeError):
            _as(world.sysadmin[u'name'], u'nfwf_user_role_set',
                id=world.reader_a[u'name'], role=roles.GRANT_EDITOR,
                grant_ids=[world.grant_a[u'id']])

        roles.clear_cache()
        assert roles.user_role(world.reader_a[u'name']) == roles.PROGRAM_READER
        assert roles.programs_for_user(world.reader_a[u'name']) == frozenset(
            [world.program_a[u'id']])

    def test_the_failure_is_still_raised(self, world, monkeypatch):
        """Restoring must not turn a failed write into a reported success."""
        self._explode_on_the_second_call(monkeypatch)

        with pytest.raises(RuntimeError):
            _as(world.sysadmin[u'name'], u'nfwf_user_role_set',
                id=world.reader_a[u'name'], role=roles.GRANT_EDITOR,
                grant_ids=[world.grant_a[u'id']])

    def test_an_account_with_nothing_to_restore_is_unharmed(
            self, world, monkeypatch):
        """The newcomer holds no assignment, so there is nothing to put back
        and the restore path must not invent one."""
        self._explode_on_the_second_call(monkeypatch)

        with pytest.raises(RuntimeError):
            _as(world.sysadmin[u'name'], u'nfwf_user_role_set',
                id=world.newcomer[u'name'], role=roles.GRANT_EDITOR,
                grant_ids=[world.grant_a[u'id']])

        roles.clear_cache()
        assert roles.user_role(world.newcomer[u'name']) is None
        assert not roles.grants_for_user(world.newcomer[u'name'])

    def test_capacities_are_restored_per_group_not_flattened(self, world):
        """`assignments_for_user` carries the capacity of each row.

        Pre-migration accounts hold different capacities on different grants,
        so a restore that wrote one capacity across all of them would quietly
        re-grade some. This pins the accessor the restore depends on.
        """
        other = factories.Organization(extras=[{
            u'key': roles.OWNER_GROUP_EXTRA,
            u'value': world.program_a[u'id']}])
        _assign(other[u'id'], world.editor_a[u'name'], roles.CAPACITY_EDITOR)
        roles.clear_cache()

        held = dict(roles.assignments_for_user(world.editor_a[u'name'], True))

        assert held[world.grant_a[u'id']] == roles.CAPACITY_EDITOR
        assert held[other[u'id']] == roles.CAPACITY_EDITOR


@pytest.mark.usefixtures(u'with_plugins')
class TestDualScopeAccountsAreOutOfReach(object):
    """An account holding assignments on both sides of the caller's scope.

    Not an edge case: the migration report shows most production accounts are
    currently like this, because one-role-per-user postdates the data.

    `is_within_scope` used to admit an account if *any* assignment intersected
    the scope, which leaked and also made the modal unusable. See its docstring
    for both. These pin the behaviour that replaced it.
    """

    @pytest.fixture
    def dual(self, world):
        """Holds program A -- the caller's -- and a grant under program B."""
        user = factories.User()
        _assign(world.program_a[u'id'], user[u'name'], roles.CAPACITY_MEMBER)
        _assign(world.grant_b[u'id'], user[u'name'], roles.CAPACITY_EDITOR)
        roles.clear_cache()
        return user

    def test_the_other_programs_grant_is_not_disclosed(self, world, dual):
        """The leak itself: the record named a grant from another program."""
        listed = _as(world.admin_a[u'name'], u'nfwf_user_list')
        rows = {record[u'name']: record for record in listed[u'results']}

        assert dual[u'name'] not in rows

    def test_the_modal_cannot_open_on_one_either(self, world, dual):
        """The same record reached through `nfwf_user_role_show`.

        Closing only the list would have left the modal leaking it, since both
        read the same record.
        """
        with pytest.raises(toolkit.ObjectNotFound):
            _as(world.admin_a[u'name'], u'nfwf_user_role_show',
                id=dual[u'name'])

    def test_and_cannot_be_written_to(self, world, dual):
        """The trap, not just the disclosure.

        `nfwf_user_role_set` replaces assignments wholesale. Reachable-but-
        unsavable was the old behaviour; now it is simply out of reach, so a
        Program Administrator cannot half-rewrite an account whose other half
        they cannot see.
        """
        with pytest.raises(toolkit.ObjectNotFound):
            _as(world.admin_a[u'name'], u'nfwf_user_role_set',
                id=dual[u'name'], role=roles.GRANT_EDITOR,
                grant_ids=[world.grant_a[u'id']])

    def test_a_platform_administrator_still_sees_them(self, world, dual):
        """Somebody has to be able to resolve these, and it is not the Program
        Administrator -- deciding which side the account keeps is exactly the
        call one-role-per-user reserves for a Platform Administrator."""
        listed = _as(world.sysadmin[u'name'], u'nfwf_user_list')

        assert dual[u'name'] in {r[u'name'] for r in listed[u'results']}

    def test_an_account_wholly_inside_the_scope_is_still_reachable(
            self, world):
        """The narrowing must not catch accounts that only look dual-scope.

        Program A plus a grant *under* program A is still one-role-per-user
        breakage, but every row sits inside this caller's scope, so resolving
        it is their business and they keep the access to do it.
        """
        user = factories.User()
        _assign(world.program_a[u'id'], user[u'name'], roles.CAPACITY_MEMBER)
        _assign(world.grant_a[u'id'], user[u'name'], roles.CAPACITY_EDITOR)
        roles.clear_cache()

        listed = _as(world.admin_a[u'name'], u'nfwf_user_list')

        assert user[u'name'] in {r[u'name'] for r in listed[u'results']}


@pytest.mark.usefixtures(u'with_plugins')
class TestPermissionLabelsDoNotBloat(object):
    """The chained `organization_list_for_user` must not inflate the label set.

    CKAN builds `member-<org id>` labels by calling that action with
    `permission='read'`, so augmenting it put one label on a Program
    Administrator for every grant in their programs. On the production snapshot
    that was 494 labels, 488 of them `member-`, against a single real
    membership row -- and it becomes a Solr filter query of that many OR'd
    terms on every search they run.

    They were pure dead weight: `labels.py` gives the same user `program-<id>`
    and `in-any-program`, which match exactly the same datasets.
    """

    def test_read_does_not_get_the_extra_grants(self, world):
        from ckanext.nfwf_permissions import labels

        held = roles.grants_for_user(world.admin_a[u'name'])
        user = model.User.get(world.admin_a[u'id'])
        got = labels.NfwfPermissionLabels().get_user_dataset_labels(user)
        member = [l for l in got if l.startswith(u'member-')]

        assert len(member) == len(held)

    def test_but_the_form_still_gets_them(self, world):
        """The reason the augmentation exists at all: without this the Grant
        selector renders empty and a Program Administrator cannot create a
        dataset. Every selector asks for `create_dataset`."""
        orgs = _as(world.admin_a[u'name'], u'organization_list_for_user',
                   permission=u'create_dataset')

        assert world.grant_a[u'id'] in {o[u'id'] for o in orgs}

    @pytest.mark.parametrize(u'permission', [u'read', u'manage_group', None])
    def test_the_belonging_questions_get_the_plain_answer(
            self, permission, world):
        """`read` builds permission labels and `manage_group` renders the
        My Organizations dashboard -- both ask who the user *belongs* to, and
        answering with every grant in the program cost ~490 redundant labels
        and a 640KB page respectively. `None` is in here because CKAN's default
        is `manage_group`, so omitting the parameter must behave the same."""
        kwargs = {} if permission is None else {u'permission': permission}
        orgs = _as(world.admin_a[u'name'], u'organization_list_for_user',
                   **kwargs)

        assert world.grant_a[u'id'] not in {o[u'id'] for o in orgs}

    def test_and_the_access_those_labels_carried_is_unchanged(self, world):
        """What matters is reach, not which label provides it."""
        from ckanext.nfwf_permissions import labels

        private = factories.Dataset(owner_org=world.grant_a[u'id'],
                                    private=True)
        pkg = model.Package.get(private[u'id'])
        roles.clear_cache()

        on_dataset = set(
            labels.NfwfPermissionLabels().get_dataset_labels(pkg))
        on_user = set(labels.NfwfPermissionLabels().get_user_dataset_labels(
            model.User.get(world.admin_a[u'id'])))

        assert on_dataset & on_user, (
            u'the Program Administrator lost sight of a private dataset in '
            u'their own program')


@pytest.mark.ckan_config(u'ckan.auth.public_user_details', u'false')
@pytest.mark.usefixtures(u'with_plugins')
class TestSeeingWhoIsAssigned(object):
    """A Program Administrator must be able to read a grant's member list.

    **Pinned to the deployment's config, and the whole finding depends on it.**
    CKAN's `test-core.ini` leaves `ckan.auth.public_user_details` at ``true``,
    which makes stock `group_show` return success early for everyone -- member
    lists open to the world, nothing to deny, and the negative tests below
    silently vacuous. This site sets it ``false`` (verified on the running
    container), which is what exposes the gap in the first place. Without this
    marker the suite would have agreed the code was fine while the real site
    returned 403.

    Found by rendering the pages, not by reading code: the Members tab of a
    grant returned 403 while the Add Member page beside it returned 200. They
    could assign a Grant Editor but not see who was already assigned.

    The check that refused is inside the `member_list` *action*, not its auth
    function -- `check_access('member_list')` passes, then the action calls
    `group_show` with `object_type='user'`, which skips stock's permissive
    early return and falls through to a membership check the role model
    deliberately does not give them.

    Driven through the action here for that reason; a `check_access` test would
    have passed against the broken code.
    """

    def test_they_can_read_a_grant_in_their_program(self, world):
        result = _as(world.admin_a[u'name'], u'member_list',
                     id=world.grant_a[u'id'], object_type=u'user')

        assert isinstance(result, list)

    def test_they_cannot_read_a_grant_in_another_program(self, world):
        with pytest.raises(toolkit.NotAuthorized):
            _as(world.admin_a[u'name'], u'member_list',
                id=world.grant_b[u'id'], object_type=u'user')

    def test_their_own_program_still_works(self, world):
        """This path was never broken -- they hold an admin row on the program
        itself, so stock's membership check already passed. Guarding it so the
        new branch cannot quietly take it over."""
        result = _as(world.admin_a[u'name'], u'member_list',
                     id=world.program_a[u'id'], object_type=u'user')

        assert isinstance(result, list)

    def test_a_program_reader_is_not_let_in(self, world):
        """The widening must reach exactly one role."""
        with pytest.raises(toolkit.NotAuthorized):
            _as(world.reader_a[u'name'], u'member_list',
                id=world.grant_a[u'id'], object_type=u'user')

    def test_the_ordinary_group_page_is_unaffected(self, world):
        """Stock `group_show` is permissive when the caller is not asking about
        users, and that must stay true for everyone -- the override only ever
        adds."""
        result = helpers.call_action(
            u'organization_show',
            context={u'user': world.newcomer[u'name'], u'ignore_auth': False},
            id=world.grant_b[u'id'])

        assert result[u'id'] == world.grant_b[u'id']


@pytest.mark.usefixtures(u'with_plugins')
class TestRemovingAMember(object):
    """Removal is half of "assign user permissions", and it is enforced in a
    place `check_access` does not reach.

    Core's `organization_member_delete` and `group_member_delete` auth
    functions return True unconditionally; the real decision happens inside the
    action, which re-checks through `member_delete` -> `member_create` -> ours.
    So `check_access` says YES to a caller with no role at all, and that is
    harmless only for as long as the action really does re-check.

    That is the same shape as the bug in `member_list`, where the action's own
    check was the thing refusing a Program Administrator. There it was too
    strict for this model; here it is exactly right. Either way the only way to
    know is to drive the action, which is what these do.
    """

    @pytest.fixture
    def victim(self, world):
        """Someone holding a Grant Editor row in the caller's program."""
        user = factories.User()
        _assign(world.grant_a[u'id'], user[u'name'], roles.CAPACITY_EDITOR)
        roles.clear_cache()
        return user

    def test_the_programs_administrator_can_remove_them(self, world, victim):
        _as(world.admin_a[u'name'], u'organization_member_delete',
            id=world.grant_a[u'id'], user_id=victim[u'name'])
        roles.clear_cache()

        assert not roles.grants_for_user(victim[u'name'])

    @pytest.mark.parametrize(u'actor', [u'reader_a', u'newcomer'])
    def test_others_cannot_however_permissive_check_access_is(
            self, actor, world, victim):
        name = getattr(world, actor)[u'name']

        # The permissive half, asserted so the test says why it exists.
        helpers.call_auth(
            u'organization_member_delete',
            {u'model': model, u'user': name,
             u'auth_user_obj': model.User.get(name)},
            id=world.grant_a[u'id'])

        with pytest.raises(toolkit.NotAuthorized):
            _as(name, u'organization_member_delete',
                id=world.grant_a[u'id'], user_id=victim[u'name'])
        roles.clear_cache()

        assert roles.grants_for_user(victim[u'name']), (
            u'the member was stripped by somebody who should not be able to')

    def test_another_programs_administrator_cannot(self, world, victim):
        """The cross-program boundary has to hold on removal too, not only on
        the add."""
        other_admin = factories.User()
        _assign(world.program_b[u'id'], other_admin[u'name'],
                roles.CAPACITY_ADMIN)
        roles.clear_cache()

        with pytest.raises(toolkit.NotAuthorized):
            _as(other_admin[u'name'], u'organization_member_delete',
                id=world.grant_a[u'id'], user_id=victim[u'name'])
        roles.clear_cache()

        assert roles.grants_for_user(victim[u'name'])


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestOwnerGroupMustNameAProgram(object):
    """`owner_group` was free-form for the callers most able to write to it.

    `_assert_grant_belongs_to_an_administered_program` decides *which* program
    a caller may file a grant under, and exempts Platform Administrators and
    `ignore_auth` outright -- correctly, since a grant belonging to no program
    could not otherwise be created. The side effect was that the field took any
    string at all from a sysadmin: a typo, a stale id, or a grant id pasted
    where a program id belongs.

    Nothing stored on production fails the new check -- 540 valid, 31 empty,
    zero dangling -- so this pins the current shape rather than tightening
    against it.
    """

    def _sysadmin(self):
        return factories.Sysadmin()

    def test_a_grant_id_is_refused(self):
        """The paste most likely to happen, and the one the read path
        silently swallows: `program_id` returns None for an organization."""
        grant = factories.Organization()
        with pytest.raises(toolkit.ValidationError) as caught:
            helpers.call_action(
                u'organization_create',
                context={u'user': self._sysadmin()[u'name']},
                name=u'probe-grant-named-by-a-grant',
                extras=[{u'key': roles.OWNER_GROUP_EXTRA,
                         u'value': grant[u'id']}])
        assert u'owner_group' in caught.value.error_dict

    def test_an_unknown_reference_is_refused(self):
        with pytest.raises(toolkit.ValidationError) as caught:
            helpers.call_action(
                u'organization_create',
                context={u'user': self._sysadmin()[u'name']},
                name=u'probe-grant-unknown-program',
                extras=[{u'key': roles.OWNER_GROUP_EXTRA,
                         u'value': u'no-such-program'}])
        assert u'owner_group' in caught.value.error_dict

    def test_a_deleted_program_is_refused(self):
        program = factories.Group()
        sysadmin = self._sysadmin()
        helpers.call_action(u'group_delete',
                            context={u'user': sysadmin[u'name']},
                            id=program[u'id'])
        roles.clear_cache()
        with pytest.raises(toolkit.ValidationError) as caught:
            helpers.call_action(
                u'organization_create', context={u'user': sysadmin[u'name']},
                name=u'probe-grant-deleted-program',
                extras=[{u'key': roles.OWNER_GROUP_EXTRA,
                         u'value': program[u'id']}])
        assert u'owner_group' in caught.value.error_dict

    def test_empty_is_still_allowed(self):
        """31 grants are in this state and `orphan_grants` reports them. A
        Platform Administrator has to be able to create a grant before
        deciding where it belongs."""
        created = helpers.call_action(
            u'organization_create', context={u'user': self._sysadmin()[u'name']},
            name=u'probe-grant-no-program',
            extras=[{u'key': roles.OWNER_GROUP_EXTRA, u'value': u''}])

        assert created[u'id']
        assert roles.program_id_for_grant(created[u'id']) is None

    def test_a_real_program_is_accepted(self):
        program = factories.Group()
        created = helpers.call_action(
            u'organization_create', context={u'user': self._sysadmin()[u'name']},
            name=u'probe-grant-real-program',
            extras=[{u'key': roles.OWNER_GROUP_EXTRA,
                     u'value': program[u'id']}])
        roles.clear_cache()

        assert roles.program_id_for_grant(created[u'id']) == program[u'id']

    def test_the_top_level_field_is_checked_too(self):
        """The route the grant form actually uses.

        `nfwf_fields._modify_group_schema` puts `convert_to_extras` on
        `owner_group`, and that runs during validation -- after a chained
        action sees the data -- so every form submission arrives top level
        and only an API caller builds `extras` directly. Both are checked.
        """
        grant = factories.Organization()
        with pytest.raises(toolkit.ValidationError) as caught:
            helpers.call_action(
                u'organization_create',
                context={u'user': self._sysadmin()[u'name']},
                name=u'probe-grant-top-level', owner_group=grant[u'id'])
        assert u'owner_group' in caught.value.error_dict

    def test_it_holds_on_update_too(self):
        """`organization_patch` merges onto the stored record and calls
        `organization_update`, so covering update covers patch."""
        program = factories.Group()
        sysadmin = self._sysadmin()
        grant = factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': program[u'id']}])

        with pytest.raises(toolkit.ValidationError) as caught:
            helpers.call_action(
                u'organization_update', context={u'user': sysadmin[u'name']},
                id=grant[u'id'], name=grant[u'name'],
                extras=[{u'key': roles.OWNER_GROUP_EXTRA,
                         u'value': u'no-such-program'}])
        assert u'owner_group' in caught.value.error_dict


@pytest.mark.usefixtures(u'clean_db', u'with_plugins')
class TestOwnerGroupThroughTheForm(object):
    """The same guard, driven through the view instead of `call_action`.

    Every other test in this suite calls actions directly, which skips two
    things the real path does. The view builds `data_dict` from posted form
    fields, so a value arrives as whatever the form spells it -- the grant
    form's selector posts a program *name* where the tests above post ids, and
    `roles.program_id` resolving both was asserted rather than run. And a
    `ValidationError` raised inside an action has to come back as the form
    re-rendered with the message on the field; `ckan/views/group.py` turns a
    `NotAuthorized` into `abort(404)` instead, which is exactly why the
    sibling guard raises `ValidationError` rather than refusing outright.

    **What this config cannot reach.** `test.ini` loads only
    `nfwf_permissions`, so this is stock CKAN's organization form, not the one
    `nfwf_fields` builds. The guard still *sees* a top-level `owner_group`,
    because it reads `data_dict` before validation -- which is what these
    tests exercise -- but stock never *stores* it, since `convert_to_extras`
    lives in `nfwf_fields`. So storage is asserted at action level above and
    against the running site, not here. The `extras` route likewise reaches
    the guard through the API rather than through this form, and is covered by
    `TestOwnerGroupMustNameAProgram`; the update path by
    `test_it_holds_on_update_too` there.

    Follows CKAN's own controller tests (`ckan/tests/controllers/test_group.py`)
    in using the `app` fixture with a token header. Driving
    `app.flask_app.test_client()` directly instead leaves a session holding
    locks, and `clean_db`'s teardown then deadlocks against it on
    `DROP TABLE api_token`.
    """

    @pytest.fixture
    def headers(self):
        # Cleared per test: these run after TestOwnerGroupMustNameAProgram,
        # and a carried-over resolution makes a valid program name look
        # unknown -- which reads as the guard refusing a good value.
        roles.clear_cache()
        return {u'Authorization': factories.SysadminWithToken()[u'token']}

    def test_a_program_name_is_accepted(self, app, headers):
        """The form's selector posts a name, not an id, and `program_id`
        resolving both was asserted rather than run until this test."""
        program = factories.Group()

        response = app.post(
            url=u'/organization/new', headers=headers,
            data={u'name': u'form-grant-ok', u'title': u'Ok',
                  u'owner_group': program[u'name'], u'save': u''})

        assert u'is not an active program' not in response.body
        assert model.Group.by_name(u'form-grant-ok') is not None, (
            u'a valid program name was refused')

    def test_a_grant_name_is_refused_on_the_form(self, app, headers):
        """Re-rendered with the message, not a 404 and not a 500.

        The paste most likely to happen once the selector lists both kinds of
        group, and the one the read path silently swallows.
        """
        grant = factories.Organization()

        response = app.post(
            url=u'/organization/new', headers=headers,
            data={u'name': u'form-grant-bad', u'title': u'Bad',
                  u'owner_group': grant[u'name'], u'save': u''})

        assert u'is not an active program' in response.body
        assert model.Group.by_name(u'form-grant-bad') is None

    def test_an_unknown_reference_is_refused_on_the_form(self, app, headers):
        response = app.post(
            url=u'/organization/new', headers=headers,
            data={u'name': u'form-grant-unknown', u'title': u'Unknown',
                  u'owner_group': u'no-such-program', u'save': u''})

        assert u'is not an active program' in response.body
        assert model.Group.by_name(u'form-grant-unknown') is None
