# encoding: utf-8
"""Tests for the grant-administrator required-field rule.

Task 125 let Program Administrators edit grants, so the fields that were
Platform-Administrator-only belong to them now too. Two things have to agree on
*who* that is: this validator, and the template gate that decides whether the
field is rendered at all. If they disagree in the direction of
required-but-hidden, the grant form becomes unsavable with an error about a
field the user was never shown -- so the shared answer comes from
``roles.administers_grants``.

The consuming half lives in ``ckanext-nfwf_fields`` (its ``can_admin_grant``
helper and ``grant_admin_not_empty``), which is a separate extension and not
loaded by this suite. What is tested here is the rule; that the other extension
resolves it is verified against the running site instead.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles
from ckanext.nfwf_permissions.logic import validators


def _assign(group_id, user_name, capacity):
    helpers.call_action(
        u'member_create', id=group_id, object=user_name,
        object_type=u'user', capacity=capacity)


class World(object):
    def __init__(self):
        self.program = factories.Group()
        self.grant = factories.Organization(extras=[
            {u'key': roles.OWNER_GROUP_EXTRA, u'value': u''}])

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


@pytest.fixture
def world(clean_db):
    return World()


@pytest.mark.usefixtures(u'with_plugins')
class TestAdministersGrants(object):

    def test_platform_and_program_admins_do(self, world):
        assert roles.administers_grants(world.platform_admin[u'name']) is True
        assert roles.administers_grants(world.program_admin[u'name']) is True

    def test_nobody_else_does(self, world):
        for user in (world.program_reader, world.grant_editor, world.nobody):
            assert roles.administers_grants(user[u'name']) is False, \
                user[u'name']

    def test_a_program_reader_is_not_a_grant_administrator(self, world):
        """The distinction the whole role model rests on: read, not administer."""
        assert roles.administers_grants(world.program_reader[u'name']) is False

    def test_unknown_and_anonymous_do_not(self, world):
        assert roles.administers_grants(None) is False
        assert roles.administers_grants(u'') is False
        assert roles.administers_grants(u'no-such-user') is False

    def test_it_agrees_with_user_role(self, world):
        """Expressed in terms of user_role so the two cannot disagree."""
        for user in (world.platform_admin, world.program_admin,
                     world.program_reader, world.grant_editor, world.nobody):
            expected = roles.user_role(user[u'name']) in (
                roles.PLATFORM_ADMIN, roles.PROGRAM_ADMIN)
            assert roles.administers_grants(user[u'name']) is expected


@pytest.mark.usefixtures(u'with_plugins')
class TestRequiredFieldValidator(object):

    SCHEMA = {
        u'funding_source': [
            validators.platform_or_program_admin_not_empty],
    }

    def _validate(self, user_name, value=None):
        data = {} if value is None else {u'funding_source': value}
        return toolkit.navl_validate(data, self.SCHEMA, {u'user': user_name})

    def test_required_for_a_platform_administrator(self, world):
        _data, errors = self._validate(world.platform_admin[u'name'])
        assert u'funding_source' in errors

    def test_required_for_a_program_administrator(self, world):
        """The point of item 5: same required fields as a Platform Admin."""
        _data, errors = self._validate(world.program_admin[u'name'])
        assert u'funding_source' in errors

    def test_satisfied_when_the_administrator_provides_it(self, world):
        for user in (world.platform_admin, world.program_admin):
            _data, errors = self._validate(user[u'name'], u'NFWF-12345')
            assert errors == {}, user[u'name']

    def test_ignored_for_everyone_else(self, world):
        """They are never shown the field, so requiring it would trap them.

        A Grant Editor can legitimately edit a grant's other fields; if this
        validator asked them for a value the form never rendered, they could
        not save at all.
        """
        for user in (world.program_reader, world.grant_editor, world.nobody):
            _data, errors = self._validate(user[u'name'])
            assert errors == {}, user[u'name']

    def test_ignored_for_anonymous(self, world):
        _data, errors = self._validate(None)
        assert errors == {}

    def test_the_validator_is_registered_by_name(self, world):
        """nfwf_fields resolves it by name, so the registration has to exist."""
        assert toolkit.get_validator(
            u'platform_or_program_admin_not_empty') is not None
