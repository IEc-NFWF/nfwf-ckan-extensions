# encoding: utf-8
"""Can a Program Administrator actually create a dataset, end to end?

Three separate layers have to agree before the role's headline capability
works, and for a while only the first of them did:

1. ``package_create``'s auth override says yes -- covered in ``test_auth.py``.
2. ``owner_org_validator`` has to accept the grant. Core's requires a
   membership row on it conferring ``create_dataset``, which a Program
   Administrator does not have by design, so the action passed authorization
   and then died in *validation* with "You cannot add a dataset to this
   organization".
3. ``organization_list_for_user`` has to return the grant, because that is
   what both dataset-form templates gate their Grant selector on. Stock builds
   it from the subject's own membership rows, so it came back empty and the
   form offered nothing to pick.

These cover 2 and 3. The schema wiring that puts the validator on the dataset
form lives in ``ckanext-nfwf_fields``, which this suite does not load, so that
last hop is verified against the running site -- the same arrangement as
``test_grant_admin_fields.py``.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles
from ckanext.nfwf_permissions.logic import validators

OWNER_ORG = (u'owner_org',)


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


class World(object):
    """One program with two grants, a foreign grant, and an orphan."""

    def __init__(self):
        self.program = factories.Group()
        self.other_program = factories.Group()

        self.grant = self._grant(self.program[u'id'])
        self.grant_two = self._grant(self.program[u'id'])
        self.foreign_grant = self._grant(self.other_program[u'id'])
        self.orphan_grant = self._grant(u'')

        self.platform_admin = factories.Sysadmin()
        self.program_admin = factories.User()
        self.program_reader = factories.User()
        self.grant_editor = factories.User()
        self.nobody = factories.User()

        _assign(self.program[u'id'], self.program_admin[u'name'],
                roles.CAPACITY_ADMIN)
        _assign(self.program[u'id'], self.program_reader[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(self.grant[u'id'], self.grant_editor[u'name'],
                roles.CAPACITY_EDITOR)

    @staticmethod
    def _grant(program_id):
        return factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': program_id}])


@pytest.fixture
def world(clean_db):
    return World()


def _validate(user_name, owner_org, **context_extras):
    """Run the validator the way the schema would, returning or raising."""
    context = {u'model': model, u'session': model.Session, u'user': user_name}
    context.update(context_extras)
    return validators.nfwf_owner_org_validator(
        OWNER_ORG, {OWNER_ORG: owner_org}, {OWNER_ORG: []}, context)


@pytest.mark.usefixtures(u'with_plugins')
class TestOwnerOrgValidator(object):

    def test_program_admin_may_file_into_their_own_programs_grants(self, world):
        """The case that was broken: auth allowed it, validation refused it."""
        for grant in (world.grant, world.grant_two):
            _validate(world.program_admin[u'name'], grant[u'id'])

    def test_program_admin_may_not_file_into_another_program(self, world):
        with pytest.raises(toolkit.Invalid):
            _validate(world.program_admin[u'name'],
                      world.foreign_grant[u'id'])

    def test_program_admin_may_not_file_into_a_grant_with_no_program(
            self, world):
        """An orphan grant is Platform-Administrator-only territory."""
        with pytest.raises(toolkit.Invalid):
            _validate(world.program_admin[u'name'], world.orphan_grant[u'id'])

    def test_everyone_else_is_refused_exactly_as_before(self, world):
        """The widening must not leak to roles core already refused."""
        for user in (world.program_reader, world.nobody):
            with pytest.raises(toolkit.Invalid):
                _validate(user[u'name'], world.grant[u'id'])

    def test_a_grant_editor_still_passes_on_their_own_grant(self, world):
        """Stock already allowed this; the override must not disturb it."""
        _validate(world.grant_editor[u'name'], world.grant[u'id'])

    def test_a_nonexistent_grant_is_still_rejected(self, world):
        with pytest.raises(toolkit.Invalid):
            _validate(world.program_admin[u'name'], u'no-such-grant')

    def test_ignore_auth_is_passed_straight_through(self, world):
        """Internal callers keep core's own bypass, unchanged."""
        _validate(world.nobody[u'name'], world.grant[u'id'], ignore_auth=True)


@pytest.mark.usefixtures(u'with_plugins')
class TestOrganizationListForUser(object):

    def _orgs(self, user_name, **kwargs):
        return helpers.call_action(
            u'organization_list_for_user',
            context={u'user': user_name, u'ignore_auth': False}, **kwargs)

    def test_program_admin_sees_every_grant_in_their_program(self, world):
        names = {o[u'name'] for o in
                 self._orgs(world.program_admin[u'name'],
                            permission=u'create_dataset')}

        assert world.grant[u'name'] in names
        assert world.grant_two[u'name'] in names

    def test_and_nothing_outside_it(self, world):
        names = {o[u'name'] for o in
                 self._orgs(world.program_admin[u'name'],
                            permission=u'create_dataset')}

        assert world.foreign_grant[u'name'] not in names
        assert world.orphan_grant[u'name'] not in names

    def test_the_added_grants_carry_a_capacity(self, world):
        """The templates read it, so an entry without one renders wrong."""
        added = [o for o in self._orgs(world.program_admin[u'name'],
                                       permission=u'create_dataset')
                 if o[u'name'] == world.grant[u'name']]

        assert added and added[0][u'capacity'] == roles.CAPACITY_ADMIN

    def test_roles_that_hold_nothing_still_get_nothing(self, world):
        for user in (world.program_reader, world.nobody):
            assert self._orgs(user[u'name'],
                              permission=u'create_dataset') == [], user[u'name']

    def test_a_grant_editor_still_sees_their_own_grant(self, world):
        """Stock's own path, which this must not have disturbed."""
        names = {o[u'name'] for o in
                 self._orgs(world.grant_editor[u'name'],
                            permission=u'create_dataset')}

        assert names == {world.grant[u'name']}

    def test_a_grant_is_not_listed_twice(self, world):
        """Holding a row on a grant *and* administering its program."""
        _assign(world.grant[u'id'], world.program_admin[u'name'],
                roles.CAPACITY_EDITOR)

        names = [o[u'name'] for o in
                 self._orgs(world.program_admin[u'name'],
                            permission=u'create_dataset')]

        assert names.count(world.grant[u'name']) == 1

    def test_a_platform_administrator_is_unaffected(self, world):
        """Stock already returns everything for them; adding must be a no-op."""
        names = [o[u'name'] for o in
                 self._orgs(world.platform_admin[u'name'],
                            permission=u'create_dataset')]

        assert len(names) == len(set(names))
        assert world.foreign_grant[u'name'] in names
