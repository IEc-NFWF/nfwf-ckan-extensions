"""Data helpers for the user administration page at /user.

Covers the user table and the Manage Roles modal launched from each row's kebab
menu.  Everything shown here comes from the ``nfwf_user_*`` actions in
ckanext-nfwf_permissions, which own the role and account-status model; this
module only shapes their responses for the template and reads the query string.

The role and status vocabularies come from ``nfwf_permissions.roles`` and are
never re-declared locally -- two parallel copies of the vocabulary, one keyed by
slug and one by display label, is exactly what made the two halves of this
feature diverge.

CKAN core's ``user.index`` view (``ckan/views/user.py``) is left untouched so its
``check_access('user_list')`` call keeps governing who may reach the page.  Only
the template is overridden -- ``templates/user/list.html`` in ckanext-nfwf_theme.
nfwf_permissions overrides that core gate to Platform Administrators alone, so
that is who reaches this screen.  Its role actions would admit a Program
Administrator scoped to their own program; until the page gate is widened to
match, that capability goes unused.  Account status -- approve, reject,
deactivate, reactivate -- is Platform Administrator only either way.

Reading the query string from a helper is the established pattern in this
extension; see ``facet_url_add`` / ``facet_url_remove`` in ``plugin.py``.
"""

from datetime import datetime, timedelta, timezone

import ckan.plugins.toolkit as toolkit
from ckan.common import config, request
from ckan.lib.helpers import Page, get_page_number, pager_url, url_for

from ckanext.nfwf_permissions import roles


#: Statuses rendered red (#FF0000).  ``active`` is rendered blue (#0000FF).
RED_STATUSES = frozenset([
    roles.STATUS_NEEDS_REVIEW,
    roles.STATUS_DEACTIVATED,
    roles.STATUS_REJECTED,
])

#: ``roles.ROLE_SCOPE`` records a site-wide role as ``None``.  manage-roles.js
#: switches on a string, so normalise it here rather than teach the JS about
#: null -- the contract's shape stays untouched, the DOM stays simple.
SCOPE_NONE = 'none'

#: ``nfwf_user_list`` refuses a larger page than this.
MAX_PAGE_SIZE = 100

#: A Last Login older than this is shown in red.
STALE_LOGIN_AGE = timedelta(days=365)

#: The table's rows-per-page dropdown.  The configured default joins them if it is
#: not already one -- see ``_page_sizes``.
PAGE_SIZES = (5, 10, 20, 50)

#: The account-status actions the kebab menu offers, keyed by the status the row
#: is in.  Follows the contract's status machine (see "The account status
#: machine" in the nfwf_permissions README).
#:
#: A rejected account offers Approve, not Reactivate, on purpose:
#: ``nfwf_user_reactivate`` accepts Deactivated only, because letting a rejected
#: *request* in is approving it, and that is the word the audit trail should
#: keep.
#:
#: Only ``reject`` and ``reactivate`` refuse an account in the wrong state (a
#: 409 on ``id``).  ``approve`` and ``deactivate`` accept anything -- approving
#: an already active account succeeds -- so the menu is still what keeps the
#: choices sensible for a row.
STATUS_ACTIONS = {
    roles.STATUS_NEEDS_REVIEW: [
        ('approve', 'nfwf_user_approve'),
        ('reject', 'nfwf_user_reject'),
    ],
    roles.STATUS_ACTIVE: [
        ('deactivate', 'nfwf_user_deactivate'),
    ],
    roles.STATUS_DEACTIVATED: [
        ('reactivate', 'nfwf_user_reactivate'),
    ],
    roles.STATUS_REJECTED: [
        ('approve', 'nfwf_user_approve'),
    ],
}


def user_admin_table():
    """Return everything ``user/list.html`` needs to draw the table.

    Keys: ``rows`` (the current page's row dicts), ``assignments`` (feeding the
    one shared modal), ``page`` (the pager), ``q``, ``include_deactivated``,
    ``include_rejected``, ``limit`` and ``page_sizes`` (the rows-per-page
    dropdown), ``pager_params`` and ``authorized``.
    """
    try:
        args = request.args
    except RuntimeError:
        # No request context (e.g. a helper introspection call).
        return _empty_table()

    q = args.get('q', '').strip()
    include_deactivated = _checkbox(args, 'include_deactivated')
    include_rejected = _checkbox(args, 'include_rejected')

    default_limit = _default_page_size()
    limit = _page_size(args, default_limit)
    page_number = get_page_number(args)

    data_dict = {
        'statuses': _statuses(include_deactivated, include_rejected),
        'limit': limit,
        'offset': (page_number - 1) * limit,
    }
    if q:
        data_dict['q'] = q

    try:
        result = toolkit.get_action('nfwf_user_list')({}, data_dict)
    except toolkit.NotAuthorized:
        # Should not happen while nfwf_permissions gates user_list to Platform
        # Administrators too, but the two checks are independent and could drift
        # apart again.  Let the template say so rather than traceback.
        table = _empty_table()
        table['authorized'] = False
        table['q'] = q
        return table

    rows = [_row(record) for record in result['results']]

    return {
        'rows': rows,
        # user name -> the one role they hold, for the single shared modal.
        'assignments': dict(
            (row['name'], row['role_selection']) for row in rows
        ),
        'page': Page(
            collection=rows,
            page=page_number,
            url=pager_url,
            # ``count`` is the total before paging and ``rows`` is already the
            # requested slice, which is what presliced_list below says.  The
            # action pages in Python, not SQL: role and the deactivated/rejected
            # split are derived rather than stored, so it resolves every match
            # and slices.  Transparent here, but it is why the page size matters.
            item_count=result['count'],
            items_per_page=limit,
            presliced_list=True,
        ),
        'q': q,
        'include_deactivated': include_deactivated,
        'include_rejected': include_rejected,
        'limit': limit,
        'page_sizes': _page_sizes(default_limit),
        'pager_params': _pager_params(
            q, include_deactivated, include_rejected, limit, default_limit),
        'authorized': True,
        'meta': _table_meta(),
    }


def user_status_class(status):
    """Return the CSS class that colours a Status value.

    Takes the status *slug*, not its label, so a wording change to
    ``roles.STATUS_LABELS`` cannot silently drop the colour.
    """
    if status in RED_STATUSES:
        return 'nfwf-user-status-red'
    if status == roles.STATUS_ACTIVE:
        return 'nfwf-user-status-blue'
    return ''


def user_last_login(stamp):
    """Format an ISO 8601 timestamp as ``5/21/2025 11:00 am``, or '' if unset.

    ``nfwf_user_list`` returns the raw ISO string and leaves formatting to the
    UI.  Built from date parts rather than strftime because the unpadded ``%-m``
    style directives are platform specific.  The timestamp is UTC.

    Note this is CKAN's *last activity* column -- core records no last-login
    time -- so it can read slightly later than the user's actual login.
    """
    parsed = _parse_stamp(stamp)
    if parsed is None:
        return ''
    return '{month}/{day}/{year} {hour}:{minute:02d} {meridiem}'.format(
        month=parsed.month,
        day=parsed.day,
        year=parsed.year,
        hour=(parsed.hour % 12) or 12,
        minute=parsed.minute,
        meridiem='am' if parsed.hour < 12 else 'pm',
    )


def user_login_is_stale(stamp, now=None):
    """Was ``stamp`` more than ``STALE_LOGIN_AGE`` ago?

    False when it is unset or unreadable.  Many accounts have no Last Login
    yet, and a blank cell means "not known", not "long ago".  ``now`` is for
    the tests.
    """
    parsed = _parse_stamp(stamp)
    if parsed is None:
        return False
    # Stored naive and in UTC; an explicit offset is normalised to match.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now - parsed > STALE_LOGIN_AGE


def _parse_stamp(stamp):
    """``nfwf_user_list``'s ISO 8601 ``last_login`` as a datetime, or None."""
    if not stamp:
        return None
    try:
        # fromisoformat rejects the 'Z' suffix before Python 3.11.
        return datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None


def manageable_roles():
    """The roles offered by the Manage Roles modal, in display order.

    ``value`` is the slug that goes on the wire, ``label`` is what the user
    reads.  They are deliberately different: the modal used to post the label
    back as the role id, which broke the moment the wording was revised.
    """
    options = _role_options()
    return [
        {
            'value': role['value'],
            'label': role['label'],
            'scope': role['assigned_to'] or SCOPE_NONE,
        }
        for role in options['roles']
    ]


def role_scope_tree():
    """Programs for the Manage Roles modal, one row each.

    Only programs.  Grants are fetched from ``nfwf_grant_list`` a page at a time, 
    one group per program in this same list.

    Returns a list of ``{'id', 'name', 'title'}``.  Programs with no grants are
    kept -- for the program-scoped roles the program itself is what gets picked.
    """
    options = _role_options()
    return [
        {
            'id': program['id'],
            'name': program['name'],
            'title': program.get('title') or program['name'],
        }
        for program in options['programs']
    ]


def _role_options():
    """``nfwf_role_options``, the vocabulary the modal is built from.

    Guarded because ``manageable_roles`` and ``role_scope_tree`` are called
    straight from the template, where an uncaught NotAuthorized is a traceback
    rather than a message.  ``nfwf_role_options`` shares an auth function with
    ``nfwf_user_role_set``, which the template already checks before rendering
    the modal, so this should not fire -- but the modal is not worth the page.
    """
    try:
        return toolkit.get_action('nfwf_role_options')({}, {})
    except toolkit.NotAuthorized:
        return {'roles': [], 'programs': []}


def _row(record):
    """Shape one ``nfwf_user_list`` result for the template.

    The action returns everything but the links, which need a request context
    to build.
    """
    grants = [
        {
            'id': grant['id'],
            'name': grant['name'],
            'title': grant.get('title') or grant['name'],
            'url': url_for('organization.read', id=grant['name']),
        }
        for grant in record.get('grants') or []
    ]
    programs = [
        {
            'id': program['id'],
            'name': program['name'],
            'title': program.get('title') or program['name'],
            'url': url_for('group.read', id=program['name']),
        }
        for program in record.get('programs') or []
    ]

    role = record.get('role') or ''
    status = record.get('status') or ''
    # ``dual_scope`` means the account holds both program and grant assignments,
    # so the one role in the Role column understates what it can actually do.
    # True for 116 accounts on the production snapshot, so it is the normal case
    # rather than an oddity.
    dual_scope = bool(record.get('dual_scope'))

    return {
        'id': record['id'],
        'name': record['name'],
        'display_name': record.get('display_name') or record['name'],
        'url': url_for('user.read', id=record['name']),
        'email': record.get('email') or '',
        'status': status,
        'status_label': record.get('status_label') or '',
        'status_class': user_status_class(status),
        'last_login': user_last_login(record.get('last_login')),
        'last_login_stale': user_login_is_stale(record.get('last_login')),
        'role': role,
        'role_label': record.get('role_label') or '',
        'programs': programs,
        'grants': grants,
        # Paired with the role before it is shown: a Platform Administrator's
        # assignments are retained but inert, so "holds both" means nothing
        # there.  Same condition as assignments_in_effect, deliberately.
        'dual_scope': dual_scope and roles.assignments_in_effect(role),
        # Which status actions the kebab offers for this row.  Approve and
        # deactivate refuse nothing, so the menu is what keeps the choices
        # sensible -- see STATUS_ACTIONS.
        'actions': [
            {'key': key, 'action': action}
            for key, action in STATUS_ACTIONS.get(status, [])
        ],
        # A Platform Administrator's assignments are retained on the record but
        # superseded by the sysadmin flag, so the table must not imply they
        # apply.  ``nfwf_user_list`` rows do not carry the flag, so derive it
        # from the role the same way the contract does.
        'assignments_in_effect': roles.assignments_in_effect(role),
        # Consumed only by the Manage Roles modal, which is rendered for
        # Platform Administrators only -- see can_manage_roles in user/list.html.
        # Programs are all in the modal's list already, so ids are enough; the
        # grant picker loads its groups a page at a time, so an assigned grant
        # may not be on screen yet -- it needs the titles of what is already
        # assigned or it could not draw them.
        'role_selection': {
            'role': role,
            'program_ids': [program['id'] for program in programs],
            'grant_ids': [grant['id'] for grant in grants],
            'grants': [
                {'id': grant['id'], 'title': grant['title']}
                for grant in grants
            ],
            # Raw here, unlike the table's copy above: saving replaces *every*
            # assignment, so the modal must warn before dropping the half it
            # cannot see -- including on a Platform Administrator being demoted,
            # whose retained assignments become live again.
            'dual_scope': dual_scope,
        },
    }


def _table_meta():
    """What the table's JS needs to rebuild a row after a status action.

    Those actions return the row's *new* status, so redrawing the row needs the
    same status-to-actions mapping and colours the server rendered from.  Handed
    to the page rather than restated in manage-roles.js, for the same reason the
    role names are not restated there: two copies of this vocabulary is what let
    the UI and the API drift apart once already.

    Deactivating also removes every role, so the Role and assignment cells are
    redrawn too.  The row the action returns has no ``assignments_in_effect``,
    unlike a role save's, so the JS looks it up by role here.
    """
    return {
        'status_actions': dict(
            (status, [{'key': key, 'action': action}
                      for key, action in actions])
            for status, actions in STATUS_ACTIONS.items()
        ),
        'status_classes': dict(
            (status, user_status_class(status)) for status in roles.STATUSES
        ),
        'assignments_in_effect': dict(
            (role, roles.assignments_in_effect(role)) for role in roles.ROLES
        ),
    }


def _statuses(include_deactivated, include_rejected):
    """Map the two "Include ...?" checkboxes onto the action's status filter.

    The screen defaults to hiding deactivated and rejected accounts, which is
    exactly ``roles.DEFAULT_VISIBLE_STATUSES``; each checkbox widens it.
    """
    statuses = list(roles.DEFAULT_VISIBLE_STATUSES)
    if include_deactivated:
        statuses.append(roles.STATUS_DEACTIVATED)
    if include_rejected:
        statuses.append(roles.STATUS_REJECTED)
    return statuses

def _default_page_size():
    """Rows per page.  Core's ckan.user_list_limit already defaults to 20."""
    try:
        size = toolkit.asint(config.get('ckan.user_list_limit'))
    except (ValueError, TypeError):
        size = 20
    # nfwf_user_list rejects anything larger.
    return min(size or 20, MAX_PAGE_SIZE)


def _page_sizes(default):
    """The dropdown's choices: ``PAGE_SIZES``, plus the default if it is not one."""
    return sorted(set(PAGE_SIZES) | {default})


def _page_size(args, default):
    """Rows per page, from the dropdown's ``limit``.

    The same parameter name core's ``user.index`` reads.  Only a size the
    dropdown offers is honored; anything else -- hand-typed, or from a stale
    link -- gets the default rather than being passed through to the action.
    """
    try:
        size = int(args.get('limit', ''))
    except (TypeError, ValueError):
        return default
    return size if size in _page_sizes(default) else default


def _checkbox(args, name):
    """Read a checkbox from the query string.

    Browsers omit unticked checkboxes entirely, so absence means False.
    """
    value = args.get(name)
    if value is None:
        return False
    return value.lower() not in ('', '0', 'false', 'off', 'no')


def _pager_params(q, include_deactivated, include_rejected, limit,
                  default_limit):
    """Filter state to carry into pager links, so paging keeps the filters.

    ``limit`` is carried only when it differs from the default, so the plain
    links stay plain.
    """
    params = {}
    if q:
        params['q'] = q
    if include_deactivated:
        params['include_deactivated'] = '1'
    if include_rejected:
        params['include_rejected'] = '1'
    if limit != default_limit:
        params['limit'] = str(limit)
    return params


def _empty_table():
    default_limit = _default_page_size()
    return {
        'rows': [],
        'assignments': {},
        'page': None,
        'q': '',
        'include_deactivated': False,
        'include_rejected': False,
        'limit': default_limit,
        'page_sizes': _page_sizes(default_limit),
        'pager_params': {},
        'authorized': True,
        'meta': _table_meta(),
    }
