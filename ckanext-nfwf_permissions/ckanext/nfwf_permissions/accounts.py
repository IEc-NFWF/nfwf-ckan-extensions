# encoding: utf-8
"""Account records and status storage for the user-management screen.

The four statuses in the US 0117 mockup do not map one-to-one onto CKAN's three
user states, so two of them share ``deleted`` and are told apart by a marker in
``plugin_extras``. ``roles.STATUS_STORAGE`` is the table; everything here reads
and writes through it so the two directions cannot drift apart.

| Mockup status            | ``user.state`` | ``plugin_extras.nfwf.account_status`` |
|--------------------------|----------------|---------------------------------------|
| Needs Review             | ``pending``    | --                                    |
| Active                   | ``active``     | --                                    |
| Deactivated              | ``deleted``    | ``deactivated``                       |
| Account request rejected | ``deleted``    | ``rejected``                          |

Kept separate from ``logic/action.py`` so the actions stay a thin layer over
this, and so the record shapes -- which are the contract Tasks 117 and 126 build
against -- can be tested without going through authorization.
"""
from sqlalchemy import func, or_

from ckan import model
from ckan.logic import schema as core_schema
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles

#: Key under ``plugin_extras[roles.PLUGIN_EXTRAS_KEY]`` holding the marker.
ACCOUNT_STATUS = u'account_status'


# -- Status ------------------------------------------------------------------

def _marker(user):
    extras = user.plugin_extras or {}
    return extras.get(roles.PLUGIN_EXTRAS_KEY, {}).get(ACCOUNT_STATUS)


def status_of(user):
    """Return which of the four mockup statuses ``user`` is in.

    Switches on ``state`` first and only consults the marker for a deleted
    account, so a stale marker left on a reactivated account cannot make it
    report as rejected.
    """
    if user.state == model.State.PENDING:
        return roles.STATUS_NEEDS_REVIEW
    if user.state == model.State.ACTIVE:
        return roles.STATUS_ACTIVE
    if user.state == model.State.DELETED:
        # A deleted account with no marker predates this feature. Report it as
        # deactivated, which is the less prejudicial of the two readings -- it
        # says nothing about why the account was closed.
        if _marker(user) == roles.STATUS_REJECTED:
            return roles.STATUS_REJECTED
        return roles.STATUS_DEACTIVATED
    return None


def set_status(context, user, status):
    """Move ``user`` to ``status``, writing both halves of its storage.

    Goes through ``user_patch`` rather than the model directly so CKAN's own
    bookkeeping runs. ``state`` (``ckan/logic/schema.py:478``) and
    ``plugin_extras`` (``:481``) both carry ``ignore_not_sysadmin``, as does
    ``sysadmin`` itself (``:474``), which ``_set_sysadmin`` writes through this
    same helper.

    That validator is **not** a refusal. It returns early for a sysadmin or
    for ``ignore_auth`` and otherwise does ``data.pop(key)``
    (``ckan/logic/validators.py:588-597``), so where it applies the field is
    silently dropped: ``user_update`` commits, returns 200, and the record this
    module then re-reads still shows the old value -- a write that reports
    success and did nothing.

    **Where it applies is the part worth being exact about**, because an
    earlier version of this note gave the fragile reason for why that cannot
    happen here -- "every caller is a Platform Administrator" -- and the real
    reason is structural and survives new callers. Both halves were probed:

    * A non-sysadmin patching **someone else** never reaches the validator.
      ``user_update``'s own auth refuses first, loudly, with ``NotAuthorized``.
      Every call through this module targets someone else, so this is the case
      that matters, and the failure is loud.
    * A non-sysadmin patching **themselves** does reach it, and does get the
      quiet failure -- ``sysadmin=True`` returns normally and changes nothing.
      Nothing here self-patches.

    So adding callers who are not Platform Administrators does not open the
    quiet path; ``nfwf_user_role_set`` now admits Program Administrators and a
    test pins that they get ``NotAuthorized`` rather than a false success. What
    *would* open it is a caller patching its own record -- don't.

    (An earlier version of this note also cited
    ``logic/action/update.py:834-838`` as a gate. It is not one: that block
    runs *after* ``model.repo.commit()`` and only decides whether the response
    echoes ``plugin_extras`` back.)

    Lifting ``ckanext-oauth2``'s blanket refusal of ``user_update`` was still
    the prerequisite for any of this working.
    """
    state, marker = roles.STATUS_STORAGE[status]

    extras = dict(user.plugin_extras or {})
    ours = dict(extras.get(roles.PLUGIN_EXTRAS_KEY) or {})
    if marker is None:
        ours.pop(ACCOUNT_STATUS, None)
    else:
        ours[ACCOUNT_STATUS] = marker
    if ours:
        extras[roles.PLUGIN_EXTRAS_KEY] = ours
    else:
        extras.pop(roles.PLUGIN_EXTRAS_KEY, None)

    patch(context, user, state=state, plugin_extras=extras)
    return model.User.get(user.id)


def patch(context, user, **fields):
    """``user_patch`` one or more fields on ``user``.

    ``name`` and ``email`` are passed explicitly every time, and that is not
    redundant. ``user_patch`` merges its data over whatever ``user_show``
    returns, and ``user_show`` strips the email address unless the caller is
    that same user or a sysadmin -- so the merged dictionary reaches
    ``user_update`` with no email and fails its ``not_empty`` validator. Naming
    the fields here makes the call work regardless of who is asking, which
    matters because internal callers arrive as ``127.0.0.1``.

    **The relaxed ``name`` validation is what makes this work on the real
    data.** Accounts here are created by ``ckanext-oauth2`` from Auth0 and are
    named after the person's email address -- ``someone@example.gov``. CKAN's
    ``name_validator`` accepts only ``[a-z0-9_-]``, so it rejects very nearly
    every account on the site, and it runs on *every* update: the merge above
    means ``name`` is always present whether or not it is passed here. Without
    the schema below, approving, rejecting or deactivating a real account fails
    with "Must be purely lowercase alphanumeric (ascii) characters and these
    symbols: -_" and nothing is written.

    That is CKAN's behavior on legacy data rather than anything this extension
    introduced -- ``user_patch`` fails identically when ``name`` is omitted and
    when ``ignore_auth`` is passed -- but it fails *here*, so it is fixed here.
    It went unnoticed because ``check_access`` runs before validation and
    ``ckanext-oauth2`` used to refuse ``user_update`` outright, which preempted
    it; and because nobody manages accounts on a site with one shared
    administrator, which is the pain point this task exists to remove.

    Only the format checks are dropped, and only for a field no caller here
    ever changes -- ``name`` is passed solely to survive the merge, always as
    the value already stored. Renaming a user still goes through stock
    ``user_update`` with stock validation. ``user_name_validator`` (uniqueness)
    goes too, for the same reason: a name being written back unchanged cannot
    collide with anything but itself.
    """
    fields.setdefault(u'name', user.name)
    fields.setdefault(u'email', user.email)
    fields[u'id'] = user.id

    schema = core_schema.default_update_user_schema()
    schema[u'name'] = [toolkit.get_validator(u'ignore_missing'),
                       toolkit.get_validator(u'unicode_safe')]

    toolkit.get_action(u'user_patch')(
        {u'user': context.get(u'user'),
         u'auth_user_obj': context.get(u'auth_user_obj'),
         u'ignore_auth': context.get(u'ignore_auth', False),
         u'schema': schema},
        fields)


# -- Records -----------------------------------------------------------------

def _iso(value):
    return value.isoformat() if value else None


def group_record(group):
    """A program or grant, as the modal and the user table need them."""
    record = {
        u'id': group.id,
        u'name': group.name,
        u'title': group.title,
    }
    if group.is_organization:
        record[u'program_id'] = roles.program_id_for_grant(group.id)
    return record


def programs():
    """Every active program, for the modal's checkbox list.

    Only programs. Production has three of them against roughly 570 grants, so
    grants cannot be served this way -- the Manage Roles modal uses
    ``organization_autocomplete`` for the Grant Editor case instead.
    """
    groups = model.Session.query(model.Group).filter(
        model.Group.is_organization.is_(False),
        model.Group.state == u'active').all()
    return [group_record(group)
            for group in sorted(groups, key=lambda g: g.title or g.name)]


def unassigned_grant_ids():
    """Ids of active grants that resolve to no program.

    The negative of ``roles._program_id_for_grant_id``, and deliberately the
    same join: an ``owner_group`` extra that is active, whose value names a
    group that is active and is not an organization. A grant fails it three
    ways -- no extra at all, an empty value, or a value naming something that
    is deleted or is itself a grant -- and all three mean the same thing to a
    program role, which is that it cannot reach this grant.

    One query rather than ``migration.orphan_grants``'s row-by-row loop,
    because this one serves a picker on a screen.
    """
    has_program = model.Session.query(model.GroupExtra.group_id).join(
        model.Group, model.Group.id == model.GroupExtra.value
    ).filter(
        model.GroupExtra.key == roles.OWNER_GROUP_EXTRA,
        model.GroupExtra.state == u'active',
        model.Group.state == u'active',
        model.Group.is_organization.is_(False),
    )
    rows = model.Session.query(model.Group.id).filter(
        model.Group.is_organization.is_(True),
        model.Group.state == u'active',
        ~model.Group.id.in_(has_program),
    ).all()
    return {row[0] for row in rows}


def search_grants(grant_ids, q=None):
    """Grant records for ``grant_ids``, optionally matching ``q``.

    Sorted by title so a picker reads alphabetically. Returns every match --
    the caller pages, the same arrangement as ``search_users`` and for the
    same reason: the set is already bounded by the caller's scope.
    """
    if not grant_ids:
        return []
    query = model.Session.query(model.Group).filter(
        model.Group.id.in_(list(grant_ids)),
        model.Group.state == u'active',
    )
    if q:
        pattern = u'%%%s%%' % q.strip().lower()
        query = query.filter(or_(
            func.lower(model.Group.title).like(pattern),
            func.lower(model.Group.name).like(pattern),
        ))
    return [group_record(group)
            for group in sorted(query.all(), key=lambda g: g.title or g.name)]


def _groups_by_id(group_ids):
    if not group_ids:
        return []
    groups = model.Session.query(model.Group).filter(
        model.Group.id.in_(list(group_ids))).all()
    return [group_record(group)
            for group in sorted(groups, key=lambda g: g.title or g.name)]


def user_record(user):
    """One row of the user-management table.

    A Platform Administrator's programs and grants are still reported, because
    they are retained rather than deleted -- ``assignments_in_effect`` on
    ``role_record`` is what tells the UI to render the cell blank.

    ``dual_scope`` says the account holds both a program and a grant
    assignment, which one-role-per-user forbids and most of the existing data
    does anyway. It is here because ``role`` alone is misleading for those
    accounts: ``user_role`` resolves by precedence, so one holding a program
    ``member`` row and a grant ``editor`` row reports as Program Reader/Member
    while holding a Grant Editor's write permissions. The table should say so
    rather than show a read-only label beside an account that can write.

    Pair it with ``role`` before warning: a Platform Administrator's
    assignments are retained but never consulted, so ``dual_scope`` may be true
    for them without meaning anything. Currently inert -- the only dual-scope
    sysadmin is a legacy shared account, which is deactivated and so outside
    the default list -- but one promotion puts a live account there. The row carries
    ``role``, which is enough to suppress it; ``assignments_in_effect`` on
    ``role_record`` answers the same question for the modal.

    **The flag is the common case, not the exception**, which matters more to
    whoever builds the table. 116 of 242 accounts hold both scopes: 114 report
    as Program Reader/Member and 2 as Program Administrator. One-role-per-user
    postdates the data, so the guards refuse new combinations while nothing
    rewrote the old ones, and ``migrate-roles`` lists every one as ``decide``.
    A badge on half the rows is noise; this probably wants a filter or a
    column rather than a warning icon.

    The migration report asks the same question through a second
    implementation -- see ``roles.holds_both_scopes`` for why they are separate
    and what pins them together.
    """
    role = roles.user_role(user)
    status = status_of(user)
    return {
        u'id': user.id,
        u'name': user.name,
        u'display_name': user.display_name,
        u'email': user.email,
        u'status': status,
        u'status_label': roles.status_label(status),
        u'last_login': _iso(user.last_active),
        u'role': role,
        u'role_label': roles.role_label(role),
        u'dual_scope': roles.holds_both_scopes(user),
        u'programs': _groups_by_id(roles.programs_for_user(user)),
        u'grants': _groups_by_id(roles.grants_for_user(user)),
    }


def role_record(user):
    """What the Manage Roles modal needs for one user.

    Carries ``dual_scope`` for the same reason ``user_record`` does, and it
    matters more here: the modal is where somebody resolves one. Saving
    replaces every assignment, so a modal that showed only the role name would
    silently drop the other half the moment anyone pressed Save.
    """
    role = roles.user_role(user)
    return {
        u'user_id': user.id,
        u'user_name': user.name,
        u'display_name': user.display_name,
        u'role': role,
        u'role_label': roles.role_label(role),
        u'dual_scope': roles.holds_both_scopes(user),
        u'programs': _groups_by_id(roles.programs_for_user(user)),
        u'grants': _groups_by_id(roles.grants_for_user(user)),
        u'assignments_in_effect': roles.assignments_in_effect(role),
    }


# -- Searching ---------------------------------------------------------------

def _escape_like(term):
    """Escape LIKE wildcards in a user-supplied search term.

    Without this a search for ``a_b`` also matches ``axb``, and a search
    containing ``%`` matches almost everything.
    """
    for char in (u'\\', u'%', u'_'):
        term = term.replace(char, u'\\' + char)
    return term


def search_users(q=None, statuses=None, role=None, program_id=None,
                 grant_id=None):
    """Every account matching the filters, as ``model.User`` rows, name order.

    Returns rows rather than records, and every match rather than one page,
    for two different reasons.

    *Every match*, because ``role`` and the deactivated/rejected split are both
    *derived* -- one from membership rows and the sysadmin flag, the other from
    ``plugin_extras`` -- so neither can be expressed as a SQL predicate without
    duplicating the resolution rules somewhere they could drift from these. The
    cheap filters run in SQL and the derived ones in Python, which means the
    total is only known after the derived ones have run.

    *Rows, not records*, because ``user_record`` costs two further queries per
    user to name their programs and grants. The caller pages this list and
    builds records for that page alone, so those queries are paid for the
    twenty rows returned rather than for every account on the site.

    The role filter is the one expensive derived filter -- it resolves
    memberships per candidate -- so it only runs when a role was actually
    asked for. Status is free: it reads the row already loaded.
    """
    statuses = statuses or roles.DEFAULT_VISIBLE_STATUSES
    wanted_states = {roles.STATUS_STORAGE[status][0] for status in statuses}

    query = model.Session.query(model.User).filter(
        model.User.state.in_(sorted(wanted_states)))

    if q:
        pattern = u'%{0}%'.format(_escape_like(q.strip()))
        query = query.filter(or_(
            model.User.name.ilike(pattern, escape=u'\\'),
            model.User.fullname.ilike(pattern, escape=u'\\'),
            model.User.email.ilike(pattern, escape=u'\\')))

    # Both references are resolved, and both filters apply. Neither of those
    # was true before: ``grant_id`` went into the query raw, so passing a
    # grant *name* silently matched nothing and reported the grant as empty,
    # and supplying both dropped the grant filter and returned the whole
    # program. An unresolvable reference now means no matches outright rather
    # than a ``group_id IS NULL`` comparison that quietly matches nothing.
    for reference, resolve in ((program_id, roles.program_id),
                               (grant_id, roles.grant_id)):
        if not reference:
            continue
        resolved = resolve(reference)
        if resolved is None:
            return []
        query = query.filter(model.User.id.in_(
            model.Session.query(model.Member.table_id).filter(
                model.Member.table_name == u'user',
                model.Member.state == u'active',
                model.Member.group_id == resolved)))

    users = query.order_by(model.User.name).all()

    users = [user for user in users if status_of(user) in statuses]
    if role:
        users = [user for user in users if roles.user_role(user) == role]
    return users
