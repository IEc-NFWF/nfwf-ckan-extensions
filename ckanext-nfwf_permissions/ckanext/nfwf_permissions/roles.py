# encoding: utf-8
"""Vocabulary for the NFWF role and account-status model.

Single source of truth for the four roles defined in "Open Data Platform User
Roles and Permissions Redesign" and the four account statuses shown in the
US 0117 mockups.

Two halves. The vocabulary at the top is plain data -- constants, labels and
the storage mapping -- and answers "what roles are there?". The resolution
functions at the bottom read the database and answer "what role does *this*
user hold, and over which grants?". They live together because the auth
functions, the permission labels, the ``nfwf_user_*`` actions and the migration
command all have to give the same answers, and splitting them across modules
would let them drift apart.
"""
import functools

import flask
from sqlalchemy import or_

from ckan import model

# -- Roles -------------------------------------------------------------------

PLATFORM_ADMIN = u'platform_admin'
PROGRAM_ADMIN = u'program_admin'
PROGRAM_READER = u'program_reader'
GRANT_EDITOR = u'grant_editor'

#: Every role, most privileged first.
ROLES = [PLATFORM_ADMIN, PROGRAM_ADMIN, PROGRAM_READER, GRANT_EDITOR]

#: Labels as written in the redesign document. The US 0117 mockup abbreviates
#: PROGRAM_READER to "Program Member" in the Role column; the document calls it
#: "Program Reader/Member". The document wins here.
ROLE_LABELS = {
    PLATFORM_ADMIN: u'Platform Administrator',
    PROGRAM_ADMIN: u'Program Administrator',
    PROGRAM_READER: u'Program Reader/Member',
    GRANT_EDITOR: u'Grant Editor',
}

#: What each role is assigned *to*. ``None`` means the role is site-wide and
#: takes no assignments at all.
ROLE_SCOPE = {
    PLATFORM_ADMIN: None,
    PROGRAM_ADMIN: u'program',
    PROGRAM_READER: u'program',
    GRANT_EDITOR: u'grant',
}

#: How each role is stored in CKAN, for reference. Platform Administrator is the
#: ``sysadmin`` flag on the user row -- CKAN's authorization short-circuits on
#: it, so it grants every action including ones added by future extensions. The
#: other three are ``member`` rows carrying a capacity.
ROLE_STORAGE = {
    PLATFORM_ADMIN: u'user.sysadmin = True',
    PROGRAM_ADMIN: u"member row, capacity 'admin', on the program group",
    PROGRAM_READER: u"member row, capacity 'member', on the program group",
    GRANT_EDITOR: u"member row, capacity 'editor', on the grant organization",
}

#: CKAN membership capacities, most privileged first. Role resolution walks
#: this order, so it decides which role wins when an account holds more than
#: one -- which the production data still does, pre-migration.
CAPACITY_ADMIN = u'admin'
CAPACITY_EDITOR = u'editor'
CAPACITY_MEMBER = u'member'
CAPACITY_ORDER = [CAPACITY_ADMIN, CAPACITY_EDITOR, CAPACITY_MEMBER]

#: Capacities on a *grant* that the redesign retires. Kept here so the chained
#: membership actions and the migration command agree on what to reject.
RETIRED_GRANT_CAPACITIES = [CAPACITY_MEMBER, CAPACITY_ADMIN]

#: The capacities each kind of group actually carries under the new model, which
#: is the positive statement of the same rule. A grant has one role on it; a
#: program has two.
GRANT_CAPACITIES = [CAPACITY_EDITOR]
PROGRAM_CAPACITIES = [CAPACITY_ADMIN, CAPACITY_MEMBER]

#: ``group_extra`` key on a grant organization naming the program it belongs
#: to. The value is the program group's id.
OWNER_GROUP_EXTRA = u'owner_group'


# -- Where this code interprets the redesign ---------------------------------
#
# A compliance pass on 2026-09-22 read "User Roles and Permissions
# Redesign.docx" and the estimates document, and found four requirements with
# no implementation behind them. Closing them meant answering questions the
# documents do not answer outright, so this is an index of every place the code
# decides what a sentence *means*. It is meant to be read when NFWF decides
# something different.
#
# Each entry is one short function or one list. Changing our reading of a
# sentence means rewriting that one body -- not threading a flag through, and
# not hunting for the other three places that had to agree with it. Where a
# rule is needed in more than one place, exactly one of these defines it and
# the callers ask; that is why the user list, the modal and the save cannot
# drift apart on what "their program" means.
#
#   Sentence being read                      Where it is decided
#   ---------------------------------------- ---------------------------------
#   "Assign user permissions for their       `auth._role_management`
#    program-associated grants/program        -- who reaches the role API
#    reader" (Program Administrator)
#
#   ...which roles that lets them hand out   `PROGRAM_ADMIN_ASSIGNABLE_ROLES`
#                                             below
#
#   "Platform Admin sees all; Program Admin  `administered_scope` and
#    sees their program" (estimates, 117)     `is_within_scope` below
#
#   A program carries Program Administrator  `PROGRAM_CAPACITIES` above, read
#   and Program Reader/Member                 by both
#                                             `_assert_membership_is_allowed`
#                                             and `member_roles_list`
#
#   "Add/edit/delete datasets ... under the  nothing -- stock CKAN already
#    grant" (Grant Editor)                    does this; guarded by a test
#
# Two of these readings are genuinely open, and both are recorded in the
# README's open questions rather than only here.

#: Which roles a Program Administrator may hand out.
#:
#: The document names two -- "their program-associated grants" (Grant Editor)
#: and "program reader" -- and is silent on whether they may appoint a *peer*
#: Program Administrator. OPEN: this takes the narrower reading and leaves it
#: out. Adding ``PROGRAM_ADMIN`` to this list is the whole change; the modal
#: narrows itself from it, and `nfwf_user_role_set` refuses from it.
#:
#: Platform Administrator is not listed and must never be: the document reserves
#: "Assign user permissions (including other Platform Administrators)" to
#: Platform Administrators.
PROGRAM_ADMIN_ASSIGNABLE_ROLES = [PROGRAM_READER, GRANT_EDITOR]

# A user holds exactly one role (confirmed 2026-08-19). Platform Administrator
# supersedes the others: it already implies everything a Grant Editor or Program
# Administrator can do, so a Platform Administrator's grant and program
# assignments are *retained but not consulted*. Removing the flag restores them.
SUPERSEDING_ROLE = PLATFORM_ADMIN


# -- Account statuses --------------------------------------------------------

STATUS_NEEDS_REVIEW = u'needs_review'
STATUS_ACTIVE = u'active'
STATUS_DEACTIVATED = u'deactivated'
STATUS_REJECTED = u'rejected'

STATUSES = [
    STATUS_NEEDS_REVIEW,
    STATUS_ACTIVE,
    STATUS_DEACTIVATED,
    STATUS_REJECTED,
]

STATUS_LABELS = {
    STATUS_NEEDS_REVIEW: u'Needs Review',
    STATUS_ACTIVE: u'Active',
    STATUS_DEACTIVATED: u'Deactivated',
    STATUS_REJECTED: u'Account request rejected',
}

#: Per US 0117 slide 4, the table hides deactivated and rejected accounts unless
#: the caller opts in via the two checkboxes.
DEFAULT_VISIBLE_STATUSES = [STATUS_NEEDS_REVIEW, STATUS_ACTIVE]

#: CKAN has three user states, and the mockup has four statuses, so the two
#: "gone" statuses share ``deleted`` and are told apart by ``plugin_extras``.
#: ``(user.state, plugin_extras['nfwf']['account_status'])``
STATUS_STORAGE = {
    STATUS_NEEDS_REVIEW: (u'pending', None),
    STATUS_ACTIVE: (u'active', None),
    STATUS_DEACTIVATED: (u'deleted', u'deactivated'),
    STATUS_REJECTED: (u'deleted', u'rejected'),
}

#: Key under ``user.plugin_extras`` where this extension keeps its own data.
PLUGIN_EXTRAS_KEY = u'nfwf'


# -- Helpers -----------------------------------------------------------------

def role_label(role):
    """Return the display label for ``role``, or ``None`` if it has no role."""
    if role is None:
        return None
    return ROLE_LABELS.get(role, role)


def status_label(status):
    """Return the display label for ``status``."""
    if status is None:
        return None
    return STATUS_LABELS.get(status, status)


def accepts_programs(role):
    """Is ``role`` assigned to one or more programs?"""
    return ROLE_SCOPE.get(role) == u'program'


def accepts_grants(role):
    """Is ``role`` assigned to one or more grants?"""
    return ROLE_SCOPE.get(role) == u'grant'


def assignments_in_effect(role):
    """Are a user's stored assignments actually consulted for ``role``?

    ``False`` for Platform Administrators, whose assignments are kept on the
    record but superseded by the sysadmin flag.
    """
    return role != SUPERSEDING_ROLE


# -- Request cache -----------------------------------------------------------

#: Attribute on Flask's request globals holding one request's cached answers.
_CACHE_ATTR = u'_nfwf_permissions_cache'


def _cache():
    """Return this request's cache dict, or ``None`` outside a request.

    Auth functions get asked the same few questions over and over -- once per
    dataset on a search page, and again for every button a template renders
    conditionally -- so without a cache a single page turns into hundreds of
    identical queries.

    The cache hangs off Flask's ``g``, which is torn down at the end of each
    request. It deliberately does *not* use the ``threading.local()`` pattern
    that ``ckanext-nfwf_fields`` uses for its facet flags: a thread-local
    outlives the request on a reused worker thread, so a role change would go
    on being ignored for the life of that thread. A stale facet flag renders a
    wrong page; a stale authorization answer keeps granting access that has
    been taken away, which is the one kind of wrong answer this module must
    never give.

    Outside a request -- the CLI, the test suite, background jobs -- there is
    nothing request-scoped to hang a cache on, so nothing is cached. Correct
    everywhere, fast on the path that needs it.
    """
    if not flask.has_request_context():
        return None
    store = getattr(flask.g, _CACHE_ATTR, None)
    if store is None:
        store = {}
        setattr(flask.g, _CACHE_ATTR, store)
    return store


def clear_cache():
    """Drop this request's cached answers.

    Call after changing a membership or the sysadmin flag in a request that
    goes on to ask about the same user again -- ``nfwf_user_role_set`` will.
    """
    if flask.has_request_context():
        setattr(flask.g, _CACHE_ATTR, None)


def _request_cached(func):
    """Memoize ``func`` for the duration of one request.

    Arguments have to be hashable and have to fully determine the answer, so
    callers resolve names to ids before crossing this boundary.
    """
    @functools.wraps(func)
    def wrapper(*args):
        cache = _cache()
        if cache is None:
            return func(*args)
        key = (func.__name__,) + args
        if key not in cache:
            cache[key] = func(*args)
        return cache[key]
    return wrapper


# -- Resolving references ----------------------------------------------------

@_request_cached
def _group_id(ref, is_organization):
    """Resolve a group name or id to an id, or ``None`` if there is no match.

    Auth functions get handed whatever the URL carried, which for
    ``/organization/edit/<x>`` is a name, while actions mostly carry ids, so
    both have to work. Deleted groups do not resolve: a Program Administrator
    falls through to stock CKAN for them, which means Platform Administrator
    only -- the safe direction.
    """
    if not ref:
        return None
    row = model.Session.query(model.Group.id).filter(
        or_(model.Group.id == ref, model.Group.name == ref),
        model.Group.state == u'active',
        model.Group.is_organization.is_(is_organization),
    ).first()
    return row[0] if row else None


@_request_cached
def _user_id_for_ref(ref):
    """Resolve a user name or id to an id, or ``None``."""
    user = model.User.get(ref)
    return user.id if user else None


def _user_id(user):
    """Resolve ``user`` -- a name, an id or a ``model.User`` -- to an id.

    Deliberately not filtered by state. Pending, deactivated and rejected
    accounts still have to report a role in the user-management screen.
    """
    if user is None:
        return None
    if isinstance(user, model.User):
        return user.id
    return _user_id_for_ref(user)


# -- Grants and programs -----------------------------------------------------

@_request_cached
def _program_id_for_grant_id(grant_id):
    # Joined to the program group and filtered on its state, matching
    # ``_group_id`` and ``_grants_in_program_id``. Without the join a deleted
    # program went on being reported as a grant's program: the grant vanished
    # from ``migration.orphan_grants`` (which tests this for ``None``, and a
    # dead id is not None), so ``migrate-roles`` reported no orphans for a site
    # that had them, while ``labels`` kept stamping ``program-<dead id>`` and
    # ``in-any-program`` on its private datasets -- leaving them readable by
    # every *other* program's administrator at the same moment the program's
    # own readers lost them, and with no program role able to administer the
    # grant at all.
    row = model.Session.query(model.GroupExtra.value).join(
        model.Group, model.Group.id == model.GroupExtra.value
    ).filter(
        model.GroupExtra.group_id == grant_id,
        model.GroupExtra.key == OWNER_GROUP_EXTRA,
        model.GroupExtra.state == u'active',
        model.Group.state == u'active',
        model.Group.is_organization.is_(False),
    ).first()
    if not row:
        return None
    # "No program" has more than one spelling: no ``owner_group`` row at all,
    # the key present with an empty value, and now also a value naming a group
    # that is deleted or is not a program. The join above accounts for all of
    # them by simply failing to match, which is why this is reached only with a
    # real, active program id -- ``or None`` is belt and braces now rather than
    # the thing doing the work, and is kept only so a future change to the
    # query cannot silently start returning ``''``.
    # `ckan nfwf-permissions migrate-roles` reports how many grants have none.
    return row[0] or None


def program_id_for_grant(grant):
    """Return the id of the program a grant belongs to, or ``None``.

    ``grant`` may be an organization id or name. This reads ``group_extra``
    directly rather than calling ``organization_show``, which is expensive and
    is itself chained -- and this runs inside auth functions.
    """
    grant_id = _group_id(grant, True)
    if grant_id is None:
        return None
    return _program_id_for_grant_id(grant_id)


@_request_cached
def _grants_in_program_id(program_id):
    rows = model.Session.query(model.GroupExtra.group_id).join(
        model.Group, model.Group.id == model.GroupExtra.group_id
    ).filter(
        model.GroupExtra.key == OWNER_GROUP_EXTRA,
        model.GroupExtra.value == program_id,
        model.GroupExtra.state == u'active',
        model.Group.state == u'active',
        model.Group.is_organization.is_(True),
    ).all()
    return frozenset(row[0] for row in rows)


def grants_in_program(program):
    """Ids of every active grant whose ``owner_group`` is ``program``.

    A ``frozenset``, because the result is cached and shared between callers
    and so must not be mutable -- and it can be large, since most of the site's
    grants belong to a single program.
    """
    program_id = _group_id(program, False)
    if program_id is None:
        return frozenset()
    return _grants_in_program_id(program_id)


def program_id(program):
    """Resolve a program reference -- an id or a name -- to an id, or ``None``.

    The public form of the lookup the functions above use internally. Anything
    comparing a *submitted* program against a user's own programs needs it,
    because a form or an API caller may send either kind of reference while
    ``programs_for_user`` deals only in ids. Returns ``None`` for an unknown
    reference, for a deleted program, and for an id that names a grant rather
    than a program -- so a caller can treat ``None`` as "not a program you can
    use".
    """
    return _group_id(program, False)


def grant_id(grant):
    """Resolve a grant reference -- an id or a name -- to an id, or ``None``.

    The organization-side twin of ``program_id``, and it exists for the same
    reason: a caller may send either kind of reference, while the membership
    queries deal only in ids. Returns ``None`` for an unknown reference, a
    deleted grant, and an id that names a program rather than a grant.
    """
    return _group_id(grant, True)


# -- Memberships -------------------------------------------------------------

def _capacity_rank(capacity):
    """Sort key for a capacity: lower is more privileged."""
    try:
        return CAPACITY_ORDER.index(capacity)
    except ValueError:
        return len(CAPACITY_ORDER)


@_request_cached
def _memberships(user_id, is_organization):
    """``((group_id, capacity), ...)`` for one user, sorted by group id.

    A tuple rather than a dict so the cached value cannot be corrupted by a
    caller. Memberships on deleted groups are left out, matching ``_group_id``.
    """
    rows = model.Session.query(
        model.Member.group_id, model.Member.capacity
    ).join(model.Group, model.Group.id == model.Member.group_id).filter(
        model.Member.table_name == u'user',
        model.Member.table_id == user_id,
        model.Member.state == u'active',
        model.Group.state == u'active',
        model.Group.is_organization.is_(is_organization),
    ).all()

    # One row per user per group is the intent, but nothing in the schema
    # enforces it. Keep the most privileged capacity so the answer is
    # deterministic whatever the data does.
    best = {}
    for group_id, capacity in rows:
        if group_id not in best or _capacity_rank(capacity) < _capacity_rank(
                best[group_id]):
            best[group_id] = capacity
    return tuple(sorted(best.items()))


def programs_for_user(user, capacities=None):
    """Program ids where ``user`` holds one of ``capacities``.

    ``capacities=None`` means any capacity.
    """
    user_id = _user_id(user)
    if user_id is None:
        return frozenset()
    return frozenset(
        group_id for group_id, capacity in _memberships(user_id, False)
        if capacities is None or capacity in capacities
    )


def grants_for_user(user, capacities=None):
    """Grant ids where ``user`` holds one of ``capacities``.

    ``capacities=None`` means any capacity, including the two the redesign
    retires -- the migration command has to see those to report on them.
    """
    user_id = _user_id(user)
    if user_id is None:
        return frozenset()
    return frozenset(
        group_id for group_id, capacity in _memberships(user_id, True)
        if capacities is None or capacity in capacities
    )


def holds_both_scopes(user):
    """Does ``user`` hold a program assignment *and* a grant assignment?

    The state one-role-per-user forbids, which most accounts were already in
    when the rule arrived -- the guards refuse new combinations but nothing
    rewrote the existing data, and ``ckan nfwf-permissions migrate-roles``
    reports how many are left.

    It matters to anything that *displays* a role, because ``user_role``
    resolves by precedence and so names only one of the two. An account holding
    a program ``member`` row and a grant ``editor`` row reports as Program
    Reader/Member -- the read-only role -- while holding a Grant Editor's write
    permissions. A screen showing the role alone understates what the account
    can do, which is the wrong direction for an administrative table to be
    wrong in.

    Raw, and deliberately the same question ``migration`` asks -- but by a
    second implementation, not a shared one. ``migration.plan`` builds its own
    ``scopes`` set from a bulk row scan, because it walks every account at once
    and a per-account call here would be N+1. Nothing structural keeps the two
    aligned; a capacity filter added to either drifts them apart in silence.
    ``TestDualScopeIsVisible`` runs both over the same population and compares
    them, which is what actually holds them together. Measured at 0
    disagreements across 180 production accounts on 2026-09-25.

    It says nothing about whether those assignments are *consulted*:
    a Platform Administrator's are retained and superseded, so pair this with
    ``role`` or ``assignments_in_effect`` before warning anybody.
    """
    return bool(programs_for_user(user)) and bool(grants_for_user(user))


def assignments_for_user(user, is_organization):
    """``((group_id, capacity), ...)`` -- what they hold, capacities included.

    The two functions above answer "which groups"; this answers "which groups,
    and as what", which is what anything restoring a previous state needs. The
    distinction is not academic: pre-migration accounts really do hold
    different capacities on different grants, so putting a single capacity back
    across all of them would quietly re-grade some of the rows it restored.
    """
    user_id = _user_id(user)
    if user_id is None:
        return ()
    return _memberships(user_id, is_organization)


# -- The role a user holds ---------------------------------------------------

@_request_cached
def _user_role(user_id):
    user = model.User.get(user_id)
    if user is None:
        return None
    if user.sysadmin:
        # Supersedes everything else. Any grant or program rows the account
        # still holds are retained but not consulted -- see
        # ``assignments_in_effect`` -- so demoting restores them.
        return PLATFORM_ADMIN
    program_capacities = {cap for _, cap in _memberships(user_id, False)}
    if CAPACITY_ADMIN in program_capacities:
        return PROGRAM_ADMIN
    if CAPACITY_MEMBER in program_capacities:
        return PROGRAM_READER
    grant_capacities = {cap for _, cap in _memberships(user_id, True)}
    if CAPACITY_EDITOR in grant_capacities:
        return GRANT_EDITOR
    return None


def user_role(user):
    """The single role ``user`` holds, or ``None`` if they hold none.

    One role per user is the rule (settled 2026-08-19) and
    ``nfwf_user_role_set`` enforces it on the way in, but the data predates the
    rule and is full of combinations -- most grant-``admin`` rows belong to
    accounts that are already sysadmins, and many accounts hold both a program
    and a grant assignment. So this resolves by precedence in ``ROLES`` order,
    most privileged wins, and keeps giving a deterministic answer until the
    migration has run.

    The retired grant capacities confer no role: an account whose only
    assignment is grant-``member`` resolves to ``None``, which is exactly what
    the migration report has to surface for a human decision.
    """
    user_id = _user_id(user)
    if user_id is None:
        return None
    return _user_role(user_id)


def administers_grants(user):
    """May ``user`` administer grants at all -- anywhere, in any program?

    True for Platform Administrators and Program Administrators, false for
    everyone else. Used for the questions that are about *capability in
    general* rather than about one particular grant: which fields a grant form
    requires, and whether to render an administrative field at all. When the
    question is "may they touch *this* grant", use
    ``is_program_admin_for_grant`` instead, or let the auth functions answer it.

    Deliberately expressed in terms of ``user_role`` rather than a fresh
    membership query, so it cannot disagree with the role a user is reported as
    holding.
    """
    return user_role(user) in (PLATFORM_ADMIN, PROGRAM_ADMIN)


def is_program_admin_for_grant(user, grant):
    """Does ``user`` administer the program that ``grant`` belongs to?

    Reports the stored assignment only, and does not consider the sysadmin
    flag. CKAN grants sysadmins every action before an auth function is
    reached, so no caller here needs to ask; and a Platform Administrator's
    retained program rows must not be read as an active Program Administrator
    role. A grant with no program is administered by nobody at this level.
    """
    program_id = program_id_for_grant(grant)
    if program_id is None:
        return False
    return program_id in programs_for_user(user, [CAPACITY_ADMIN])


# -- The reach of a Program Administrator ------------------------------------
#
# "Program Admin sees their program", written out. Two functions: what the
# scope *is*, and who falls inside it. The user list, the modal and the save
# all ask these rather than each working it out, so widening or narrowing the
# reach is an edit to one of these two bodies and nothing else needs to know.


def administered_scope(user):
    """The programs ``user`` administers and every grant filed under them.

    Returns ``(program_ids, grant_ids)`` as two sets, both empty for anyone who
    is not a Program Administrator.

    The sysadmin flag is deliberately not consulted, for the same reason
    ``is_program_admin_for_grant`` does not consult it: a Platform Administrator
    is answered by CKAN's short-circuit long before any of this runs, and their
    *retained* program rows must not be mistaken for an active assignment.
    Callers that need "sysadmins see everything" ask ``authz.is_sysadmin``
    themselves, where it is visible.
    """
    program_ids = set(programs_for_user(user, [CAPACITY_ADMIN]))
    grant_ids = set()
    for program in program_ids:
        grant_ids |= grants_in_program(program)
    return program_ids, grant_ids


def is_within_scope(subject, program_ids, grant_ids):
    """Is ``subject`` an account a holder of that scope may act on?

    Three rules, in the order they are written below.

    A **Platform Administrator** is never in scope. Their retained assignments
    may well fall inside it, and acting on one of those rows would let a Program
    Administrator demote the account that outranks them.

    An account with **no assignment at all** is in scope. OPEN: the literal
    reading of "sees their program" would exclude a fresh registration, but that
    leaves a Program Administrator unable to give anyone a first role, which is
    the thing the document asks them to do. To take the literal reading instead,
    delete the two lines marked below -- the last rule then answers it.

    Otherwise **every** assignment the subject holds has to fall inside the
    scope, not merely one of them. "Any" was tried first and was wrong twice
    over, which is worth recording because the data makes it the common case
    rather than an edge: the migration report shows most accounts currently hold
    both a program and a grant assignment.

    * It leaked. A Program Administrator of one program saw, in the account's
      record, the name of a grant belonging to a different program -- the exact
      cross-program visibility the scoping exists to prevent.
    * Worse, it made the Manage Roles modal a trap. The record populates it,
      ``nfwf_user_role_set`` replaces assignments wholesale, and it checks the
      submitted ids against this same scope -- so saving either failed with a
      refusal the caller could do nothing about, or, had the record been
      filtered to hide the other grant, would have silently deleted it.

    Requiring the whole account to sit inside the scope removes both. The cost
    is that a dual-scope account is invisible to a Program Administrator until
    somebody resolves it, which is the right answer: one-role-per-user says that
    account should not exist, and deciding which side it keeps is a Platform
    Administrator's call, not a side effect of someone else's edit.
    """
    if _is_sysadmin(subject):
        return False

    held_programs = set(programs_for_user(subject))
    held_grants = set(grants_for_user(subject))

    # Delete these two lines to exclude accounts that hold nothing yet.
    if not held_programs and not held_grants:
        return True

    return (held_programs <= set(program_ids)
            and held_grants <= set(grant_ids))


def _is_sysadmin(user):
    """``user.sysadmin``, for the several shapes callers pass around."""
    if isinstance(user, model.User):
        return bool(user.sysadmin)
    user_id = _user_id(user)
    if user_id is None:
        return False
    record = model.User.get(user_id)
    return bool(record and record.sysadmin)
