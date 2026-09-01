# encoding: utf-8
"""Authorization for the NFWF user-management actions.

Platform Administrators are CKAN sysadmins, and CKAN grants sysadmins every
action *before* these functions are consulted -- see the sysadmin short-circuit
in ``ckan/authz.py``. So returning ``False`` unconditionally here means
"Platform Administrator only", without this extension needing to know anything
about sysadmins.

Do **not** decorate these with ``@toolkit.auth_sysadmins_check``. That
suppresses the short-circuit, so the function below would run for sysadmins too
and lock everybody out -- which is precisely the bug in ``ckanext-oauth2`` that
Task 125 has to fix before promote/demote and account approval can work at all.

TODO (Task 125, full permission matrix): US 0117 asks for Program Administrators
to see the users within their own program. That scoping belongs here, once the
role-resolution helpers land.
"""
from ckan.plugins import toolkit

__all__ = [
    u'nfwf_user_list',
    u'nfwf_user_role_show',
    u'nfwf_user_role_set',
    u'nfwf_user_approve',
    u'nfwf_user_reject',
    u'nfwf_user_deactivate',
    u'nfwf_role_options',
]


def _platform_admin_only(context, data_dict=None):
    return {
        u'success': False,
        u'msg': toolkit._(
            u'Only a Platform Administrator may manage user accounts and roles.'
        ),
    }


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
