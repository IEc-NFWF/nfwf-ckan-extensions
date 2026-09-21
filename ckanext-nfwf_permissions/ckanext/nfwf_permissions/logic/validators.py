# encoding: utf-8
"""Validators for the NFWF role contract.

Registered by name through ``toolkit.blanket.validators``, so they are also
available to form schemas later on.
"""
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles

__all__ = [
    u'nfwf_id_list',
    u'nfwf_status_list',
    u'nfwf_role',
    u'platform_or_program_admin_not_empty',
    u'nfwf_owner_org_validator',
]


def nfwf_owner_org_validator(key, data, errors, context):
    """Core's ``owner_org_validator``, plus Program Administrators.

    Core requires a membership row on the target grant conferring
    ``create_dataset`` (``ckan/logic/validators.py:84-89``). A Program
    Administrator holds none -- that is the entire premise of this extension --
    so passing ``package_create``'s auth check bought them nothing: the action
    then died in *validation* with "You cannot add a dataset to this
    organization", and the role's headline capability did not work at all.
    Reproduced end to end before this validator existed.

    ``ignore_auth`` is injected into a **copy** of the context, and only for a
    caller who genuinely administers that grant's program. Inside core's
    validator that flag gates exactly one thing -- the membership check above --
    so nothing else it enforces is relaxed: the unowned-dataset rules, the
    collaborator branch and the group-exists check all still run, and the
    copy keeps the caller's real context untouched for everything downstream.
    """
    value = data.get(key)
    if value and not context.get(u'ignore_auth'):
        if roles.is_program_admin_for_grant(context.get(u'user'), value):
            context = dict(context, ignore_auth=True)
    return toolkit.get_validator(u'owner_org_validator')(
        key, data, errors, context)


def platform_or_program_admin_not_empty(key, data, errors, context):
    """Required for whoever may administer grants, ignored for everyone else.

    Replaces ``ckanext-nfwf_fields``' ``sysadmin_not_empty`` on the grant
    schema, so a Program Administrator faces the same required fields as a
    Platform Administrator now that they can edit grants at all.

    The shape -- required for one audience, ``ignore_missing`` for the rest --
    is not a nicety. The field it guards is only *rendered* for that same
    audience, so making it unconditionally required would leave everyone else
    unable to save a grant at all, with an error about a field their form never
    showed them. The template gate and this validator have to agree on who,
    which is why both go through ``roles.administers_grants``.

    Note what this deliberately is *not*: an override of the ``sysadmin`` auth
    function. That would be far too broad -- everything in CKAN gated on
    ``sysadmin`` would open up at once, when all that is wanted is one required
    field on one form.
    """
    if roles.administers_grants(context.get(u'user')):
        toolkit.get_validator(u'not_empty')(key, data, errors, context)
    else:
        toolkit.get_validator(u'ignore_missing')(key, data, errors, context)


def nfwf_id_list(value):
    """Coerce a list parameter into a clean, de-duplicated list of id strings.

    Accepts a real JSON list (the normal case for an API caller), a single
    string, or a comma-separated string, so form-encoded callers work too.
    CKAN's ``flatten_dict`` passes a list of strings through untouched, so this
    validator receives the whole list rather than one item at a time.
    """
    if value is None or value is toolkit.missing or value == u'':
        return []

    if isinstance(value, str):
        items = value.split(u',')
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise toolkit.Invalid(
            toolkit._(u'Expected a list of ids, got {0}').format(
                type(value).__name__))

    cleaned = []
    for item in items:
        if not isinstance(item, str):
            raise toolkit.Invalid(toolkit._(u'Ids must be strings'))
        item = item.strip()
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def nfwf_status_list(value):
    """Validate a list of account statuses against the known vocabulary."""
    statuses = nfwf_id_list(value)
    unknown = [status for status in statuses if status not in roles.STATUSES]
    if unknown:
        raise toolkit.Invalid(
            toolkit._(u'Unknown account status: {0}. Valid statuses are: {1}')
            .format(u', '.join(unknown), u', '.join(roles.STATUSES)))
    return statuses


def nfwf_role(value):
    """Validate a single role name against the known vocabulary."""
    if value not in roles.ROLES:
        raise toolkit.Invalid(
            toolkit._(u'Unknown role: {0}. Valid roles are: {1}').format(
                value, u', '.join(roles.ROLES)))
    return value
