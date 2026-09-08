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
from sqlalchemy import or_

from ckan import model
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
    bookkeeping runs. Both ``state`` and ``plugin_extras`` are sysadmin-only
    fields on the user schema (``ckan/logic/schema.py:478`` and
    ``logic/action/update.py:834-838``), which is fine because every caller here
    is a Platform Administrator -- and is the reason the ``ckanext-oauth2``
    ``user_update`` block had to be lifted first (item 9).
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
    """
    fields.setdefault(u'name', user.name)
    fields.setdefault(u'email', user.email)
    fields[u'id'] = user.id

    toolkit.get_action(u'user_patch')(
        {u'user': context.get(u'user'),
         u'auth_user_obj': context.get(u'auth_user_obj'),
         u'ignore_auth': context.get(u'ignore_auth', False)},
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
    grants cannot be served this way -- Task 126 uses
    ``organization_autocomplete`` for the Grant Editor case.
    """
    groups = model.Session.query(model.Group).filter(
        model.Group.is_organization.is_(False),
        model.Group.state == u'active').all()
    return [group_record(group)
            for group in sorted(groups, key=lambda g: g.title or g.name)]


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
        u'programs': _groups_by_id(roles.programs_for_user(user)),
        u'grants': _groups_by_id(roles.grants_for_user(user)),
    }


def role_record(user):
    """What the Manage Roles modal needs for one user."""
    role = roles.user_role(user)
    return {
        u'user_id': user.id,
        u'user_name': user.name,
        u'display_name': user.display_name,
        u'role': role,
        u'role_label': roles.role_label(role),
        u'programs': _groups_by_id(roles.programs_for_user(user)),
        u'grants': _groups_by_id(roles.grants_for_user(user)),
        u'assignments_in_effect': roles.assignments_in_effect(role),
    }


# -- Searching ---------------------------------------------------------------

def search_users(q=None, statuses=None, role=None, program_id=None,
                 grant_id=None):
    """Every account matching the filters, as records, newest name order.

    Returns the full match list; the action pages it. Doing so is deliberate:
    ``role`` and the deactivated/rejected split are both *derived* -- one from
    membership rows and the sysadmin flag, the other from ``plugin_extras`` --
    so neither can be expressed as a SQL predicate without duplicating the
    resolution rules in a second place where they could drift. The cheap
    filters run in SQL and the derived ones in Python. Production holds 244
    accounts, so the difference is not measurable.
    """
    statuses = statuses or roles.DEFAULT_VISIBLE_STATUSES
    wanted_states = {roles.STATUS_STORAGE[status][0] for status in statuses}

    query = model.Session.query(model.User).filter(
        model.User.state.in_(sorted(wanted_states)))

    if q:
        pattern = u'%{0}%'.format(q.strip())
        query = query.filter(or_(
            model.User.name.ilike(pattern),
            model.User.fullname.ilike(pattern),
            model.User.email.ilike(pattern)))

    if program_id or grant_id:
        wanted = roles.program_id(program_id) if program_id else grant_id
        query = query.filter(model.User.id.in_(
            model.Session.query(model.Member.table_id).filter(
                model.Member.table_name == u'user',
                model.Member.state == u'active',
                model.Member.group_id == wanted)))

    records = [user_record(user) for user
               in query.order_by(model.User.name).all()]

    # Derived filters, applied after the record is built so there is exactly
    # one implementation of each rule.
    records = [record for record in records if record[u'status'] in statuses]
    if role:
        records = [record for record in records if record[u'role'] == role]
    return records
