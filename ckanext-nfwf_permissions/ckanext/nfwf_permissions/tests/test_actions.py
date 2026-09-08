# encoding: utf-8
"""Tests for the chained core actions.

``logic/auth.py`` decides *whether* a Program Administrator may create or edit
a grant. These decide *which program* it may be filed under -- a rule that
depends on submitted data and has to hold on update as well as create.

Note that ``nfwf_fields`` is not loaded here, so ``owner_group`` is not part of
the organization schema and the original action drops it. That is fine and in
fact the point: the check reads the raw ``data_dict`` before the original
action runs, so it does not depend on any schema being installed. What these
tests exercise is the gate, not the storage.
"""
import pytest

import ckan.logic as logic
import ckan.tests.factories as factories
import ckan.tests.helpers as helpers

from ckanext.nfwf_permissions import roles


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


def _as(user_name, action, **data_dict):
    """Call an action as ``user_name`` with authorization actually enforced.

    ``helpers.call_action`` defaults ``ignore_auth`` to True, which the chained
    check honours -- so without turning it off these tests would pass no matter
    what the code did.
    """
    return helpers.call_action(
        action, context={u'user': user_name, u'ignore_auth': False},
        **data_dict)


class Programs(object):
    """Two programs, a Program Administrator of one, and a Platform Admin."""

    def __init__(self):
        self.program_mine = factories.Group()
        self.program_theirs = factories.Group()

        self.program_admin = factories.User()
        self.platform_admin = factories.Sysadmin()
        _assign(self.program_mine[u'id'], self.program_admin[u'name'],
                roles.CAPACITY_ADMIN)


@pytest.fixture
def programs(clean_db):
    """Depends on ``clean_db`` explicitly, and that dependency is the point.

    As an ``autouse`` fixture this built its users and groups *before*
    ``clean_db`` ran, and ``clean_db`` then dropped every table -- so the
    sysadmin did not exist, ``is_sysadmin`` was false, the programs did not
    resolve, and every negative test passed for entirely the wrong reason.
    Naming ``clean_db`` as an argument forces it to run first.
    """
    return Programs()


@pytest.mark.ckan_config(u'ckan.auth.user_create_organizations', u'false')
@pytest.mark.usefixtures(u'with_plugins')
class TestGrantMustBelongToAnAdministeredProgram(object):

    # -- Creating ------------------------------------------------------------

    def test_program_admin_creates_a_grant_in_their_own_program(self, programs):
        result = _as(programs.program_admin[u'name'], u'organization_create',
                     name=u'grant-in-my-program',
                     owner_group=programs.program_mine[u'id'])

        assert result[u'name'] == u'grant-in-my-program'

    def test_a_program_name_works_as_well_as_an_id(self, programs):
        result = _as(programs.program_admin[u'name'], u'organization_create',
                     name=u'grant-by-program-name',
                     owner_group=programs.program_mine[u'name'])

        assert result[u'name'] == u'grant-by-program-name'

    def test_program_admin_cannot_create_under_another_program(self, programs):
        with pytest.raises(logic.NotAuthorized):
            _as(programs.program_admin[u'name'], u'organization_create',
                name=u'grant-in-their-program',
                owner_group=programs.program_theirs[u'id'])

    def test_program_admin_cannot_create_a_grant_with_no_program(self, programs):
        with pytest.raises(logic.NotAuthorized):
            _as(programs.program_admin[u'name'], u'organization_create',
                name=u'orphan-grant')

    def test_program_admin_cannot_create_with_an_empty_program(self, programs):
        """The 30-orphan spelling must not be a way round the check."""
        with pytest.raises(logic.NotAuthorized):
            _as(programs.program_admin[u'name'], u'organization_create',
                name=u'empty-owner-group', owner_group=u'')

    def test_program_admin_cannot_use_an_unknown_program(self, programs):
        with pytest.raises(logic.NotAuthorized):
            _as(programs.program_admin[u'name'], u'organization_create',
                name=u'bogus-program', owner_group=u'no-such-program')

    def test_a_grant_id_is_not_a_program(self, programs):
        """owner_group must name a program, not another grant."""
        grant = factories.Organization()

        with pytest.raises(logic.NotAuthorized):
            _as(programs.program_admin[u'name'], u'organization_create',
                name=u'grant-under-a-grant', owner_group=grant[u'id'])

    # -- Platform Administrators are exempt ----------------------------------

    def test_platform_admin_creates_a_grant_under_any_program(self, programs):
        result = _as(programs.platform_admin[u'name'], u'organization_create',
                     name=u'sysadmin-grant',
                     owner_group=programs.program_theirs[u'id'])

        assert result[u'name'] == u'sysadmin-grant'

    def test_platform_admin_may_create_a_grant_with_no_program(self, programs):
        """Otherwise the 30 legitimately orphaned grants could not exist."""
        result = _as(programs.platform_admin[u'name'], u'organization_create',
                     name=u'sysadmin-orphan-grant')

        assert result[u'name'] == u'sysadmin-orphan-grant'

    # -- Updating ------------------------------------------------------------

    def test_program_admin_may_edit_a_grant_in_their_program(self, programs):
        grant = _as(programs.program_admin[u'name'], u'organization_create',
                    name=u'editable-grant',
                    owner_group=programs.program_mine[u'id'])

        result = _as(programs.program_admin[u'name'], u'organization_update',
                     id=grant[u'id'], name=grant[u'name'],
                     title=u'A new title',
                     owner_group=programs.program_mine[u'id'])

        assert result[u'title'] == u'A new title'

    def test_program_admin_cannot_move_a_grant_to_another_program(self, programs):
        """The hole that makes enforcing this on create alone cosmetic."""
        grant = _as(programs.program_admin[u'name'], u'organization_create',
                    name=u'movable-grant',
                    owner_group=programs.program_mine[u'id'])

        with pytest.raises(logic.NotAuthorized):
            _as(programs.program_admin[u'name'], u'organization_update',
                id=grant[u'id'], name=grant[u'name'],
                owner_group=programs.program_theirs[u'id'])

    def test_program_admin_cannot_orphan_a_grant(self, programs):
        """Clearing owner_group would put it beyond their own reach."""
        grant = _as(programs.program_admin[u'name'], u'organization_create',
                    name=u'orphanable-grant',
                    owner_group=programs.program_mine[u'id'])

        with pytest.raises(logic.NotAuthorized):
            _as(programs.program_admin[u'name'], u'organization_update',
                id=grant[u'id'], name=grant[u'name'])

    def test_patch_is_covered_too(self, programs):
        """organization_patch merges and then calls organization_update."""
        grant = _as(programs.program_admin[u'name'], u'organization_create',
                    name=u'patchable-grant',
                    owner_group=programs.program_mine[u'id'])

        with pytest.raises(logic.NotAuthorized):
            _as(programs.program_admin[u'name'], u'organization_patch',
                id=grant[u'id'], owner_group=programs.program_theirs[u'id'])

    # -- ignore_auth ---------------------------------------------------------

    def test_ignore_auth_bypasses_the_check(self, programs):
        """Internal callers -- factories, the migration, CLI -- must still work.

        Mirrors ``authz.is_authorized``, which returns success immediately on
        ``ignore_auth``. Every other test in this repo that builds an
        organization depends on this holding.

        The user is a Program Administrator of a *different* program, so the
        check would refuse them outright -- ``ignore_auth`` is the only reason
        this succeeds. A real user is still required because CKAN's own
        ``_group_or_org_create`` asserts on one when it adds the creator as
        admin, regardless of authorization.
        """
        result = helpers.call_action(
            u'organization_create',
            context={u'user': programs.program_admin[u'name'],
                     u'ignore_auth': True},
            name=u'internally-created',
            owner_group=programs.program_theirs[u'id'])

        assert result[u'name'] == u'internally-created'
