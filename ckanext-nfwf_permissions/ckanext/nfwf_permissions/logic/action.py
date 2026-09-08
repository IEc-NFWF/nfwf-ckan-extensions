# encoding: utf-8
"""API contract for Tasks 117 and 126.

Every action here is a **stub**. It authorizes the caller and validates its
input for real, then returns realistically-shaped fixture data instead of
touching the database. The names, parameters, schemas and response shapes are
the contract that the user management screen (Task 117) and the Manage Roles
modal (Task 126) build against; the bodies get replaced as Task 125 lands,
without any caller changing.

Stub responses carry ``"stub": true`` so it is obvious in the browser's network
tab that the data is not real yet. That key disappears when the real
implementation lands, and nothing should depend on it.
"""
import logging

from ckan import authz, model
from ckan.lib import search
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import fixtures, roles
from ckanext.nfwf_permissions.logic import schema

log = logging.getLogger(__name__)

__all__ = [
    u'nfwf_user_list',
    u'nfwf_user_role_show',
    u'nfwf_user_role_set',
    u'nfwf_user_approve',
    u'nfwf_user_reject',
    u'nfwf_user_deactivate',
    u'nfwf_role_options',
    # Chained core actions. Real, not stubs -- see the bottom of this file.
    u'organization_create',
    u'organization_update',
]

#: US 0117 slide 4: "Default display 20 users".
DEFAULT_LIMIT = 20

#: Ceiling on ``limit`` so one call cannot ask for every user at once.
MAX_LIMIT = 100


@toolkit.side_effect_free
def nfwf_user_list(context, data_dict):
    """List users for the centralized user management screen.

    Core ``user_list`` cannot serve this screen: it filters out deleted users in
    SQL, and both "Deactivated" and "Account request rejected" are stored as
    CKAN's ``deleted`` state. It also has no status or role filter. Hence a
    separate action rather than a wrapper around the core one.

    :param q: match against name, display name or email
    :type q: string
    :param statuses: which account statuses to include; defaults to
        ``['needs_review', 'active']``, matching the screen's default of hiding
        deactivated and rejected accounts
    :type statuses: list of strings
    :param role: only users holding this role
    :type role: string
    :param program_id: only users assigned to this program
    :type program_id: string
    :param grant_id: only users assigned to this grant
    :type grant_id: string
    :param limit: page size, default 20, maximum 100
    :type limit: int
    :param offset: rows to skip, default 0
    :type offset: int

    :rtype: dictionary with ``count``, ``limit``, ``offset`` and ``results``,
        where ``count`` is the total number of matches before paging
    """
    toolkit.check_access(u'nfwf_user_list', context, data_dict)
    data = _validated(data_dict, schema.nfwf_user_list_schema(), context)

    statuses = data.get(u'statuses') or roles.DEFAULT_VISIBLE_STATUSES
    limit = min(data.get(u'limit', DEFAULT_LIMIT), MAX_LIMIT)
    offset = data.get(u'offset', 0)

    matches = [user for user in fixtures.users()
               if user[u'status'] in statuses]

    query = data.get(u'q')
    if query:
        needle = query.strip().lower()
        matches = [user for user in matches
                   if needle in user[u'display_name'].lower()
                   or needle in user[u'email'].lower()
                   or needle in user[u'name'].lower()]

    role = data.get(u'role')
    if role:
        matches = [user for user in matches if user[u'role'] == role]

    program_id = data.get(u'program_id')
    if program_id:
        matches = [user for user in matches
                   if program_id in _ids(user[u'programs'])]

    grant_id = data.get(u'grant_id')
    if grant_id:
        matches = [user for user in matches
                   if grant_id in _ids(user[u'grants'])]

    return {
        u'count': len(matches),
        u'limit': limit,
        u'offset': offset,
        u'results': matches[offset:offset + limit],
        u'stub': True,
    }


@toolkit.side_effect_free
def nfwf_user_role_show(context, data_dict):
    """Return one user's role and assignments, for populating the modal.

    :param id: user id or name
    :type id: string

    :rtype: dictionary -- see ``nfwf_user_role_set``
    """
    toolkit.check_access(u'nfwf_user_role_show', context, data_dict)
    data = _validated(data_dict, schema.nfwf_user_id_schema(), context)

    return _role_dict(fixtures.user_by_id_or_name(data[u'id']))


@toolkit.side_effect_free
def nfwf_role_options(context, data_dict):
    """Return the role vocabulary and the selectable programs for the modal.

    Saves the UI hard-coding role names and labels, so renaming a role stays a
    backend change.

    Grants are deliberately *not* returned: production has roughly 570 of them,
    which is not a checkbox list. Use ``organization_autocomplete`` or a paged
    ``organization_list`` for the Grant Editor case -- see the README.

    :rtype: dictionary with ``roles`` and ``programs``
    """
    toolkit.check_access(u'nfwf_role_options', context, data_dict)

    return {
        u'roles': [{
            u'value': role,
            u'label': roles.ROLE_LABELS[role],
            u'assigned_to': roles.ROLE_SCOPE[role],
        } for role in roles.ROLES],
        u'programs': fixtures.programs(),
        u'stub': True,
    }


def nfwf_user_role_set(context, data_dict):
    """Set a user's role and assignments. Single entry point for the modal.

    A user holds exactly one role, so this *replaces* whatever they had rather
    than adding to it. ``role`` determines which assignment list is required:

    ==========================  ===================
    Role                        Assignments
    ==========================  ===================
    ``platform_admin``          none
    ``program_admin``           ``program_ids``
    ``program_reader``          ``program_ids``
    ``grant_editor``            ``grant_ids``
    ==========================  ===================

    Promoting someone to ``platform_admin`` does not discard their existing
    program or grant assignments -- they are kept on the record and simply not
    consulted, so demoting them later restores what they had. The response flags
    this with ``assignments_in_effect: false``.

    :param id: user id or name
    :type id: string
    :param role: one of ``platform_admin``, ``program_admin``,
        ``program_reader``, ``grant_editor``
    :type role: string
    :param program_ids: programs to assign, for the two program roles
    :type program_ids: list of strings
    :param grant_ids: grants to assign, for ``grant_editor``
    :type grant_ids: list of strings

    :rtype: dictionary with ``user_id``, ``user_name``, ``display_name``,
        ``role``, ``role_label``, ``programs``, ``grants`` and
        ``assignments_in_effect``
    """
    toolkit.check_access(u'nfwf_user_role_set', context, data_dict)
    data = _validated(data_dict, schema.nfwf_user_role_set_schema(), context)

    role = data[u'role']
    program_ids = data.get(u'program_ids', [])
    grant_ids = data.get(u'grant_ids', [])
    _check_assignment_scope(role, program_ids, grant_ids)

    user = fixtures.user_by_id_or_name(data[u'id'])
    # Stub: echo back what *would* be stored. The real implementation writes
    # member rows (or the sysadmin flag) and returns the same shape.
    user[u'role'] = role
    if roles.accepts_programs(role):
        user[u'programs'] = _resolved(
            u'program_ids', program_ids, fixtures.programs_by_id(program_ids))
        user[u'grants'] = []
    elif roles.accepts_grants(role):
        user[u'grants'] = _resolved(
            u'grant_ids', grant_ids, fixtures.grants_by_id(grant_ids))
        user[u'programs'] = []
    # else Platform Administrator: keep both lists exactly as they were.
    #
    # Only this role retains. Switching *between* program and grant roles has to
    # clear the other list, because for those roles the assignment IS the
    # permission -- leaving an 'editor' row behind would leave real edit rights
    # behind with it. The sysadmin flag already implies more than any assignment
    # does, so retaining is harmless there and makes a later demotion restore
    # what the user had.

    return _role_dict(user)


def nfwf_user_approve(context, data_dict):
    """Approve an account awaiting review, moving it to Active.

    :param id: user id or name
    :type id: string

    :rtype: the updated user dictionary, as returned by ``nfwf_user_list``
    """
    return _set_status(
        context, data_dict, u'nfwf_user_approve', roles.STATUS_ACTIVE)


def nfwf_user_reject(context, data_dict):
    """Reject an account request.

    :param id: user id or name
    :type id: string

    :rtype: the updated user dictionary, as returned by ``nfwf_user_list``
    """
    return _set_status(
        context, data_dict, u'nfwf_user_reject', roles.STATUS_REJECTED)


def nfwf_user_deactivate(context, data_dict):
    """Deactivate an existing account.

    :param id: user id or name
    :type id: string

    :rtype: the updated user dictionary, as returned by ``nfwf_user_list``
    """
    return _set_status(
        context, data_dict, u'nfwf_user_deactivate', roles.STATUS_DEACTIVATED)


# -- Internals ---------------------------------------------------------------

def _validated(data_dict, action_schema, context):
    """Run ``data_dict`` through ``action_schema``, raising on any error.

    Actions registered by an extension are not validated by CKAN automatically,
    so each one does this explicitly.
    """
    data, errors = toolkit.navl_validate(data_dict, action_schema, context)
    if errors:
        raise toolkit.ValidationError(errors)
    return data


def _set_status(context, data_dict, action_name, new_status):
    toolkit.check_access(action_name, context, data_dict)
    data = _validated(data_dict, schema.nfwf_user_id_schema(), context)

    user = fixtures.user_by_id_or_name(data[u'id'])
    # Stub: the real implementation writes user.state plus the plugin_extras key
    # described in roles.STATUS_STORAGE, via user_update -- which is why the
    # ckanext-oauth2 block has to be relaxed first.
    user[u'status'] = new_status
    user[u'status_label'] = roles.status_label(new_status)
    return user


def _check_assignment_scope(role, program_ids, grant_ids):
    """Enforce that assignments match what the role is assigned to.

    ASSUMPTION, worth confirming: a program or grant role must carry at least
    one assignment. A Program Administrator of no programs, or a Grant Editor of
    no grants, has no permissions at all and is almost certainly a mistake in
    the UI rather than something anyone wants to save.
    """
    errors = {}
    label = roles.ROLE_LABELS[role]

    if roles.accepts_programs(role):
        if not program_ids:
            errors[u'program_ids'] = [
                toolkit._(u'{0} must be assigned at least one program.')
                .format(label)]
    elif program_ids:
        errors[u'program_ids'] = [
            toolkit._(u'{0} is not assigned to programs.').format(label)]

    if roles.accepts_grants(role):
        if not grant_ids:
            errors[u'grant_ids'] = [
                toolkit._(u'{0} must be assigned at least one grant.')
                .format(label)]
    elif grant_ids:
        errors[u'grant_ids'] = [
            toolkit._(u'{0} is not assigned to grants.').format(label)]

    if errors:
        raise toolkit.ValidationError(errors)


def _resolved(field, wanted_ids, found):
    """Reject ids that do not exist instead of silently dropping them.

    ``fixtures.programs_by_id`` and ``grants_by_id`` skip ids they do not
    recognise, so a typo would otherwise save as the role with *no* assignment
    while the response still reported success -- a silent partial write. The
    real implementation must not do that either: an unknown program or grant is
    a failed save, not an empty one.
    """
    missing = [wanted for wanted in wanted_ids if wanted not in _ids(found)]
    if missing:
        raise toolkit.ValidationError({
            field: [toolkit._(u'Unknown ids: {0}').format(u', '.join(missing))]
        })
    return found


def _role_dict(user):
    role = user.get(u'role')
    return {
        u'user_id': user[u'id'],
        u'user_name': user[u'name'],
        u'display_name': user[u'display_name'],
        u'role': role,
        u'role_label': roles.role_label(role),
        u'programs': user.get(u'programs', []),
        u'grants': user.get(u'grants', []),
        u'assignments_in_effect': roles.assignments_in_effect(role),
        u'stub': True,
    }


def _ids(records):
    return [record[u'id'] for record in records]


# -- Chained core actions ----------------------------------------------------
#
# These are the real thing, not stubs. ``logic/auth.py`` can decide *whether*
# a Program Administrator may create or edit a grant, but not *which program*
# the grant may be filed under -- that depends on the submitted data, and it
# has to hold on update as well as create, or a Program Administrator could
# take a grant they legitimately hold and move it into someone else's program.

def _assert_grant_belongs_to_an_administered_program(context, data_dict):
    """Refuse to file a grant under a program the caller does not administer.

    Applies to create, update *and* patch: ``organization_patch`` merges onto
    the stored record and then calls ``organization_update``, so checking here
    sees the effective value rather than a partial one.

    Two exemptions.

    ``ignore_auth`` is honoured, mirroring ``authz.is_authorized``
    (``ckan/authz.py:207-208``). Without it every internal caller that
    deliberately bypasses authorization -- the test factories, the role
    migration, ``ckan`` CLI commands -- would be refused.

    Platform Administrators are exempt outright. They own the whole site, and
    the 30 grants that legitimately belong to no program at all could not exist
    otherwise, since ``owner_group`` would have to name a program they
    administer.
    """
    if context.get(u'ignore_auth'):
        return

    user = context.get(u'user')
    if authz.is_sysadmin(user):
        return

    submitted = (data_dict or {}).get(u'owner_group')
    # Resolve first: a form may post a name while ``programs_for_user`` deals
    # in ids, and an unknown or deleted reference resolves to None.
    program = roles.program_id(submitted) if submitted else None
    if program and program in roles.programs_for_user(
            user, [roles.CAPACITY_ADMIN]):
        return

    raise toolkit.NotAuthorized(toolkit._(
        u'A grant must belong to a program you administer.'))


@toolkit.chained_action
def organization_create(original_action, context, data_dict):
    """Enforce which program a new grant is filed under."""
    _assert_grant_belongs_to_an_administered_program(context, data_dict)
    return original_action(context, data_dict)


@toolkit.chained_action
def organization_update(original_action, context, data_dict):
    """Enforce that a grant cannot be moved out of the caller's program.

    Also stops a Program Administrator orphaning a grant by clearing its
    ``owner_group``, which would put it beyond their own reach and everyone
    else's but a Platform Administrator's.

    Reindexes the grant's datasets when the program actually changes, because
    their permission labels are derived from it -- see ``labels``.
    """
    _assert_grant_belongs_to_an_administered_program(context, data_dict)

    before = roles.program_id_for_grant(data_dict.get(u'id'))
    result = original_action(context, data_dict)
    _reindex_if_program_changed(result, before)
    return result


def _reindex_if_program_changed(organization, before):
    """Reindex a grant's datasets if its ``owner_group`` moved.

    Permission labels are written into Solr at index time, so a grant that
    changes program leaves every one of its datasets carrying the *old*
    program's label until something reindexes them. Nothing in CKAN does that
    on its own.

    This is the reason ``roles.clear_cache`` exists: ``program_id_for_grant``
    is memoized per request, and it was already asked this question a few lines
    above, so without clearing it the "after" value would be the stale "before"
    one and a real move would look like no change at all.

    Doing it synchronously is a deliberate choice. The work is bounded by one
    grant -- the largest holds 27 datasets and the average is four -- so it is
    far cheaper than a background job that needs a worker process to exist,
    which this deployment does not run. A bulk change of ``owner_group``, as the
    role migration does, still needs a full ``ckan search-index rebuild``.
    """
    roles.clear_cache()
    if roles.program_id_for_grant(organization[u'id']) == before:
        return

    package_ids = [row[0] for row in model.Session.query(model.Package.id)
                   .filter(model.Package.owner_org == organization[u'id'])
                   .filter(model.Package.state != u'deleted').all()]
    if not package_ids:
        return

    log.info(u'Grant %s changed program; reindexing %d dataset(s)',
             organization[u'id'], len(package_ids))
    search.rebuild(package_ids=package_ids, quiet=True)

    # The explicit commit is required, not belt and braces. `rebuild`'s
    # package_ids branch calls `update_dict(pkg_dict, True)` -- hard-coding
    # defer_commit=True regardless of what the caller asked for -- and the
    # `model.Session.commit()` at the end of it commits the *database* session,
    # not Solr (ckan/lib/search/__init__.py:198-201, 250). So without this the
    # new labels sit uncommitted and every search still answers from the old
    # ones. Caught by the reindex test, which saw a moved grant's dataset still
    # visible to the previous program's readers.
    search.commit()
