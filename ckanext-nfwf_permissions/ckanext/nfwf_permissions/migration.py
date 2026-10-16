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

One row is nonetheless removed rather than kept, and it is the commonest of
all: the old **Program Member** role. It was handed out so that a dataset could
be filed under a program, back when a user's assignments were the only link
between a grant and its program; ``owner_group`` on the grant replaced that
mechanism. The product owner settled on 2026-10-02 that the existing rows do
not carry over. Program Reader itself survives -- it is still a program
``member`` row -- but it is assigned deliberately from here, to the people who
review a program's performance, rather than inherited from the stopgap.

What the data adds is where the volume sits:

* Most ``drop`` rows belong to a **handful of shared service accounts** -- the
  ones the redesign's pain points are about -- carrying retired grant ``admin``
  capacities, plus every legacy program membership. The service-account half is
  why the migration is low-risk: those accounts are already Platform
  Administrators, so removing the rows changes nothing they can do. It is a lot
  of rows either way, and ``--apply`` really does delete them.
* ``decide`` rows have one shape in practice: an account holding a Program
  **Administrator** row alongside a grant, which one-role-per-user does not
  allow. Two earlier sources of decisions have been settled and are rules now
  -- a program membership beside a grant (a grantee with both is simply a
  Grant Editor), and a retired grant capacity on a real person (removed; see
  ``DROP_RETIRED_GRANT_ROLE``).

  There is a second shape that no row in this database has: a capacity that
  is neither the one kept nor one of the two retired. It is reported and
  left alone rather than dropped, because every rule here is written for a
  capacity somebody chose, and a value nobody has seen is a question, not a
  row to delete under a reason that would not be true of it.

Run the command for the current numbers rather than trusting any figure written
down here.

Three dispositions, per assignment:

``keep``
    The row already expresses the right role. No write.
``drop``
    One of three. A retired capacity held by an account that is already a
    Platform Administrator -- safe because there is nothing to restore it
    *to*, the capacity no longer existing in the model. A legacy program
    membership, which the product owner decided does not carry over. Or a
    retired grant capacity on a real person, which she decided on 2026-10-13
    is removed rather than promoted.
``decide``
    A human has to choose. An account holding a Program Administrator row
    alongside a grant is the only shape left.

And one per *account*, because "needs a decision" is not a property of a single
row: an account administering a program while also editing a grant has to lose
one side under one-role-per-user, whatever each individual row says. An account
holding a program *membership* beside a grant used to be counted here too; now
that the membership is dropped outright, the rule settles it and nobody is
asked.
"""
from ckan import model

from ckanext.nfwf_permissions import roles

KEEP = u'keep'
DROP = u'drop'
DECIDE = u'decide'

#: Why a row is droppable, carried on the row because ``--apply`` has to tell
#: them apart, and because the report has to be able to say which rule took
#: a given person's access away.
#:
#: Only the first is re-checked at write time. It rests on the account still
#: being a Platform Administrator -- a person can sit on the confirmation
#: prompt, and a demotion in the meantime would change the answer. The other
#: two rest on settled decisions about the roles themselves and hold whoever
#: owns the account.
DROP_RETIRED_ON_ADMIN = u'retired-capacity-on-platform-admin'
DROP_LEGACY_MEMBERSHIP = u'legacy-program-membership'
DROP_RETIRED_GRANT_ROLE = u'retired-grant-role'

#: Column order for the CSV, so the report is diffable between runs.
ASSIGNMENT_FIELDS = [
    u'account', u'account_state', u'is_platform_admin', u'account_disposition',
    u'scope', u'group_name', u'group_title', u'capacity', u'proposed_role',
    u'disposition', u'drop_rule', u'note',
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
    """What becomes of one row: ``(proposed_role, disposition, note, rule)``.

    ``rule`` names the reason behind a ``drop`` and is ``None`` otherwise.
    ``--apply`` needs it: the three drop rules rest on different things and
    only one of them has to be re-checked at write time. See the ``DROP_*``
    constants.
    """
    if is_organization:
        if capacity == roles.CAPACITY_EDITOR:
            if sysadmin:
                return (roles.GRANT_EDITOR, KEEP,
                        u'retained but not consulted while the account is a '
                        u'Platform Administrator', None)
            return roles.GRANT_EDITOR, KEEP, u'', None
        if capacity not in roles.RETIRED_GRANT_CAPACITIES:
            # Not editor, and not one of the two retired capacities
            # either. The drop below is written for Grant Member and
            # Grant Admin and says so in its note; applying it to a
            # capacity nobody has seen would delete the row and
            # explain it with something untrue. `plan()` already
            # counts only RETIRED_GRANT_CAPACITIES as retired, so
            # without this the two disagree about what that means.
            # Reported instead, and left exactly as it is -- the
            # same answer the program branch below gives.
            return (None, DECIDE,
                    u'unexpected capacity on a grant: {0}'.format(
                        capacity),
                    None)
        # Grant admin and grant member are both retired.
        if sysadmin:
            return (None, DROP,
                    u'retired capacity, and the account is already a Platform '
                    u'Administrator, so there is nothing to restore it to',
                    DROP_RETIRED_ON_ADMIN)
        # Until 2026-10-13 this was a decision, on the grounds that the row
        # could become Grant Editor instead of nothing and only a person could
        # say which. That restraint did its job: it is why the eight accounts
        # holding these rows were put to the product owner at all, rather than
        # 61 rows of access disappearing unremarked, 49 of them one person's.
        # She answered for every one of them, and the answer was remove. So
        # the rule now says what the new model says, which is that the
        # capacity confers nothing because it does not exist.
        return (None, DROP,
                u'Grant Member and Grant Admin are not roles in the new '
                u'model; the product owner settled on 2026-10-13 that these '
                u'rows are removed rather than promoted to Grant Editor',
                DROP_RETIRED_GRANT_ROLE)

    if capacity == roles.CAPACITY_MEMBER:
        # Program membership was a stopgap. It was handed out so a dataset
        # could be filed under a program, back when a user assignment was the
        # only link between the two; `owner_group` on the grant replaced that
        # (see the module docstring). The product owner settled on 2026-10-02
        # that no existing row carries over.
        #
        # This is not the retirement of Program Reader. That role survives and
        # is still a program `member` row -- what ends is inheriting it from
        # the old data. It gets assigned deliberately from here, to the people
        # who review a program's performance.
        return (None, DROP,
                u'the old Program Member role was a stopgap and does not '
                u'carry over; Program Reader is assigned deliberately instead',
                DROP_LEGACY_MEMBERSHIP)

    if capacity == roles.CAPACITY_ADMIN:
        role = roles.PROGRAM_ADMIN
    else:
        return (None, DECIDE,
                u'unexpected capacity on a program: {0}'.format(capacity),
                None)

    if sysadmin:
        return (role, KEEP,
                u'retained but not consulted while the account is a Platform '
                u'Administrator', None)
    return role, KEEP, u'', None


def plan():
    """The whole migration report, as plain data.

    Returns a dict with ``assignments``, ``accounts``, ``orphan_grants`` and
    ``inactive_holders``, plus a ``totals`` summary.
    """
    rows = _assignment_rows()

    # Each row is judged before the accounts are, because whether
    # one-role-per-user has anything left to resolve is a question about the
    # rows that *survive*. A legacy program membership is dropped outright, so
    # it no longer puts its account in two scopes at once -- which is what
    # used to make the holder a decision for somebody.
    decided = [(row, _disposition(row[2], row[5], row[6])) for row in rows]

    scopes = {}
    retired = {}
    for row, (_role, disposition, _note, _rule) in decided:
        name, _state, _sysadmin, _gname, _gtitle, is_org, capacity = row
        held = scopes.setdefault(name, set())
        if disposition != DROP:
            held.add(u'grant' if is_org else u'program')
        if is_org and capacity in roles.RETIRED_GRANT_CAPACITIES:
            retired[name] = retired.get(name, 0) + 1

    accounts = _accounts(rows, scopes, retired)
    by_name = {account[u'account']: account for account in accounts}

    assignments = []
    for row, (role, disposition, note, rule) in decided:
        name, state, sysadmin, gname, gtitle, is_org, capacity = row
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
            u'drop_rule': rule or u'',
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
                u'holds a Program Administrator row and a grant assignment, '
                u'which one-role-per-user does not allow')
        elif not held:
            # Not a decision -- the rules settle it -- but worth saying out
            # loud, because an account that ends up holding nothing is easy to
            # create by accident and impossible to notice in a total. The
            # per-account count of retired rows is still reported, so the
            # report can still say who lost what; it is no longer a question.
            disposition, reason = KEEP, (
                u'every row it holds is dropped by the migration, so the '
                u'account is left with no role at all')
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
    """The rows ``--apply`` would remove.

    Three kinds, and deliberately the only things a write touches: retired
    grant capacities on accounts that are already Platform Administrators,
    the legacy program memberships, and retired grant capacities on real
    people. Every other disposition is either already correct in storage or
    waiting on a human.

    The first is a tidy-up and costs its holders nothing. The other two take
    something away from people who are using it -- the Program Affiliation
    box on the dataset form, and read access to a grant's private datasets --
    so both are decisions rather than tidy-ups, and both are recorded in the
    module docstring and the README.
    """
    return [row for row in plan_data[u'assignments']
            if row[u'disposition'] == DROP]
