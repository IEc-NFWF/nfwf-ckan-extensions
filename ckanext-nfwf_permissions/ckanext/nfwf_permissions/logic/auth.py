# encoding: utf-8
"""Authorization for NFWF roles -- the permission matrix.

Three layers answer every question, in this order.

**1. Platform Administrators never reach this file.** CKAN grants sysadmins
every action before an auth function is consulted (``ckan/authz.py:218-223``),
so nothing here needs to mention them. The corollary is that none of these
functions may be decorated with ``@toolkit.auth_sysadmins_check``, which
*suppresses* that short-circuit. That decorator was why ``ckanext-oauth2``
locked even sysadmins out of editing a user record, which had to be fixed
before promoting a Platform Administrator could work at all.

**2. Program Administrators are what these overrides exist for.** They hold no
membership row on the grants they administer: a grant points at its program
through the ``owner_group`` extra, which is not a CKAN group hierarchy, so none
of CKAN's native permission cascading
(``ckan.auth.roles_that_cascade_to_sub_groups``) reaches it. Every override
below has the same shape -- ask ``roles`` whether the caller administers this
thing's program, allow if so.

**3. Everyone else falls through to stock CKAN**, called directly. Grant
Editors are ordinary organization ``editor``s and stock CKAN already gets them
right, so this file adds nothing for them and cannot accidentally take a
permission away.

``member_create`` is the one place that inverts layer 3 and *denies* what stock
CKAN would allow. See its docstring.

What is deliberately **not** overridden, because stock already gives the right
answer -- each of these is a decision, not an oversight:

* ``group_create`` / ``group_delete`` -- ``user_create_groups`` and
  ``user_delete_groups`` are both false, so they are already sysadmin-only.
* ``group_update`` -- a Program Administrator holds capacity ``admin`` on their
  own program, and ``admin`` satisfies every permission check
  (``ckan/authz.py:355-358``), so stock allows exactly them. A Program Reader's
  ``member`` capacity does not carry ``update``.
* ``group_member_create`` -- needs ``membership``, which ``admin`` has and
  ``member`` does not, so stock already lets a Program Administrator add
  Program Readers to their own program and nobody else.
* ``package_delete``, every ``resource_*``, ``member_delete``,
  ``group_member_delete`` and ``organization_member_delete`` -- all of these
  defer through ``authz.is_authorized`` to ``package_update`` or
  ``member_create``, so they inherit the overrides here instead of needing
  their own.
* ``user_delete`` -- already ``{'success': False}``, i.e. sysadmin-only.
* ``user_update`` -- **owned by ``ckanext-oauth2``**, which already implements
  exactly this policy: sysadmins allowed, everyone else refused
  (``ckanext-oauth2/ckanext/oauth2/plugin.py:48-65``). CKAN refuses a duplicate
  non-chained auth function (``ckan/authz.py:99-112``), so registering it here
  too would break authorization.

  ``user_create``, ``user_reset`` and ``request_reset`` are also claimed by
  that extension and so must also be left alone -- but only for the
  registration conflict, *not* because they share the policy. Those three
  refuse everyone, Platform Administrators included, each being an
  unconditional ``_no_permissions`` under ``@auth_sysadmins_check``. If a
  Platform Administrator ever reports being unable to drive a password reset,
  that is why, and it is oauth2's decision to revisit rather than something to
  look for here.

  Note the failure is not at boot, despite how it is often described: the
  registry is built lazily behind ``if not self._functions``
  (``ckan/authz.py:46-56``), so nothing assembles it until the first
  authorization check. A collision therefore surfaces on the first request
  that checks anything, not on startup -- which is a good deal harder to
  attribute, so do not rely on a clean boot as evidence that a new
  registration is safe.

Rejecting a *retired* capacity is not done here. ``member_create`` speaks in
``capacity`` and ``organization_member_create`` in ``role``, so one check over
validated action data is easier to keep honest than two over raw input -- it
lives in the chained membership actions instead.
"""
from ckan.logic import auth as core
from ckan.logic.auth import create as core_create
from ckan.logic.auth import delete as core_delete
from ckan.logic.auth import get as core_get
from ckan.logic.auth import update as core_update
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles

__all__ = [
    # The user-management API contract.
    u'nfwf_user_list',
    u'nfwf_user_role_show',
    u'nfwf_user_role_set',
    u'nfwf_user_approve',
    u'nfwf_user_reject',
    u'nfwf_user_deactivate',
    u'nfwf_user_reactivate',
    u'nfwf_role_options',
    u'nfwf_grant_list',
    # Core CKAN actions this extension takes over.
    u'package_create',
    u'package_update',
    u'organization_create',
    u'organization_update',
    u'organization_delete',
    u'member_create',
    u'organization_member_create',
    u'group_show',
    u'dataset_purge',
    u'user_list',
    u'user_autocomplete',
    u'user_show',
]


# -- Helpers -----------------------------------------------------------------

def _caller(context):
    """The acting user, preferring the object CKAN has already loaded.

    ``roles`` accepts a name, an id or a ``model.User``, so handing it
    ``auth_user_obj`` saves a lookup. Anonymous callers give ``''`` or
    ``None``, which every ``roles`` function reads as "holds nothing".
    """
    return context.get(u'auth_user_obj') or context.get(u'user')


def _allowed():
    """A fresh success result -- never a shared dict, callers may mutate it."""
    return {u'success': True}


def _denied(message):
    return {u'success': False, u'msg': message}


def _administers_a_program(context):
    """Is the caller the Program Administrator of anything at all?"""
    return bool(roles.programs_for_user(
        _caller(context), [roles.CAPACITY_ADMIN]))


# -- The user-management API contract ----------------------------------------
#
# Returning False unconditionally means "Platform Administrator only", by way
# of the short-circuit described above.
#
# The functions split into two groups, and the split is the document's, not a
# convenience. **Account lifecycle** -- approve, reject, deactivate -- is listed
# under Platform Administrator alone ("Approve new/remove user accounts") and
# stays closed, through ``_platform_admin_only``. **Role assignment** is listed
# under both, so the four actions the Manage Roles modal drives go through
# ``_role_management`` instead.
#
# Which group an action belongs to is the one thing to change if the document is
# read differently: move its name between the two blocks below. Nothing else
# needs to know.
#
# What they may then *see and change* is not decided here. An auth function's
# only answers are all or nothing, and the document's answer is "their own
# program", which is a filter -- so the scoping lives in the actions, where a
# filter can be expressed. Letting a caller in here is therefore only half of
# the rule; ``action._callers_scope`` is the other half, and neither is safe
# without the other.

def _platform_admin_only(context, data_dict=None):
    return _denied(toolkit._(
        u'Only a Platform Administrator may manage user accounts and roles.'))


def _role_management(context, data_dict=None):
    """Platform Administrators, plus Program Administrators within their own.

    See the note above for why "within their own" is not enforced here.
    """
    if _administers_a_program(context):
        return _allowed()
    return _denied(toolkit._(
        u'Only a Platform Administrator, or a Program Administrator within '
        u'their own program, may manage user roles.'))


def nfwf_user_list(context, data_dict=None):
    return _role_management(context, data_dict)


def nfwf_user_role_show(context, data_dict=None):
    return _role_management(context, data_dict)


def nfwf_user_role_set(context, data_dict=None):
    return _role_management(context, data_dict)


def nfwf_role_options(context, data_dict=None):
    return _role_management(context, data_dict)


def nfwf_grant_list(context, data_dict=None):
    return _role_management(context, data_dict)


def nfwf_user_approve(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_user_reject(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_user_deactivate(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_user_reactivate(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


# -- Datasets and resources --------------------------------------------------

@toolkit.auth_allow_anonymous_access
def package_create(context, data_dict=None):
    """A Program Administrator may create datasets in their program's grants.

    Stock CKAN refuses them twice over: ``has_user_permission_for_some_org``
    finds no *organization* row for them (it filters on
    ``is_organization``, so their program rows do not count), and the
    ``owner_org`` check finds no row on the target grant either.

    Carries ``auth_allow_anonymous_access`` because the core function does.
    Dropping it would deny anonymous callers a step earlier with a different
    message; keeping it means stock still decides their case.

    **This is asked in two shapes and both have to work.** The form path asks
    it with no ``data_dict`` at all -- ``CreateView._prepare``
    (``ckan/views/dataset.py:516-527``) calls ``check_access('package_create',
    context)`` bare, and aborts 403 if it fails -- so there is no
    ``owner_org`` yet to check a grant against. Answering only the second
    shape meant a Program Administrator was refused before ever reaching the
    form where they would have chosen the grant, which made the override
    unreachable through the UI and left it working for API callers only.

    So with no ``owner_org``, the question is the general one -- may this
    caller create datasets anywhere? -- and administering any program answers
    it. The per-grant check still happens on the way in, because the create
    itself carries ``owner_org`` and comes back through here.
    """
    caller = _caller(context)
    owner_org = (data_dict or {}).get(u'owner_org')

    if owner_org:
        if roles.is_program_admin_for_grant(caller, owner_org):
            return _allowed()
    elif _administers_a_program(context):
        return _allowed()

    return core_create.package_create(context, data_dict)


@toolkit.auth_allow_anonymous_access
def package_update(context, data_dict=None):
    """A Program Administrator may edit any dataset in their program's grants.

    This is the busiest override in the file. ``package_delete`` and every
    ``resource_create`` / ``_update`` / ``_delete`` / ``resource_view_*``
    action defers here through ``authz.is_authorized``, so they all inherit
    this answer and need no override of their own.
    """
    package = core.get_package_object(context, data_dict)
    if package.owner_org and roles.is_program_admin_for_grant(
            _caller(context), package.owner_org):
        return _allowed()
    return core_update.package_update(context, data_dict)


def dataset_purge(context, data_dict=None):
    """Platform Administrators anywhere, Program Administrators in-program.

    Stock is a flat ``{'success': False}``, so without this a Program
    Administrator could delete a dataset but never purge it.
    """
    package = core.get_package_object(context, data_dict)
    if package.owner_org and roles.is_program_admin_for_grant(
            _caller(context), package.owner_org):
        return _allowed()
    return core_delete.dataset_purge(context, data_dict)


# -- Grants (CKAN organizations) ---------------------------------------------

def organization_create(context, data_dict=None):
    """A Program Administrator may create a grant.

    *Which* program it is filed under is enforced by the chained
    ``organization_create`` action, not here. ``owner_group`` does reach this
    function -- ``nfwf_fields`` makes it a required field on the grant schema --
    but the same rule has to hold on **update**, or a Program Administrator
    could take a grant they legitimately hold and move it into someone else's
    program. ``organization_patch`` also merges onto the stored record before
    calling ``organization_update``, so only the action layer sees the
    effective value. One check covering create, update and patch beats three
    that can drift.
    """
    if _administers_a_program(context):
        return _allowed()
    return core_create.organization_create(context, data_dict)


def organization_update(context, data_dict=None):
    """A Program Administrator may edit the grants in their program."""
    group = core.get_group_object(context, data_dict)
    if roles.is_program_admin_for_grant(_caller(context), group.id):
        return _allowed()
    return core_update.organization_update(context, data_dict)


def organization_delete(context, data_dict=None):
    """A Program Administrator may delete a grant in their program.

    Stock is gated on ``user_delete_organizations``, which is false here, so
    this is the only path that opens it to anyone but a sysadmin.
    """
    group = core.get_group_object(context, data_dict)
    if roles.is_program_admin_for_grant(_caller(context), group.id):
        return _allowed()
    return core_delete.organization_delete(context, data_dict)


# -- Membership --------------------------------------------------------------

def member_create(context, data_dict):
    """Who may change a program's or a grant's membership.

    Also covers removal: ``member_delete`` defers here, and
    ``group_member_delete`` / ``organization_member_delete`` return ``True``
    and let the ``member_delete`` *action* re-check
    (``ckan/logic/action/delete.py``), which lands back here.

    The two branches are not symmetrical.

    On a **grant**, the program's administrator may assign Grant Editors, and
    anyone else falls through to stock.

    On a **program**, this deliberately does *not* fall through. Stock asks for
    ``manage_group`` when the object is a dataset, and capacity ``member``
    carries ``manage_group`` (``ckan/authz.py:250-252``) -- so stock CKAN lets
    a Program Reader add and remove a program's datasets. That is not
    theoretical -- datasets really are members of program groups in this data,
    and Program Reader is the most populous role on the site. The role exists
    for outside contractors who are conflicted out of applying for grant
    funds; read-only is the entire point of it, so the program branch allows
    only its own Program Administrator.
    """
    group = core.get_group_object(context, data_dict)
    caller = _caller(context)

    if group.is_organization:
        if roles.is_program_admin_for_grant(caller, group.id):
            return _allowed()
        return core_create.member_create(context, data_dict)

    if group.id in roles.programs_for_user(caller, [roles.CAPACITY_ADMIN]):
        return _allowed()
    return _denied(toolkit._(
        u"Only a Platform Administrator or this program's Program "
        u"Administrator may change what belongs to it."))


@toolkit.auth_allow_anonymous_access
def group_show(context, data_dict=None):
    """Let a Program Administrator see who is assigned to what.

    Narrow in intent, broad in reach, so read the whole of this before changing
    it. Stock ``group_show`` is permissive -- an active group is visible to
    anyone -- **except** when the caller asks about its users:

        if group.state == 'active':
            if config.get('ckan.auth.public_user_details') or \\
                (not asbool(data_dict.get('include_users', False)) and
                    (data_dict.get('object_type', None) != 'user')):
                return {'success': True}
        authorized = authz.has_user_permission_for_group_or_org(
            group.id, user, 'read')

    ``member_list`` calls it with ``object_type='user'``
    (``ckan/logic/action/get.py:178``), which skips that early return and falls
    through to a membership check -- and a Program Administrator holds no row on
    the grants they administer, by design. ``public_user_details`` is ``False``
    here, so nothing rescues it.

    The symptom, found by rendering the pages rather than by reading: a Program
    Administrator got **403 on a grant's Members tab while the Add Member page
    beside it returned 200**. They could assign a Grant Editor but not see who
    was already assigned, which is not a coherent version of the document's
    "assign user permissions for their program-associated grants".

    Only the grant branch is new. A program's Members tab already worked,
    because they *do* hold an ``admin`` row on the program itself and the
    membership check passes -- so this deliberately does not touch that path.

    This only ever *adds* permission; every caller it does not recognize falls
    through to stock. ``organization_show`` defers here
    (``ckan/logic/auth/get.py:174-175``), so the same widening applies to it,
    which is intended: the two describe the same object.

    Carries ``auth_allow_anonymous_access`` because the core function does.
    Without it CKAN refuses anonymous callers before this body runs, so a
    logged-out visitor could open no grant or program page at all -- and
    every dataset page in a grant broke too, since its sidebar looks the
    grant up.
    """
    group = core.get_group_object(context, data_dict)
    caller = _caller(context)

    if group.is_organization:
        if roles.is_program_admin_for_grant(caller, group.id):
            return _allowed()
    elif group.id in roles.programs_for_user(caller, [roles.CAPACITY_ADMIN]):
        return _allowed()

    return core_get.group_show(context, data_dict)


def organization_member_create(context, data_dict):
    """A Program Administrator may add members to grants in their program.

    Stock wants the ``membership`` permission on the grant, which only a row on
    that grant confers.
    """
    if roles.is_program_admin_for_grant(
            _caller(context), (data_dict or {}).get(u'id')):
        return _allowed()
    return core_create.organization_member_create(context, data_dict)


# -- User records ------------------------------------------------------------

def user_list(context, data_dict=None):
    """Platform Administrators only.

    Stock CKAN lets *any* logged-in user list every account on the site --
    ``restrict_anon`` is the only gate once ``public_user_details`` is false.
    Closing that off is what this one function does, because
    ``ckan/views/user.py`` gates the ``/user/`` page on exactly this check.

    ``user_autocomplete`` used to be covered by this too, since stock defers to
    it. That turned out to take the member screens down with it -- see below.
    """
    return _denied(toolkit._(
        u'Only a Platform Administrator may list user accounts.'))


def user_autocomplete(context, data_dict=None):
    """Platform Administrators, and Program Administrators.

    Stock defers to ``user_list`` (``ckan/logic/auth/get.py:214-215``), which
    the override above refuses outright -- and that took the *only* user picker
    on both member screens with it. A Program Administrator may add Grant
    Editors to the grants in their program and Program Readers to the program
    itself, and each of those templates sources its lookup from
    ``/api/2/util/user/autocomplete``, so without this they hold a permission
    they can never exercise. To add someone you have to be able to find them,
    and the people worth finding are the ones not already assigned, which is
    why scoping the lookup to the caller's own program would not have helped.

    Opening the lookup without opening the list is the point of splitting them.
    ``user_list`` returns whole user records; this returns ``id``, ``name`` and
    ``fullname`` only (``ckan/logic/action/get.py:1630``), matches on name and
    full name -- email matching is already restricted to sysadmins in
    ``model.User.search`` (``ckan/model/user.py:310-313``) -- and excludes
    deleted accounts, so deactivated and rejected ones stay hidden.

    Program Readers and Grant Editors get nothing here. Neither may add anyone
    to anything, so neither has a reason to look a person up, and Program
    Reader is the role the conflict-of-interest rules are written about.
    """
    if _administers_a_program(context):
        return _allowed()
    return _denied(toolkit._(
        u'Only a Platform Administrator or a Program Administrator may look '
        u'up user accounts.'))


def user_show(context, data_dict=None):
    """Yourself, or a Platform Administrator.

    Stock lets any logged-in user read any account. The reference is compared
    against both the caller's id and name without a lookup, since ``id`` may be
    either. A missing ``id`` means "the logged-in user" per the action's own
    contract, so it can only ever resolve to the caller.
    """
    caller = context.get(u'auth_user_obj')
    if caller is None:
        return _denied(toolkit._(u'You must be logged in to view an account.'))

    requested = (data_dict or {}).get(u'id')
    if not requested or requested in (caller.id, caller.name):
        return _allowed()
    return _denied(toolkit._(
        u"Only a Platform Administrator may view another user's account."))
