# encoding: utf-8
"""Validation schemas for the ``nfwf_user_*`` actions.

These are the machine-readable half of the contract: they state exactly what
each action accepts, and they reject anything else with a per-field error
message rather than a 500. Core validators are resolved inside each function
rather than at import time so the plugin does not depend on validator
registration order.
"""
from ckan.plugins import toolkit

from ckanext.nfwf_permissions import roles
from ckanext.nfwf_permissions.logic import validators


def nfwf_user_list_schema():
    """Schema for ``nfwf_user_list``."""
    ignore_missing = toolkit.get_validator(u'ignore_missing')
    unicode_safe = toolkit.get_validator(u'unicode_safe')
    natural_number = toolkit.get_validator(u'natural_number_validator')
    one_of = toolkit.get_validator(u'one_of')

    return {
        u'q': [ignore_missing, unicode_safe],
        u'statuses': [ignore_missing, validators.nfwf_status_list],
        u'role': [ignore_missing, unicode_safe, one_of(roles.ROLES)],
        u'program_id': [ignore_missing, unicode_safe],
        u'grant_id': [ignore_missing, unicode_safe],
        u'limit': [ignore_missing, natural_number],
        u'offset': [ignore_missing, natural_number],
    }


def nfwf_user_id_schema():
    """Schema for the actions that take nothing but a user id."""
    not_empty = toolkit.get_validator(u'not_empty')
    unicode_safe = toolkit.get_validator(u'unicode_safe')

    return {
        u'id': [not_empty, unicode_safe],
    }


def nfwf_user_role_set_schema():
    """Schema for ``nfwf_user_role_set``.

    ``role`` is a single value, not a list -- a user holds exactly one role.
    Which of ``program_ids`` / ``grant_ids`` is expected depends on the role;
    that cross-field rule lives in the action, since a schema cannot express it.
    """
    not_empty = toolkit.get_validator(u'not_empty')
    ignore_missing = toolkit.get_validator(u'ignore_missing')
    unicode_safe = toolkit.get_validator(u'unicode_safe')

    return {
        u'id': [not_empty, unicode_safe],
        u'role': [not_empty, unicode_safe, validators.nfwf_role],
        u'program_ids': [ignore_missing, validators.nfwf_id_list],
        u'grant_ids': [ignore_missing, validators.nfwf_id_list],
    }
