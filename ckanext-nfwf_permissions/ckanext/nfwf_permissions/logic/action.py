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
from ckan.lib.dictization import model_dictize
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
    u'organization_list_for_user',
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

    # `natural_number_validator` accepts 0, and a limit of 0 would otherwise
    # return an empty page alongside a non-zero `count` -- which reads as "no
    # results" while the count says otherwise. Say so instead of guessing.
    if data.get(u'limit') == 0:
        raise toolkit.ValidationError({u'limit': [toolkit._(
            u'Must be at least 1.')]})

    limit = min(data.get(u'limit', DEFAULT_LIMIT), MAX_LIMIT)
    offset = data.get(u'offset', 0)

    # Paged here rather than in SQL: `role` and the deactivated/rejected split
    # are derived rather than stored, so `accounts.search_users` resolves them
    # in Python and returns every matching row. See its docstring for why.
    matches = accounts.search_users(
        q=data.get(u'q'),
        statuses=data.get(u'statuses'),
        role=data.get(u'role'),
        program_id=data.get(u'program_id'),
        grant_id=data.get(u'grant_id'))

    # Slice first, then build. A record costs two queries to name the user's
    # programs and grants, so building them before paging would charge every
    # account on the site for a page that shows twenty.
    return {
        u'count': len(matches),
        u'limit': limit,
        u'offset': offset,
        u'results': [accounts.user_record(user)
                     for user in matches[offset:offset + limit]],
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
    if role != roles.PLATFORM_ADMIN:
        _assert_an_administrator_remains(
            context, user, u'role', toolkit._(u'demote'))
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
    if new_status != roles.STATUS_ACTIVE:
        # Every status but Active stops the account being used, so closing the
        # last Platform Administrator's strands the site exactly as demoting
        # them would.
        _assert_an_administrator_remains(
            context, user, u'id', toolkit._(u'close'))
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


def _assert_an_administrator_remains(context, user, field, verb):
    """Refuse anything that would leave the site with no Platform Administrator.

    Every action in this file is Platform-Administrator-only, so removing the
    last one leaves no account able to appoint another: recovery means
    ``ckan sysadmin add`` on the server, which needs a deploy key and somebody
    who knows that is the answer.

    Self-removal is refused for the same reason one step earlier. It is the
    likelier accident of the two -- the screen is a table of other people's
    names, and the row for *you* looks exactly like the rest -- and a Platform
    Administrator wanting to step down can be removed by another one.

    Two routes reach this, and guarding only one would be pointless: a role
    change away from Platform Administrator, and a status change that closes
    the account. Deactivating the last two administrators locks the site just
    as thoroughly as demoting them, and leaves ``remaining`` at zero besides,
    since a deleted account does not count as one.
    """
    if not user.sysadmin:
        return

    caller = context.get(u'auth_user_obj') or model.User.get(
        context.get(u'user'))
    if caller is not None and caller.id == user.id:
        raise toolkit.ValidationError({field: [toolkit._(
            u'You cannot {0} your own Platform Administrator account. Ask '
            u'another Platform Administrator to do it.').format(verb)]})

    # Deleted accounts do not count: `legacy-admin` carries the flag in this data
    # and could not log in to use it.
    remaining = model.Session.query(model.User).filter(
        model.User.sysadmin.is_(True),
        model.User.state == u'active',
        model.User.id != user.id).count()
    if not remaining:
        raise toolkit.ValidationError({field: [toolkit._(
            u'{0} is the only Platform Administrator left. Appoint another '
            u'one before you {1} this account.').format(user.name, verb)]})


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
    the grants that legitimately belong to no program at all could not exist
    otherwise, since ``owner_group`` would have to name a program the creator
    administers.

    Raises ``ValidationError`` against ``owner_group`` rather than
    ``NotAuthorized``, deliberately. This refuses a *submitted value*, which
    makes it a field error, and the group edit view turns a ``NotAuthorized``
    from the action into ``abort(404, 'Group not found')``
    (``ckan/views/group.py:1093-1094``) -- so the caller was told their grant
    did not exist and lost everything they had typed, while a
    ``ValidationError`` re-renders the form with the message on the field.
    The refusal is exactly as strong either way, and this matches how the
    retired-capacity rule below already reports itself.
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

    raise toolkit.ValidationError({u'owner_group': [toolkit._(
        u'A grant must belong to a program you administer.')]})


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

    Doing it synchronously is a deliberate choice. The work is bounded by a
    single grant's datasets, which is a small number here, so it is far cheaper
    than a background job that needs a worker process to exist -- which this
    deployment does not run. A bulk change of ``owner_group``, as the role
    migration does, still needs a full ``ckan search-index rebuild``.
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
      gone; on a grant the only role is Grant Editor. Existing rows with those
      capacities are left alone for the migration to report on rather than
      being rewritten here -- but nothing new should be added.
    * **One role per user.** Settled 2026-08-19, and a conflict-of-interest
      control rather than a convenience: Program Reader is for outside
      contractors who are typically conflicted out of applying for grant funds,
      so it must not be combinable with a grant role. That makes it a
      server-side rule, not something the UI can be trusted to hide. Note the
      existing data does not satisfy it; see the migration report.
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


def _assert_no_group_hierarchy(context):
    """Refuse a group-to-group membership row.

    The role model has no concept of one. A grant points at its program
    through the ``owner_group`` extra precisely *because* it is not a CKAN
    hierarchy -- ``logic/auth.py``'s second layer exists because none of
    CKAN's native cascading reaches it. A ``Member`` row with
    ``table_name='group'`` reintroduces exactly that cascading, outside the
    model and outside the audit.

    Demonstrated before this guard existed: a Program Administrator could
    write ``member_create(id=<a grant in their program>, object=<any other
    grant>, object_type='group')``. ``member_create``'s auth function checks
    only ``id``, never ``object``, so the parent could be a grant from a
    different program. That makes the parent's holders of the retired grant
    ``admin`` capacity -- accounts ``user_role`` reports as holding *no role* --
    gain full authority over the child grant through
    ``has_user_permission_for_group_or_org``'s cascade, with no membership row
    on it. ``migration.py`` filters on ``table_name == 'user'`` throughout, so
    the report certifies a site whose effective permissions no longer match
    the role model.

    Only ``organization``-typed parents actually fire the cascade, since
    ``get_parent_group_hierarchy`` is scoped to the child's own type -- a
    program parent is filtered out. Both are refused anyway: the distinction
    is CKAN's to change, not ours to depend on.

    ``ignore_auth`` and Platform Administrators are exempt, matching
    ``_assert_grant_belongs_to_an_administered_program``. Nothing in this
    extension writes such a row, so the exemption costs nothing today and
    leaves a sysadmin able to build a hierarchy deliberately if CKAN's own
    features ever need one.
    """
    if context.get(u'ignore_auth'):
        return
    if authz.is_sysadmin(context.get(u'user')):
        return
    raise toolkit.ValidationError({u'object_type': [toolkit._(
        u'Programs and grants are related through the grant\'s program field, '
        u'not through group membership. Only a Platform Administrator may '
        u'create a group-to-group relationship.')]})


@toolkit.chained_action
def member_create(original_action, context, data_dict):
    """Guard the role model on the generic membership action.

    Also covers removal indirectly: `member_delete` defers its *authorization*
    here, though not its validation, since removing a row never creates a
    conflict.
    """
    data_dict = data_dict or {}
    object_type = data_dict.get(u'object_type')
    if object_type == u'user':
        _assert_membership_is_allowed(
            context, data_dict.get(u'id'), data_dict.get(u'object'),
            data_dict.get(u'capacity'))
    elif object_type == u'group':
        _assert_no_group_hierarchy(context)
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


@toolkit.chained_action
def organization_list_for_user(original_action, context, data_dict):
    """Add the grants in the subject's programs to what stock returns.

    Stock builds this list purely from the subject's own membership rows
    (``ckan/logic/action/get.py:700-731``), and a Program Administrator holds
    none on the grants they administer -- so it came back **empty** for them.
    That is what both dataset-form templates gate their Grant selector on, so
    the form rendered with no grant to choose and the submit could not
    succeed. The ``package_create`` auth override got them to the form; this
    is what puts anything in the dropdown.

    Capacity is reported as ``admin`` because that is what the permission
    matrix actually grants them over these grants -- organization_update and
    _delete, member_create, package_create and _update, dataset_purge. The
    requested ``permission`` is deliberately not consulted for the same
    reason: ``admin`` satisfies every permission check in CKAN
    (``ckan/authz.py:357-358``), so any permission stock might be asked about
    is one they hold here.

    Sysadmins need no special case: stock already returns every organization
    for them, so the set difference below is empty and nothing is added.
    """
    orgs = original_action(context, data_dict)
    data_dict = data_dict or {}

    subject = data_dict.get(u'id') or context.get(u'user')
    administered = roles.programs_for_user(subject, [roles.CAPACITY_ADMIN])
    if not administered:
        return orgs

    wanted = set()
    for program_id in administered:
        wanted |= roles.grants_in_program(program_id)
    missing = sorted(wanted - {org.get(u'id') for org in orgs})
    if not missing:
        return orgs

    groups = model.Session.query(model.Group).filter(
        model.Group.id.in_(missing),
        model.Group.state == u'active').all()

    # Dictized exactly as stock does, so callers cannot tell the two halves
    # of the list apart -- including the capacity key, which the templates read.
    context[u'with_capacity'] = True
    return orgs + model_dictize.group_list_dictize(
        [(group, roles.CAPACITY_ADMIN) for group in groups], context,
        with_package_counts=toolkit.asbool(
            data_dict.get(u'include_dataset_count')),
        with_member_counts=toolkit.asbool(
            data_dict.get(u'include_member_count')))
