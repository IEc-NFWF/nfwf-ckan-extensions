# encoding: utf-8
"""Validators for the NFWF role contract.

Registered by name through ``toolkit.blanket.validators``, so they are also
available to form schemas later on.
"""
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles

__all__ = [u'nfwf_id_list', u'nfwf_status_list', u'nfwf_role']


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
