# encoding: utf-8
"""Fixture data backing the stub actions.

Mirrors the table in the US 0117 / US 0126 mockups row for row, so the user
management screen and the Manage Roles modal can be built and eyeballed against
the same data the wireframes show.

Every id here is opaque and disposable -- do not hard-code one in the UI. They
are replaced by real CKAN ids when the actions start reading the database.
"""
import copy

from ckanext.nfwf_permissions import roles


# -- Programs (from the US 0126 modal mockup) ---------------------------------

_PROGRAMS = [
    {
        u'id': u'fixture-program-ncrf',
        u'name': u'national-coastal-resilience-fund',
        u'title': u'National Coastal Resilience Fund',
    },
    {
        u'id': u'fixture-program-ecrf',
        u'name': u'emergency-coastal-resilience-fund',
        u'title': u'Emergency Coastal Resilience Fund',
    },
    {
        u'id': u'fixture-program-hscr',
        u'name': u'hurricane-sandy-coastal-resiliency',
        u'title': u'Hurricane Sandy Coastal Resiliency',
    },
]

# -- Grants (titles as they appear in the mockup's Assigned Grants column) -----

_GRANTS = [
    {
        u'id': u'fixture-grant-66072',
        u'name': u'grant-66072-texas-general-land-office',
        u'title': u'Grant 66072 (Texas General Land Office)',
        u'program_id': u'fixture-program-ncrf',
    },
    {
        u'id': u'fixture-grant-66991',
        u'name': u'grant-66991-cape-fear-resource-conservation-development',
        u'title': u'Grant 66991 (Cape Fear Resource Conservation & Development)',
        u'program_id': u'fixture-program-ncrf',
    },
    {
        u'id': u'fixture-grant-66288',
        u'name': u'grant-66288-national-audubon-society-inc',
        u'title': u'Grant 66288 (National Audubon Society, Inc.)',
        u'program_id': u'fixture-program-ecrf',
    },
]

# -- Users --------------------------------------------------------------------
#
# ``last_login`` is ISO 8601 UTC. The mockup renders it as "5/21/2025 11:00 am";
# formatting is the UI's job, the API stays unambiguous.

_USERS = [
    {
        u'id': u'fixture-user-aquimby',
        u'name': u'aquimby',
        u'display_name': u'Allison Quimby',
        u'email': u'aboyer@wilmintonde.gov',
        u'status': roles.STATUS_NEEDS_REVIEW,
        u'last_login': None,
        u'role': None,
        u'programs': [],
        u'grants': [],
    },
    {
        u'id': u'fixture-user-akruger',
        u'name': u'akruger',
        u'display_name': u'Alex Kruger',
        u'email': u'akruger@indecon.com',
        u'status': roles.STATUS_DEACTIVATED,
        u'last_login': u'2025-05-21T11:00:00',
        u'role': None,
        u'programs': [],
        u'grants': [],
    },
    {
        u'id': u'fixture-user-emazur',
        u'name': u'emazur',
        u'display_name': u'Emily Mazur',
        u'email': u'emazur@indecon.com',
        u'status': roles.STATUS_ACTIVE,
        u'last_login': u'2026-04-21T12:00:00',
        u'role': roles.PLATFORM_ADMIN,
        u'programs': [],
        u'grants': [],
    },
    {
        u'id': u'fixture-user-rlittlewood',
        u'name': u'rlittlewood',
        u'display_name': u'Ryan Littlewood',
        u'email': u'Ryan.Littlewood@nfwf.org',
        u'status': roles.STATUS_ACTIVE,
        u'last_login': u'2026-01-01T09:00:00',
        u'role': roles.PROGRAM_ADMIN,
        u'programs': [u'fixture-program-ncrf'],
        u'grants': [],
    },
    {
        u'id': u'fixture-user-mflight',
        u'name': u'mflight',
        u'display_name': u'Maura Flight',
        u'email': u'mflight@indecon.com',
        u'status': roles.STATUS_ACTIVE,
        u'last_login': u'2023-06-01T16:00:00',
        u'role': roles.PROGRAM_READER,
        u'programs': [u'fixture-program-hscr'],
        u'grants': [],
    },
    {
        u'id': u'fixture-user-asunley',
        u'name': u'asunley',
        u'display_name': u'Angela Sunley',
        u'email': u'Angela.Sunley@glo.Texas.gov',
        u'status': roles.STATUS_ACTIVE,
        u'last_login': None,
        u'role': roles.GRANT_EDITOR,
        u'programs': [],
        u'grants': [u'fixture-grant-66072'],
    },
    {
        u'id': u'fixture-user-dyork',
        u'name': u'dyork',
        u'display_name': u'Dawn York',
        u'email': u'dyork5713@gmail.com',
        u'status': roles.STATUS_ACTIVE,
        u'last_login': u'2026-04-07T11:00:00',
        u'role': roles.GRANT_EDITOR,
        u'programs': [],
        u'grants': [u'fixture-grant-66991', u'fixture-grant-66288'],
    },
    {
        u'id': u'fixture-user-abc123',
        u'name': u'abc123',
        u'display_name': u'ABC123',
        u'email': u'email@email.com',
        u'status': roles.STATUS_REJECTED,
        u'last_login': None,
        u'role': None,
        u'programs': [],
        u'grants': [],
    },
]


def programs():
    """Every program, as the modal's checkbox list needs them."""
    return copy.deepcopy(_PROGRAMS)


def grants():
    """Every grant.

    Note for Task 126: production has ~570 grants, so the modal cannot render
    these as a checkbox list the way it does programs. See the README.
    """
    return copy.deepcopy(_GRANTS)


def programs_by_id(program_ids):
    """Expand a list of program ids into program dicts, preserving order."""
    return _expand(_PROGRAMS, program_ids)


def grants_by_id(grant_ids):
    """Expand a list of grant ids into grant dicts, preserving order."""
    return _expand(_GRANTS, grant_ids)


def users():
    """Every fixture user, with programs and grants already expanded."""
    expanded = []
    for user in copy.deepcopy(_USERS):
        user[u'programs'] = programs_by_id(user[u'programs'])
        user[u'grants'] = grants_by_id(user[u'grants'])
        user[u'role_label'] = roles.role_label(user[u'role'])
        user[u'status_label'] = roles.status_label(user[u'status'])
        user[u'stub'] = True
        expanded.append(user)
    return expanded


def user_by_id_or_name(id_or_name):
    """Return one fixture user, matched on id or name.

    Raises ``ObjectNotFound`` so callers see the same error they will see once
    these actions read the database.
    """
    # Imported here so this module stays importable without a CKAN app context.
    from ckan.plugins import toolkit

    for user in users():
        if id_or_name in (user[u'id'], user[u'name']):
            return user
    raise toolkit.ObjectNotFound(
        toolkit._(u'User not found: {0}').format(id_or_name))


def _expand(records, wanted_ids):
    by_id = {record[u'id']: record for record in records}
    found = []
    for wanted in wanted_ids or []:
        record = by_id.get(wanted)
        if record is not None:
            found.append(copy.deepcopy(record))
    return found
