# encoding: utf-8
"""Unit tests for the /user administration helpers.

These cover the parts that are this extension's own work: mapping the filter
checkboxes onto the action's ``statuses`` parameter, shaping a
``nfwf_user_list`` row for the template, and formatting.  The data itself comes
from ckanext-nfwf_permissions, which tests its own contract; the query and
pagination paths need a request context and are exercised against the running
site instead.

The vocabulary tests exist to catch a regression rather than to restate the
contract: this module used to keep its own copy of the role and status names,
keyed by display label, which is what let the UI and the API drift apart.
"""
import pytest

from ckanext.nfwf_fields import user_admin
from ckanext.nfwf_permissions import roles


@pytest.fixture
def no_url_for(monkeypatch):
    """Stub url_for so row shaping can be tested without a request context."""
    monkeypatch.setattr(
        user_admin, u'url_for',
        lambda route, id=None, **kwargs: u'/{0}/{1}'.format(
            route.split(u'.')[0], id))


def _record(**overrides):
    """A ``nfwf_user_list`` result row, in the contract's shape."""
    record = {
        u'id': u'user-1',
        u'name': u'dyork',
        u'display_name': u'Dawn York',
        u'email': u'dyork@example.org',
        u'status': roles.STATUS_ACTIVE,
        u'status_label': roles.STATUS_LABELS[roles.STATUS_ACTIVE],
        u'last_login': u'2025-05-21T11:00:00',
        u'role': roles.GRANT_EDITOR,
        u'role_label': roles.ROLE_LABELS[roles.GRANT_EDITOR],
        u'dual_scope': False,
        u'programs': [],
        u'grants': [
            {u'id': u'grant-1', u'name': u'cape-fear', u'title': u'Cape Fear'},
        ],
    }
    record.update(overrides)
    return record


# -- vocabulary --------------------------------------------------------------

def test_module_declares_no_role_vocabulary_of_its_own():
    """Roles must come from the contract, not from a local copy."""
    for leaked in (u'MANAGEABLE_ROLES', u'ROLE_SYSADMIN', u'ROLE_GRANT_EDITOR',
                   u'STATUS_ACTIVE', u'STATE_TO_STATUS'):
        assert not hasattr(user_admin, leaked), (
            u'%s is back; the role vocabulary belongs to nfwf_permissions.roles'
            % leaked)


def test_red_statuses_are_everything_but_active():
    assert user_admin.RED_STATUSES == frozenset(
        set(roles.STATUSES) - {roles.STATUS_ACTIVE})


# -- status colouring --------------------------------------------------------

@pytest.mark.parametrize(u'status', [
    roles.STATUS_NEEDS_REVIEW,
    roles.STATUS_DEACTIVATED,
    roles.STATUS_REJECTED,
])
def test_red_statuses_get_the_red_class(status):
    assert user_admin.user_status_class(status) == u'nfwf-user-status-red'


def test_active_gets_the_blue_class():
    assert user_admin.user_status_class(
        roles.STATUS_ACTIVE) == u'nfwf-user-status-blue'


@pytest.mark.parametrize(u'status', [None, u'', u'Active', u'unknown'])
def test_unknown_status_gets_no_class(status):
    """Including the old display-label form, which must no longer match."""
    assert user_admin.user_status_class(status) == u''


# -- last login --------------------------------------------------------------

@pytest.mark.parametrize(u'stamp,expected', [
    (u'2025-05-21T11:00:00', u'5/21/2025 11:00 am'),
    (u'2025-12-03T00:05:00', u'12/3/2025 12:05 am'),
    (u'2025-10-30T23:59:00', u'10/30/2025 11:59 pm'),
    (u'2025-10-30T12:00:00', u'10/30/2025 12:00 pm'),
    # The real action may render UTC with a Z; fromisoformat rejects it
    # before Python 3.11, so it is normalised first.
    (u'2025-05-21T11:00:00Z', u'5/21/2025 11:00 am'),
])
def test_last_login_formatting(stamp, expected):
    assert user_admin.user_last_login(stamp) == expected


@pytest.mark.parametrize(u'stamp', [None, u'', u'not a date', 12345])
def test_unusable_last_login_renders_empty(stamp):
    assert user_admin.user_last_login(stamp) == u''


# -- status filter -----------------------------------------------------------

def test_statuses_default_to_the_contracts_visible_set():
    assert user_admin._statuses(False, False) == list(
        roles.DEFAULT_VISIBLE_STATUSES)


def test_include_deactivated_widens_the_filter():
    assert user_admin._statuses(True, False) == list(
        roles.DEFAULT_VISIBLE_STATUSES) + [roles.STATUS_DEACTIVATED]


def test_include_rejected_widens_the_filter():
    assert user_admin._statuses(False, True) == list(
        roles.DEFAULT_VISIBLE_STATUSES) + [roles.STATUS_REJECTED]


def test_both_checkboxes_ask_for_every_status():
    assert sorted(user_admin._statuses(True, True)) == sorted(roles.STATUSES)


# -- row shaping -------------------------------------------------------------

def test_row_carries_the_label_not_the_slug(no_url_for):
    row = user_admin._row(_record())
    assert row[u'role'] == roles.GRANT_EDITOR
    assert row[u'role_label'] == u'Grant Editor'
    assert row[u'status_label'] == u'Active'
    assert row[u'status_class'] == u'nfwf-user-status-blue'


def test_row_adds_the_links_the_action_does_not_return(no_url_for):
    row = user_admin._row(_record())
    assert row[u'url'] == u'/user/dyork'
    assert row[u'grants'][0][u'url'] == u'/organization/cape-fear'


def test_row_selection_uses_ids_not_names(no_url_for):
    row = user_admin._row(_record())
    assert row[u'role_selection'] == {
        u'role': roles.GRANT_EDITOR,
        u'program_ids': [],
        u'grant_ids': [u'grant-1'],
        # The grant picker searches rather than lists, so it needs the titles
        # of what is already assigned.
        u'grants': [{u'id': u'grant-1', u'title': u'Cape Fear'}],
        u'dual_scope': False,
    }


def test_platform_admin_assignments_are_not_in_effect(no_url_for):
    """Retained on the record, superseded by the sysadmin flag."""
    row = user_admin._row(_record(role=roles.PLATFORM_ADMIN))
    assert row[u'assignments_in_effect'] is False


def test_scoped_role_assignments_are_in_effect(no_url_for):
    row = user_admin._row(_record())
    assert row[u'assignments_in_effect'] is True


def test_row_survives_a_user_with_no_role_or_assignments(no_url_for):
    row = user_admin._row(_record(
        role=None, role_label=None, last_login=None, grants=[], programs=[]))
    assert row[u'role'] == u''
    assert row[u'role_label'] == u''
    assert row[u'last_login'] == u''
    assert row[u'grants'] == []
    # No role means nothing supersedes anything.
    assert row[u'assignments_in_effect'] is True


def test_row_falls_back_to_the_name_when_a_grant_has_no_title(no_url_for):
    row = user_admin._row(_record(grants=[
        {u'id': u'grant-2', u'name': u'no-title', u'title': None},
    ]))
    assert row[u'grants'][0][u'title'] == u'no-title'


# -- dual scope --------------------------------------------------------------

def test_dual_scope_reaches_the_table(no_url_for):
    row = user_admin._row(_record(dual_scope=True))
    assert row[u'dual_scope'] is True


def test_dual_scope_is_suppressed_for_a_platform_admin(no_url_for):
    """Their assignments are retained but inert, so "holds both" says nothing.

    The contract leaves the flag raw and tells the UI to pair it with the role.
    """
    row = user_admin._row(_record(role=roles.PLATFORM_ADMIN, dual_scope=True))
    assert row[u'dual_scope'] is False


def test_the_modal_sees_dual_scope_even_for_a_platform_admin(no_url_for):
    """Demoting one makes those retained assignments live again, and saving
    replaces every one of them -- so the modal must still be able to warn."""
    row = user_admin._row(_record(role=roles.PLATFORM_ADMIN, dual_scope=True))
    assert row[u'role_selection'][u'dual_scope'] is True


def test_a_row_without_the_flag_is_not_dual_scope(no_url_for):
    """``dual_scope`` is absent from the stub contract and from older rows."""
    record = _record()
    del record[u'dual_scope']
    assert user_admin._row(record)[u'dual_scope'] is False


# -- status actions ----------------------------------------------------------

def test_every_status_offers_at_least_one_action():
    """A status with no actions would render an empty kebab menu."""
    for status in roles.STATUSES:
        assert user_admin.STATUS_ACTIONS.get(status), (
            u'%s offers no account actions' % status)


def test_status_actions_name_only_contract_actions():
    allowed = {u'nfwf_user_approve', u'nfwf_user_reject',
               u'nfwf_user_deactivate'}
    for actions in user_admin.STATUS_ACTIONS.values():
        for _key, action in actions:
            assert action in allowed


@pytest.mark.parametrize(u'status,expected', [
    (roles.STATUS_NEEDS_REVIEW, [u'nfwf_user_approve', u'nfwf_user_reject']),
    (roles.STATUS_ACTIVE, [u'nfwf_user_deactivate']),
    # There is no nfwf_user_reactivate: approve is the only action that moves an
    # account out of 'deleted' and clears the status marker.
    (roles.STATUS_DEACTIVATED, [u'nfwf_user_approve']),
    (roles.STATUS_REJECTED, [u'nfwf_user_approve']),
])
def test_row_offers_the_actions_its_status_allows(no_url_for, status, expected):
    row = user_admin._row(_record(status=status))
    assert [action[u'action'] for action in row[u'actions']] == expected


def test_an_unknown_status_offers_no_actions(no_url_for):
    """Rather than guessing, which could offer an action that then 409s."""
    assert user_admin._row(_record(status=u'unknown'))[u'actions'] == []


def test_table_meta_covers_every_status():
    meta = user_admin._table_meta()
    assert sorted(meta[u'status_actions']) == sorted(roles.STATUSES)
    assert sorted(meta[u'status_classes']) == sorted(roles.STATUSES)


# -- query string ------------------------------------------------------------

@pytest.mark.parametrize(u'value', [u'1', u'on', u'true', u'yes', u'TRUE'])
def test_checkbox_truthy_values(value):
    assert user_admin._checkbox({u'include_rejected': value},
                                u'include_rejected') is True


@pytest.mark.parametrize(u'value', [u'', u'0', u'false', u'off', u'no'])
def test_checkbox_falsy_values(value):
    assert user_admin._checkbox({u'include_rejected': value},
                                u'include_rejected') is False


def test_absent_checkbox_is_false():
    """Browsers omit unticked boxes from the query string entirely."""
    assert user_admin._checkbox({}, u'include_rejected') is False


def test_pager_params_carry_the_active_filters():
    assert user_admin._pager_params(u'dawn', True, False, 20, 20) == {
        u'q': u'dawn',
        u'include_deactivated': u'1',
    }


def test_pager_params_omit_inactive_filters():
    assert user_admin._pager_params(u'', False, False, 20, 20) == {}


def test_pager_params_carry_a_chosen_page_size():
    assert user_admin._pager_params(u'', False, False, 50, 20) == {
        u'limit': u'50',
    }


# -- page size ---------------------------------------------------------------

@pytest.mark.parametrize(u'size', user_admin.PAGE_SIZES)
def test_every_offered_page_size_is_honored(size):
    assert user_admin._page_size({u'limit': str(size)}, 20) == size


@pytest.mark.parametrize(u'value', [u'', u'7', u'100', u'1000', u'-5',
                                    u'abc', u'20.5'])
def test_an_unoffered_page_size_gets_the_default(value):
    """Including 100, which the action would accept but the dropdown never
    offers -- the table pages only at the sizes it shows."""
    assert user_admin._page_size({u'limit': value}, 20) == 20


def test_absent_page_size_gets_the_default():
    assert user_admin._page_size({}, 20) == 20


def test_page_sizes_are_what_the_product_owner_asked_for():
    assert list(user_admin.PAGE_SIZES) == [5, 10, 20, 50]


def test_a_configured_default_joins_the_choices():
    """Otherwise a site set to 25 would open on a size it cannot show."""
    assert user_admin._page_sizes(25) == [5, 10, 20, 25, 50]
    assert user_admin._page_size({u'limit': u'25'}, 25) == 25


def test_the_default_is_not_added_twice():
    assert user_admin._page_sizes(20) == [5, 10, 20, 50]


# -- empty table -------------------------------------------------------------

def test_empty_table_has_every_key_the_template_reads():
    table = user_admin._empty_table()
    for key in (u'rows', u'assignments', u'page', u'q', u'include_deactivated',
                u'include_rejected', u'limit', u'page_sizes', u'pager_params',
                u'authorized', u'meta'):
        assert key in table
