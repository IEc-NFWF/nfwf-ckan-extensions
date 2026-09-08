# encoding: utf-8
"""Tests for program-wide visibility of private datasets.

Two layers, and both matter.

The label tests check what strings go into the index and onto a user. They are
fast and precise, but a matching pair of labels is only *evidence* of
visibility.

The `TestVisibilityThroughSearch` tests go through `package_search` and
`package_show` for real, with `clean_index`, so they prove the labels actually
intersect the way intended once Solr is involved. Without those, a typo in a
label prefix would pass every test above and still hide every dataset.

`clean_index` matters more here than anywhere else in this suite: the Solr core
is shared with the development database, and permission labels are written at
index time, so a leftover document from another test would answer these
queries.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model

from ckanext.nfwf_permissions import labels, roles


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


class World(object):
    """Two programs, grants in each, one orphan grant, one user per role."""

    def __init__(self):
        self.program_a = factories.Group()
        self.program_b = factories.Group()

        self.grant_a1 = self._grant(self.program_a[u'id'])
        self.grant_a2 = self._grant(self.program_a[u'id'])
        self.grant_b1 = self._grant(self.program_b[u'id'])
        self.grant_orphan = self._grant(u'')

        self.program_admin = factories.User()
        self.program_reader = factories.User()
        self.grant_editor = factories.User()
        self.outsider = factories.User()

        _assign(self.program_a[u'id'], self.program_admin[u'name'],
                roles.CAPACITY_ADMIN)
        _assign(self.program_a[u'id'], self.program_reader[u'name'],
                roles.CAPACITY_MEMBER)
        _assign(self.grant_a1[u'id'], self.grant_editor[u'name'],
                roles.CAPACITY_EDITOR)

        # One private dataset per grant, so every combination is reachable.
        self.private_a1 = self._private(self.grant_a1[u'id'])
        self.private_a2 = self._private(self.grant_a2[u'id'])
        self.private_b1 = self._private(self.grant_b1[u'id'])
        self.private_orphan = self._private(self.grant_orphan[u'id'])
        self.public_a1 = factories.Dataset(
            owner_org=self.grant_a1[u'id'], private=False)

    @staticmethod
    def _grant(program_id):
        return factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': program_id}])

    @staticmethod
    def _private(owner_org):
        return factories.Dataset(owner_org=owner_org, private=True)


@pytest.fixture
def world(clean_db):
    return World()


def _labeller():
    from ckan.lib.plugins import get_permission_labels
    return get_permission_labels()


def _dataset_labels(dataset_dict):
    return _labeller().get_dataset_labels(
        model.Package.get(dataset_dict[u'id']))


def _user_labels(user_dict):
    return _labeller().get_user_dataset_labels(
        model.User.get(user_dict[u'id']))


@pytest.mark.usefixtures(u'with_plugins')
class TestTheExtensionProvidesTheLabels(object):

    def test_get_permission_labels_returns_our_implementation(self):
        """Only the first IPermissionLabels plugin is used, so confirm it's ours."""
        assert isinstance(_labeller(), labels.NfwfPermissionLabels)


@pytest.mark.usefixtures(u'with_plugins')
class TestDatasetLabels(object):

    def test_a_public_dataset_stays_just_public(self, world):
        """Adding program labels here would grant nothing and bloat the index."""
        assert _dataset_labels(world.public_a1) == [labels.PUBLIC]

    def test_a_private_dataset_carries_its_program(self, world):
        got = _dataset_labels(world.private_a1)

        assert labels.program_label(world.program_a[u'id']) in got
        assert labels.IN_ANY_PROGRAM in got
        assert labels.PUBLIC not in got

    def test_ckan_defaults_are_preserved(self, world):
        """The grant's own members must not lose access."""
        assert u'member-%s' % world.grant_a1[u'id'] in _dataset_labels(
            world.private_a1)

    def test_a_private_dataset_in_a_program_less_grant_gets_no_program(
            self, world):
        got = _dataset_labels(world.private_orphan)

        assert labels.IN_ANY_PROGRAM not in got
        assert not [l for l in got if l.startswith(u'program-')]
        assert u'member-%s' % world.grant_orphan[u'id'] in got

    def test_the_two_programs_get_different_labels(self, world):
        assert labels.program_label(world.program_a[u'id']) not in \
            _dataset_labels(world.private_b1)


@pytest.mark.usefixtures(u'with_plugins')
class TestUserLabels(object):

    def test_a_program_reader_carries_their_program(self, world):
        got = _user_labels(world.program_reader)

        assert labels.program_label(world.program_a[u'id']) in got
        assert labels.program_label(world.program_b[u'id']) not in got

    def test_a_program_reader_does_not_carry_the_constant(self, world):
        """That is what keeps them inside their own program."""
        assert labels.IN_ANY_PROGRAM not in _user_labels(world.program_reader)

    def test_a_program_admin_carries_the_constant(self, world):
        """Q4, accepted as designed: read across every program, not just theirs."""
        got = _user_labels(world.program_admin)

        assert labels.IN_ANY_PROGRAM in got
        assert labels.program_label(world.program_a[u'id']) in got

    def test_a_grant_editor_carries_no_program_labels(self, world):
        """CKAN's own member-<org_id> already covers the grants they hold."""
        got = _user_labels(world.grant_editor)

        assert labels.IN_ANY_PROGRAM not in got
        assert not [l for l in got if l.startswith(u'program-')]
        assert u'member-%s' % world.grant_a1[u'id'] in got

    def test_an_outsider_carries_nothing_extra(self, world):
        got = _user_labels(world.outsider)

        assert labels.IN_ANY_PROGRAM not in got
        assert not [l for l in got if l.startswith(u'program-')]

    def test_anonymous_gets_only_public(self):
        assert _labeller().get_user_dataset_labels(None) == [labels.PUBLIC]


@pytest.mark.usefixtures(u'clean_index', u'with_plugins')
class TestVisibilityThroughSearch(object):
    """End to end: labels are only useful if they actually intersect in Solr."""

    def _search(self, user_dict):
        result = helpers.call_action(
            u'package_search', context={
                u'user': user_dict[u'name'],
                u'auth_user_obj': model.User.get(user_dict[u'id']),
                u'ignore_auth': False,
            }, include_private=True, rows=100)
        return {row[u'id'] for row in result[u'results']}

    def test_program_reader_sees_private_data_across_their_program(self, world):
        visible = self._search(world.program_reader)

        assert world.private_a1[u'id'] in visible
        assert world.private_a2[u'id'] in visible, \
            u'a second grant in the same program must be visible too'

    def test_program_reader_cannot_see_another_program(self, world):
        visible = self._search(world.program_reader)

        assert world.private_b1[u'id'] not in visible
        assert world.private_orphan[u'id'] not in visible

    def test_program_admin_sees_every_program(self, world):
        visible = self._search(world.program_admin)

        assert world.private_a1[u'id'] in visible
        assert world.private_b1[u'id'] in visible, \
            u'the in-any-program constant should reach another program'

    def test_program_admin_cannot_see_a_program_less_grant(self, world):
        """The 31 program-less grants stay Platform Administrator territory."""
        assert world.private_orphan[u'id'] not in self._search(
            world.program_admin)

    def test_grant_editor_sees_only_their_own_grant(self, world):
        visible = self._search(world.grant_editor)

        assert world.private_a1[u'id'] in visible
        assert world.private_a2[u'id'] not in visible
        assert world.private_b1[u'id'] not in visible

    def test_an_outsider_sees_no_private_data(self, world):
        visible = self._search(world.outsider)

        for dataset in (world.private_a1, world.private_a2,
                        world.private_b1, world.private_orphan):
            assert dataset[u'id'] not in visible
        assert world.public_a1[u'id'] in visible

    def test_package_show_agrees_with_search(self, world):
        """package_show intersects the same label sets, so it must not differ."""
        def can_show(user_dict, dataset_dict):
            try:
                helpers.call_action(
                    u'package_show', context={
                        u'user': user_dict[u'name'],
                        u'auth_user_obj': model.User.get(user_dict[u'id']),
                        u'ignore_auth': False,
                    }, id=dataset_dict[u'id'])
                return True
            except Exception:
                return False

        assert can_show(world.program_reader, world.private_a2)
        assert not can_show(world.program_reader, world.private_b1)
        assert can_show(world.program_admin, world.private_b1)
        assert not can_show(world.outsider, world.private_a1)


@pytest.mark.usefixtures(u'clean_index', u'with_plugins')
class TestReindexOnProgramChange(object):
    """Labels live in the index, so moving a grant has to reindex its datasets."""

    def test_moving_a_grant_updates_what_its_readers_can_see(self, world):
        sysadmin = factories.Sysadmin()

        def reader_sees(dataset_dict):
            result = helpers.call_action(
                u'package_search', context={
                    u'user': world.program_reader[u'name'],
                    u'auth_user_obj': model.User.get(
                        world.program_reader[u'id']),
                    u'ignore_auth': False,
                }, include_private=True, rows=100)
            return dataset_dict[u'id'] in {r[u'id'] for r in result[u'results']}

        # Starts in program A, which the reader belongs to.
        assert reader_sees(world.private_a2)

        # A Platform Administrator moves that grant to program B.
        helpers.call_action(
            u'organization_update', context={u'user': sysadmin[u'name']},
            id=world.grant_a2[u'id'], name=world.grant_a2[u'name'],
            extras=[{u'key': roles.OWNER_GROUP_EXTRA,
                     u'value': world.program_b[u'id']}])

        # Without the reindex the dataset would still carry program A's label
        # and the reader would still see it.
        assert not reader_sees(world.private_a2)
