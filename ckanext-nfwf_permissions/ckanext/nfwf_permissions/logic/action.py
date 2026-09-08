# encoding: utf-8
"""The ``nfwf_user_*`` API for Tasks 117 and 126, plus chained core actions.

These were stubs returning fixture data. They now read and write the database,
with the names, parameters, schemas and response shapes unchanged -- those are
the contract the user management screen (Task 117) and the Manage Roles modal
(Task 126) build against. The ``"stub": true`` marker the stub responses
carried is gone, which is the only difference a caller can observe.

Record shapes and status storage live in ``accounts``, so this stays a thin
layer of authorize, validate, delegate.
"""
import logging

from ckan import authz, model
from ckan.lib import search
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import accounts, roles
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
    u'member_create',
    u'organization_member_create',
    u'group_member_create',
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

    limit = min(data.get(u'limit', DEFAULT_LIMIT), MAX_LIMIT)
    offset = data.get(u'offset', 0)

    # Paged here rather than in SQL: `role` and the deactivated/rejected split
    # are derived rather than stored, so `accounts.search_users` resolves them
    # in Python and returns every match. See its docstring for why.
    matches = accounts.search_users(
        q=data.get(u'q'),
        statuses=data.get(u'statuses'),
        role=data.get(u'role'),
        program_id=data.get(u'program_id'),
        grant_id=data.get(u'grant_id'))

    return {
        u'count': len(matches),
        u'limit': limit,
        u'offset': offset,
        u'results': matches[offset:offset + limit],
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

    return accounts.role_record(_user_or_404(data[u'id']))


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
        u'programs': accounts.programs(),
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

    user = _user_or_404(data[u'id'])
    programs = _resolved(u'program_ids', program_ids, False)
    grants = _resolved(u'grant_ids', grant_ids, True)

    _apply_role(context, user, role, programs, grants)

    # The writes above changed what `roles` would answer, and it memoizes per
    # request, so without clearing this the record below describes the old state.
    roles.clear_cache()
    return accounts.role_record(model.User.get(user.id))


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

    user = _user_or_404(data[u'id'])
    return accounts.user_record(
        accounts.set_status(context, user, new_status))


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


def _user_or_404(id_or_name):
    """Look up a user by id or name, or raise ObjectNotFound."""
    user = model.User.get(id_or_name)
    if user is None:
        raise toolkit.ObjectNotFound(
            toolkit._(u'User not found: {0}').format(id_or_name))
    return user


def _resolved(field, wanted_ids, is_organization):
    """Look up every id, rejecting any that does not exist.

    An unknown program or grant has to be a *failed* save, not an empty one.
    Skipping the ones we cannot find would store the role with no assignment at
    all while the response still reported success -- a silent partial write,
    and for a program role that means a user who can see nothing wondering why.
    """
    if not wanted_ids:
        return []

    found = model.Session.query(model.Group).filter(
        model.Group.id.in_(list(wanted_ids)),
        model.Group.state == u'active',
        model.Group.is_organization.is_(is_organization)).all()
    by_id = {group.id: group for group in found}

    missing = [wanted for wanted in wanted_ids if wanted not in by_id]
    if missing:
        raise toolkit.ValidationError({
            field: [toolkit._(u'Unknown ids: {0}').format(u', '.join(missing))]
        })
    return [by_id[wanted] for wanted in wanted_ids]


def _apply_role(context, user, role, programs, grants):
    """Make the stored assignments say exactly ``role`` and nothing else.

    Order matters. The other scope is cleared *before* the wanted one is
    written, because the chained membership actions below refuse to leave a user
    holding both a program and a grant assignment -- writing first would trip
    the extension's own rule halfway through.
    """
    _set_sysadmin(context, user, role == roles.PLATFORM_ADMIN)

    if role == roles.PLATFORM_ADMIN:
        # Retained, not deleted. The sysadmin flag already implies more than
        # any assignment does, so leaving them costs nothing and means a later
        # demotion gives the user back what they had.
        return

    capacity = {
        roles.PROGRAM_ADMIN: roles.CAPACITY_ADMIN,
        roles.PROGRAM_READER: roles.CAPACITY_MEMBER,
        roles.GRANT_EDITOR: roles.CAPACITY_EDITOR,
    }[role]

    if roles.accepts_programs(role):
        _replace_memberships(context, user, True, [], None)
        _replace_memberships(context, user, False, programs, capacity)
    else:
        _replace_memberships(context, user, False, [], None)
        _replace_memberships(context, user, True, grants, capacity)


def _replace_memberships(context, user, is_organization, groups, capacity):
    """Make the user's memberships of one kind be exactly ``groups``.

    Uses the member actions rather than the model so CKAN's own bookkeeping
    runs. They are called with ``ignore_auth`` because this *is* the sanctioned
    path -- it has already validated the role model, and the chained checks
    below exist to catch changes that come in any other way.
    """
    internal = {u'user': context.get(u'user'), u'ignore_auth': True}

    held = (roles.grants_for_user(user) if is_organization
            else roles.programs_for_user(user))
    wanted = [group.id for group in groups]

    for group_id in sorted(set(held) - set(wanted)):
        toolkit.get_action(u'member_delete')(dict(internal), {
            u'id': group_id, u'object': user.id, u'object_type': u'user'})

    for group_id in wanted:
        # member_create updates the capacity of an existing row rather than
        # duplicating it, so this covers both adding and re-grading.
        toolkit.get_action(u'member_create')(dict(internal), {
            u'id': group_id, u'object': user.id, u'object_type': u'user',
            u'capacity': capacity})

    roles.clear_cache()


def _set_sysadmin(context, user, wanted):
    """Grant or revoke the sysadmin flag, which *is* the Platform Admin role."""
    if bool(user.sysadmin) == wanted:
        return
    accounts.patch(context, user, sysadmin=wanted)


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


# -- Chained membership actions ----------------------------------------------
#
# These guard the role model against changes that arrive by any route other
# than nfwf_user_role_set -- the stock "Members" screens on a grant or a
# program, and direct API calls.
#
# `ignore_auth` is honoured, which is not a loophole but a requirement:
# CKAN's own `_group_or_org_create` makes the creating user an `admin` of a new
# organization by calling member_create with ignore_auth set
# (ckan/logic/action/create.py:773-784). Refusing retired capacities without
# that exemption would make it impossible to create a grant at all.

def _assert_membership_is_allowed(context, group_ref, user_ref, capacity):
    """Refuse a membership that would break the role model.

    Two rules, both from the redesign:

    * **The retired grant capacities.** Grant `member` and grant `admin` are
      gone; on a grant the only role is Grant Editor. Production still holds
      585 grant-`admin` and 59 grant-`member` rows, which the migration reports
      rather than converts -- but nothing new should be added.
    * **One role per user.** Settled 2026-08-19, and a conflict-of-interest
      control rather than a convenience: Program Reader is for outside
      contractors who are typically conflicted out of applying for grant funds,
      so it must not be combinable with a grant role. That makes it a
      server-side rule, not something the UI can be trusted to hide.
    """
    if context.get(u'ignore_auth'):
        return

    group = model.Group.get(group_ref)
    if group is None:
        return  # Let the original action raise its own NotFound.

    user = model.User.get(user_ref)
    if user is None:
        return

    if group.is_organization and capacity in roles.RETIRED_GRANT_CAPACITIES:
        raise toolkit.ValidationError({u'capacity': [toolkit._(
            u'{0} is no longer a role on a grant. Use {1}.').format(
                capacity, roles.ROLE_LABELS[roles.GRANT_EDITOR])]})

    # Would this leave the user holding both scopes at once?
    other_scope = (roles.programs_for_user(user) if group.is_organization
                   else roles.grants_for_user(user))
    if other_scope:
        held = roles.role_label(roles.user_role(user)) or toolkit._(u'a role')
        raise toolkit.ValidationError({u'object': [toolkit._(
            u'{0} already holds {1}. A user has one role at a time, so remove '
            u'that first.').format(user.name, held)]})


@toolkit.chained_action
def member_create(original_action, context, data_dict):
    """Guard the role model on the generic membership action.

    Also covers removal indirectly: `member_delete` defers its *authorization*
    here, though not its validation, since removing a row never creates a
    conflict.
    """
    data_dict = data_dict or {}
    if data_dict.get(u'object_type') == u'user':
        _assert_membership_is_allowed(
            context, data_dict.get(u'id'), data_dict.get(u'object'),
            data_dict.get(u'capacity'))
    return original_action(context, data_dict)


@toolkit.chained_action
def organization_member_create(original_action, context, data_dict):
    """Guard the role model on a grant's Members screen.

    This one speaks `role` and `username` where member_create speaks `capacity`
    and `object`; same rule, different vocabulary.
    """
    data_dict = data_dict or {}
    _assert_membership_is_allowed(
        context, data_dict.get(u'id'),
        data_dict.get(u'username') or data_dict.get(u'id_or_name'),
        data_dict.get(u'role'))
    return original_action(context, data_dict)


@toolkit.chained_action
def group_member_create(original_action, context, data_dict):
    """Guard the role model on a program's Members screen."""
    data_dict = data_dict or {}
    _assert_membership_is_allowed(
        context, data_dict.get(u'id'),
        data_dict.get(u'username') or data_dict.get(u'id_or_name'),
        data_dict.get(u'role'))
    return original_action(context, data_dict)
