# encoding: utf-8
"""Analyze existing role assignments against the new role model.

Produces the migration report the role redesign was deferred on: what the new
model makes of every assignment that already exists, and which ones a person
has to decide about rather than a rule.

Kept separate from ``cli.py`` so the analysis is testable without invoking a
command, and so nothing here can write: every function below only reads.

**The migration is low-risk but it is not small, and an earlier version of this
docstring got that backwards.** It claimed the migration "writes almost nothing"
and that "the vast majority of assignments need no change at all". Run against
the production data, only a small minority of rows are ``keep``; the other two
dispositions are the bulk of it. The claim was reasoning from the design rather
than from the data, which is how it survived.

The design half is true and is why the model was chosen: it maps onto capacities
CKAN already stores -- Grant Editor *is* a grant ``editor`` row, Program Reader
*is* a program ``member`` row, Program Administrator *is* a program ``admin``
row. No row has to be rewritten into a new shape.

What the data adds is where the volume actually sits, and the two halves have
very different weights:

* Most ``drop`` rows belong to a **handful of shared service accounts** -- the
  ones the redesign's pain points are about -- carrying retired grant ``admin``
  capacities. That is why the migration is low-risk: those accounts are already
  Platform Administrators, so removing the rows changes nothing they can do.
  It is still a lot of rows, and ``--apply`` really does delete them.
* Most ``decide`` rows belong to **accounts holding both a program and a grant
  assignment**, which one-role-per-user cannot resolve on its own. This is the
  real cost of the migration and it is measured in people, not rows: each one
  is somebody who has to be asked which side they keep.

Run the command for the current numbers rather than trusting any figure written
down here.

Three dispositions, per assignment:

``keep``
    The row already expresses the right role. No write.
``drop``
    A retired capacity held by an account that is already a Platform
    Administrator. Safe to remove because there is nothing to restore it *to*:
    the capacity no longer exists in the model, so retaining it -- which is the
    rule for live capacities -- would preserve nothing.
``decide``
    A human has to choose. A retired capacity on a real person, or an account
    holding assignments of both scopes at once.

And one per *account*, because "needs a decision" is not a property of a single
row: an account holding both a program membership and grant editorships has to
lose one side under one-role-per-user, no matter what each individual row says.
"""
from ckan import model

from ckanext.nfwf_permissions import roles

KEEP = u'keep'
DROP = u'drop'
DECIDE = u'decide'

#: Column order for the CSV, so the report is diffable between runs.
ASSIGNMENT_FIELDS = [
    u'account', u'account_state', u'is_platform_admin', u'account_disposition',
    u'scope', u'group_name', u'group_title', u'capacity', u'proposed_role',
    u'disposition', u'note',
]


def _assignment_rows():
    """Every active membership a user holds on an active group."""
    return model.Session.query(
        model.User.name, model.User.state, model.User.sysadmin,
        model.Group.name, model.Group.title, model.Group.is_organization,
        model.Member.capacity,
    ).join(
        model.Member, model.Member.table_id == model.User.id
    ).join(
        model.Group, model.Group.id == model.Member.group_id
    ).filter(
        model.Member.table_name == u'user',
        model.Member.state == u'active',
        model.Group.state == u'active',
    ).order_by(model.User.name, model.Group.name).all()


def _disposition(sysadmin, is_organization, capacity):
    """What becomes of one row: ``(proposed_role, disposition, note)``."""
    if is_organization:
        if capacity == roles.CAPACITY_EDITOR:
            if sysadmin:
                return (roles.GRANT_EDITOR, KEEP,
                        u'retained but not consulted while the account is a '
                        u'Platform Administrator')
            return roles.GRANT_EDITOR, KEEP, u''
        # Grant admin and grant member are both retired.
        if sysadmin:
            return (None, DROP,
                    u'retired capacity, and the account is already a Platform '
                    u'Administrator, so there is nothing to restore it to')
        return (None, DECIDE,
                u'retired capacity on a real account -- Grant Editor instead, '
                u'or remove?')

    if capacity == roles.CAPACITY_ADMIN:
        role = roles.PROGRAM_ADMIN
    elif capacity == roles.CAPACITY_MEMBER:
        role = roles.PROGRAM_READER
    else:
        return (None, DECIDE,
                u'unexpected capacity on a program: {0}'.format(capacity))

    if sysadmin:
        return (role, KEEP,
                u'retained but not consulted while the account is a Platform '
                u'Administrator')
    return role, KEEP, u''


def plan():
    """The whole migration report, as plain data.

    Returns a dict with ``assignments``, ``accounts``, ``orphan_grants`` and
    ``inactive_holders``, plus a ``totals`` summary.
    """
    rows = _assignment_rows()

    scopes = {}
    retired = {}
    for name, _state, _sysadmin, _gname, _gtitle, is_org, capacity in rows:
        scopes.setdefault(name, set()).add(
            u'grant' if is_org else u'program')
        if is_org and capacity in roles.RETIRED_GRANT_CAPACITIES:
            retired[name] = retired.get(name, 0) + 1

    accounts = _accounts(rows, scopes, retired)
    by_name = {account[u'account']: account for account in accounts}

    assignments = []
    for name, state, sysadmin, gname, gtitle, is_org, capacity in rows:
        role, disposition, note = _disposition(sysadmin, is_org, capacity)
        # An account-level decision overrides a row that looks fine on its own.
        account = by_name[name]
        if disposition == KEEP and account[u'disposition'] == DECIDE:
            disposition = DECIDE
            note = (note + u'; ' if note else u'') + account[u'reason']
        assignments.append({
            u'account': name,
            u'account_state': state,
            u'is_platform_admin': bool(sysadmin),
            u'account_disposition': account[u'disposition'],
            u'scope': u'grant' if is_org else u'program',
            u'group_name': gname,
            u'group_title': gtitle or u'',
            u'capacity': capacity,
            u'proposed_role': roles.role_label(role) or u'',
            u'disposition': disposition,
            u'note': note,
        })

    # Scanned once and passed down. `orphan_grants` asks
    # `program_id_for_grant` per grant, and `roles`' request cache is a no-op
    # on the CLI, so at roughly 570 grants each scan is over a thousand
    # queries -- there is no reason to pay for it twice.
    orphans = orphan_grants()

    return {
        u'assignments': assignments,
        u'accounts': accounts,
        u'orphan_grants': orphans,
        u'inactive_holders': [a for a in accounts
                              if a[u'account_state'] != u'active'],
        u'totals': _totals(assignments, accounts, orphans),
    }


def _accounts(rows, scopes, retired):
    """One summary per account, with the cost of each side of a decision."""
    seen = {}
    for name, state, sysadmin, _gname, _gtitle, _is_org, _capacity in rows:
        seen[name] = (state, sysadmin)

    summaries = []
    for name in sorted(seen):
        state, sysadmin = seen[name]
        held = scopes[name]
        dual = held == {u'grant', u'program'}
        retired_rows = retired.get(name, 0)

        programs = roles.programs_for_user(name)
        editable = roles.grants_for_user(name, [roles.CAPACITY_EDITOR])
        # What the program side is worth: every grant in those programs.
        visible = set()
        for program_id in programs:
            visible |= roles.grants_in_program(program_id)

        if sysadmin:
            disposition, reason = KEEP, (
                u'Platform Administrator; assignments retained but not '
                u'consulted')
        elif dual:
            disposition, reason = DECIDE, (
                u'holds both a program and a grant assignment, which '
                u'one-role-per-user does not allow')
        elif retired_rows:
            disposition, reason = DECIDE, (
                u'holds {0} row(s) with a retired grant capacity'.format(
                    retired_rows))
        else:
            disposition, reason = KEEP, u''

        summaries.append({
            u'account': name,
            u'account_state': state,
            u'is_platform_admin': bool(sysadmin),
            u'role_now': roles.role_label(roles.user_role(name)) or u'',
            u'programs_held': len(programs),
            u'grants_visible_via_programs': len(visible),
            u'grants_editable': len(editable),
            u'retired_rows': retired_rows,
            u'dual_scope': dual,
            u'disposition': disposition,
            u'reason': reason,
        })
    return summaries


def excluded_rows():
    """Active memberships on *deleted* groups, which the report leaves out.

    Counted and reported rather than silently dropped, because otherwise these
    numbers will not reconcile with a plain ``select count(*) from member`` and
    someone will lose an afternoon to the difference. They are mostly retired
    capacities held by the service accounts.

    They are excluded because they confer nothing -- the group is gone, so no
    role, no visibility, no edit rights -- and including them would inflate the
    decision counts with rows nobody needs to decide about.
    """
    return model.Session.query(model.Member).join(
        model.Group, model.Group.id == model.Member.group_id
    ).filter(
        model.Member.table_name == u'user',
        model.Member.state == u'active',
        model.Group.state != u'active',
    ).count()


def orphan_grants():
    """Active grants with no program, which no program role can reach.

    Both spellings count: no ``owner_group`` row at all, and the key present
    with an empty value -- in this data it is entirely the second kind.
    """
    grants = model.Session.query(model.Group.name, model.Group.title).filter(
        model.Group.is_organization.is_(True),
        model.Group.state == u'active').order_by(model.Group.name).all()
    orphans = []
    for name, title in grants:
        if roles.program_id_for_grant(name) is None:
            orphans.append({u'group_name': name, u'group_title': title or u''})
    return orphans


def _totals(assignments, accounts, orphans):
    def count(items, key, value):
        return len([item for item in items if item[key] == value])

    return {
        u'assignments': len(assignments),
        u'keep': count(assignments, u'disposition', KEEP),
        u'drop': count(assignments, u'disposition', DROP),
        u'decide': count(assignments, u'disposition', DECIDE),
        u'accounts': len(accounts),
        u'accounts_to_decide': count(accounts, u'disposition', DECIDE),
        u'dual_scope_accounts': len(
            [a for a in accounts if a[u'dual_scope'] and
             not a[u'is_platform_admin']]),
        u'orphan_grants': len(orphans),
        u'excluded_rows': excluded_rows(),
    }


def droppable(plan_data):
    """The rows ``--apply`` would remove: retired capacities on sysadmins.

    Deliberately the *only* thing a write touches. Every other disposition is
    either already correct in storage or waiting on a human.
    """
    return [row for row in plan_data[u'assignments']
            if row[u'disposition'] == DROP]
