# encoding: utf-8
"""Vocabulary for the NFWF role and account-status model.

Single source of truth for the four roles defined in "Open Data Platform User
Roles and Permissions Redesign" and the four account statuses shown in the
US 0117 mockups. Deliberately free of CKAN imports so it can be used from
actions, auth functions, templates and the migration command without import
cycles.
"""

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

#: Capacities on a *grant* that the redesign retires. Kept here so the chained
#: membership actions and the migration command agree on what to reject.
RETIRED_GRANT_CAPACITIES = [u'member', u'admin']

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
