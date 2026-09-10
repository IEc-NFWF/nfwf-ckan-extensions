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
  ``group_member_delete``, ``organization_member_delete`` and
  ``user_autocomplete`` -- all of these defer through ``authz.is_authorized``
  to ``package_update``, ``member_create`` or ``user_list``, so they inherit
  the overrides here instead of needing their own.
* ``user_delete`` -- already ``{'success': False}``, i.e. sysadmin-only.
* ``user_update`` -- **owned by ``ckanext-oauth2``**, which already implements
  exactly this policy (sysadmins allowed, everyone else refused). CKAN raises
  at startup if two plugins register the same non-chained auth function
  (``ckan/authz.py:100-110``), so registering it here would stop the site
  booting. The same goes for ``user_create``, ``user_reset`` and
  ``request_reset``, which that extension also claims.

Rejecting a *retired* capacity is not done here. ``member_create`` speaks in
``capacity`` and ``organization_member_create`` in ``role``, so one check over
validated action data is easier to keep honest than two over raw input -- it
lives in the chained membership actions instead.
"""
from ckan.logic import auth as core
from ckan.logic.auth import create as core_create
from ckan.logic.auth import delete as core_delete
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
    u'nfwf_role_options',
    # Core CKAN actions this extension takes over.
    u'package_create',
    u'package_update',
    u'organization_create',
    u'organization_update',
    u'organization_delete',
    u'member_create',
    u'organization_member_create',
    u'dataset_purge',
    u'user_list',
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
# of the short-circuit described above. The user-management screen also wants
# Program Administrators to see the users within their own program; that is a
# *filtered* list, so it belongs inside ``nfwf_user_list`` where a filter can
# be applied, not here where the only answers are all or nothing.

def _platform_admin_only(context, data_dict=None):
    return _denied(toolkit._(
        u'Only a Platform Administrator may manage user accounts and roles.'))


def nfwf_user_list(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_user_role_show(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_user_role_set(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_user_approve(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_user_reject(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_user_deactivate(context, data_dict=None):
    return _platform_admin_only(context, data_dict)


def nfwf_role_options(context, data_dict=None):
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
    """
    owner_org = (data_dict or {}).get(u'owner_org')
    if owner_org and roles.is_program_admin_for_grant(
            _caller(context), owner_org):
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
    ``user_autocomplete`` defers here too, so it is covered.
    """
    return _denied(toolkit._(
        u'Only a Platform Administrator may list user accounts.'))


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
