# encoding: utf-8
"""The Grant Editor picker's data source.

US 0126 slide 5 asks for grants "by program", ten at a time behind a scroll
bar. ``nfwf_role_options`` deliberately returns no grants, on the grounds that
roughly 570 of them "is not a checkbox list" -- an objection the slide answers
directly. This is the endpoint that was missing.

The split under test: the backend pages, the frontend groups. Every record
carries ``program_id`` and the modal already has the program list, so grouping
needs no help. Paging does, because the sizes are lopsided -- one program holds
487 of 571 grants against 41 and 12 -- so a flat page can straddle two programs
and the screen cannot tell a finished group from a truncated one.
"""
import pytest

import ckan.tests.factories as factories
import ckan.tests.helpers as helpers
from ckan import model
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import accounts, roles


def _grant(program_id=None, title=None):
    extras = [{u'key': roles.OWNER_GROUP_EXTRA, u'value': program_id or u''}]
    return factories.Organization(extras=extras, title=title)


class World(object):
    def __init__(self):
        self.sysadmin = factories.Sysadmin()
        self.program_a = factories.Group(title=u'Program A')
        self.program_b = factories.Group(title=u'Program B')
        self.a1 = _grant(self.program_a[u'id'], u'Alpha Grant')
        self.a2 = _grant(self.program_a[u'id'], u'Beta Grant')
        self.b1 = _grant(self.program_b[u'id'], u'Gamma Grant')
        self.orphan = _grant(None, u'Unattached Grant')
        self.padmin = factories.User()
        helpers.call_action(u'group_member_create', id=self.program_a[u'id'],
                            username=self.padmin[u'name'], role=u'admin')
        roles.clear_cache()


@pytest.fixture
def world(clean_db):
    return World()


def _as(user, **kw):
    return helpers.call_action(
        u'nfwf_grant_list',
        context={u'user': user, u'ignore_auth': False}, **kw)


@pytest.mark.usefixtures(u'with_plugins')
class TestWhoSeesWhat(object):

    def test_a_platform_administrator_sees_a_programs_grants(self, world):
        result = _as(world.sysadmin[u'name'], program_id=world.program_a[u'id'])

        assert {g[u'title'] for g in result[u'results']} == {
            u'Alpha Grant', u'Beta Grant'}

    def test_a_program_administrator_sees_only_their_own(self, world):
        mine = _as(world.padmin[u'name'], program_id=world.program_a[u'id'])
        theirs = _as(world.padmin[u'name'], program_id=world.program_b[u'id'])

        assert mine[u'count'] == 2
        assert theirs[u'count'] == 0, (
            u'a Program Administrator must not enumerate another program')

    def test_unassigned_is_empty_for_a_program_administrator(self, world):
        """Not a limitation -- the reason the screen omits that group.

        A grant under no program is administered by nobody, so
        ``_callers_scope`` excludes it. The frontend has to read an absent
        group as correct rather than as a failed load.
        """
        assert _as(world.padmin[u'name'], unassigned=True)[u'count'] == 0

    def test_unassigned_reaches_a_platform_administrator(self, world):
        result = _as(world.sysadmin[u'name'], unassigned=True)

        assert world.orphan[u'id'] in {g[u'id'] for g in result[u'results']}

    def test_an_ordinary_user_is_refused(self, world):
        with pytest.raises(toolkit.NotAuthorized):
            _as(factories.User()[u'name'])


@pytest.mark.usefixtures(u'with_plugins')
class TestTheShapeAndThePaging(object):

    def test_every_record_carries_its_program(self, world):
        """What the frontend groups on."""
        result = _as(world.sysadmin[u'name'], program_id=world.program_a[u'id'])

        assert all(g[u'program_id'] == world.program_a[u'id']
                   for g in result[u'results'])
        assert all({u'id', u'name', u'title', u'program_id'} == set(g)
                   for g in result[u'results'])

    def test_count_is_the_total_not_the_page(self, world):
        """Otherwise the screen cannot tell a finished group from a page."""
        result = _as(world.sysadmin[u'name'],
                     program_id=world.program_a[u'id'], limit=1)

        assert result[u'count'] == 2
        assert len(result[u'results']) == 1

    def test_pages_do_not_overlap(self, world):
        first = _as(world.sysadmin[u'name'],
                    program_id=world.program_a[u'id'], limit=1, offset=0)
        second = _as(world.sysadmin[u'name'],
                     program_id=world.program_a[u'id'], limit=1, offset=1)

        assert not ({g[u'id'] for g in first[u'results']} &
                    {g[u'id'] for g in second[u'results']})

    def test_search_matches_title(self, world):
        result = _as(world.sysadmin[u'name'], q=u'alpha')

        assert {g[u'title'] for g in result[u'results']} == {u'Alpha Grant'}

    def test_a_zero_limit_is_refused(self, world):
        """Same reason as ``nfwf_user_list``: an empty page beside a non-zero
        count reads as no results while the count says otherwise."""
        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'], limit=0)

    def test_one_program_or_the_unassigned_but_not_both(self, world):
        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'],
                program_id=world.program_a[u'id'], unassigned=True)

    def test_an_unknown_program_is_refused(self, world):
        """Rather than silently returning nothing, which reads as an empty
        program."""
        with pytest.raises(toolkit.ValidationError):
            _as(world.sysadmin[u'name'], program_id=u'no-such-program')


@pytest.mark.usefixtures(u'with_plugins')
class TestUnassignedAgreesWithTheRestOfTheModel(object):
    """``accounts.unassigned_grant_ids`` is a second implementation of the
    question ``roles.program_id_for_grant`` answers, written in SQL because
    this one serves a screen rather than a report. Nothing structural keeps
    them aligned, so this pins them -- the same arrangement, and the same
    reason, as ``dual_scope`` and the migration.
    """

    def test_the_two_agree_on_every_grant(self, world):
        by_sql = accounts.unassigned_grant_ids()
        every = model.Session.query(model.Group.id).filter(
            model.Group.is_organization.is_(True),
            model.Group.state == u'active').all()

        compared = 0
        for (grant_id,) in every:
            compared += 1
            roles.clear_cache()
            assert (roles.program_id_for_grant(grant_id) is None) == (
                grant_id in by_sql), grant_id

        assert compared, u'no grants to compare'

    def test_a_deleted_program_makes_its_grants_unassigned(self, world):
        """The state filter, which the join carries and a naive query would
        miss -- the defect behind ``test_deleted_program.py``."""
        helpers.call_action(u'group_delete',
                            context={u'user': world.sysadmin[u'name']},
                            id=world.program_a[u'id'])
        roles.clear_cache()

        assert world.a1[u'id'] in accounts.unassigned_grant_ids()
