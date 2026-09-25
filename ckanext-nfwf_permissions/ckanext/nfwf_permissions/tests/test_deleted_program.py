# encoding: utf-8
"""What happens to a grant when its program is deleted.

``_program_id_for_grant_id`` used to read the ``owner_group`` extra without
checking the group it names, so a deleted program went on being reported as a
grant's program. Three things then disagreed about the same grant:

* the auth layer treated it as administered by nobody, because
  ``programs_for_user`` filters to active groups;
* ``labels`` went on stamping ``program-<dead id>`` and ``in-any-program`` on
  its private datasets, so every *other* program's administrator kept read
  access at the moment the program's own readers lost it;
* ``migration.orphan_grants`` could not see it, because it tests
  ``program_id_for_grant(...) is None`` and a dead id is not ``None`` -- so the
  one report built to surface unreachable grants reported none.

The join added to that query makes all three agree.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model

from ckanext.nfwf_permissions import migration, roles
from ckanext.nfwf_permissions.labels import (
    IN_ANY_PROGRAM, NfwfPermissionLabels, program_label)


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


class World(object):
    def __init__(self):
        self.sysadmin = factories.Sysadmin()
        self.program = factories.Group()
        self.live_program = factories.Group()

        self.grant = factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': self.program[u'id']}])
        self.live_grant = factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA,
             u'value': self.live_program[u'id']}])

        self.dataset = factories.Dataset(
            owner_org=self.grant[u'id'], private=True)

        self.reader = factories.User()
        _assign(self.program[u'id'], self.reader[u'name'],
                roles.CAPACITY_MEMBER)

    def delete_the_program(self):
        helpers.call_action(u'group_delete',
                            context={u'user': self.sysadmin[u'name']},
                            id=self.program[u'id'])
        roles.clear_cache()


@pytest.fixture
def world(clean_db):
    return World()


@pytest.mark.usefixtures(u'with_plugins')
class TestDeletedProgram(object):

    def test_the_grant_no_longer_claims_a_program(self, world):
        assert roles.program_id_for_grant(world.grant[u'id'])
        world.delete_the_program()
        assert roles.program_id_for_grant(world.grant[u'id']) is None

    def test_the_orphan_report_can_see_it(self, world):
        """The report exists for exactly this state; it used to miss it."""
        world.delete_the_program()

        orphans = [g[u'group_name'] for g in migration.orphan_grants()]

        assert world.grant[u'name'] in orphans

    def test_its_private_datasets_stop_carrying_program_labels(self, world):
        """Otherwise other programs' administrators keep reading them."""
        world.delete_the_program()
        pkg = model.Package.get(world.dataset[u'id'])

        labels = NfwfPermissionLabels().get_dataset_labels(pkg)

        assert program_label(world.program[u'id']) not in labels
        assert IN_ANY_PROGRAM not in labels

    def test_nobody_administers_it_any_more(self, world):
        world.delete_the_program()

        assert roles.is_program_admin_for_grant(
            world.reader[u'name'], world.grant[u'id']) is False

    def test_a_live_program_is_untouched(self, world):
        """The fix must not turn working grants into orphans."""
        world.delete_the_program()

        assert roles.program_id_for_grant(
            world.live_grant[u'id']) == world.live_program[u'id']
        assert world.live_grant[u'name'] not in [
            g[u'group_name'] for g in migration.orphan_grants()]

    def test_an_owner_group_naming_a_grant_is_not_a_program(self, world):
        """The join filters on is_organization too, so this resolves to None.

        Written straight to the model rather than through
        `organization_create`, because `_assert_owner_group_names_a_program`
        now refuses this value at write time -- for `ignore_auth` callers too,
        since integrity is not authorization. The read path still has to hold:
        it is what protects rows that predate that guard, and anything written
        by direct SQL. Both halves are now tested, one per layer.
        """
        confused = factories.Organization()
        model.Session.add(model.GroupExtra(
            group_id=confused[u'id'], key=roles.OWNER_GROUP_EXTRA,
            value=world.grant[u'id'], state=u'active'))
        model.Session.commit()
        roles.clear_cache()

        assert roles.program_id_for_grant(confused[u'id']) is None
