# encoding: utf-8
"""NFWF roles and permissions -- Task 125.

What this plugin now provides:

* the ``nfwf_user_*`` API contract Tasks 117 and 126 build against -- still
  stubbed bodies, real authorization and validation
* the permission matrix in ``logic/auth.py``, which is what lets a Program
  Administrator reach the grants in their program
* chained ``organization_create`` / ``organization_update`` enforcing that a
  grant belongs to a program the caller administers
* ``IPermissionLabels`` in ``labels.py`` for program-wide visibility of private
  datasets
* chained membership actions rejecting the retired grant capacities and
  enforcing one role per user
* ``ckan nfwf-permissions migrate-roles``, the Q3 migration report

This lives in its own extension rather than in ``ckanext-nfwf_fields`` because
authorization is a separate concern from field and facet logic, and separate
files mean effectively no merge conflicts with Tasks 117/126.
"""
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from ckanext.nfwf_permissions.labels import NfwfPermissionLabels


@toolkit.blanket.actions
@toolkit.blanket.auth_functions
@toolkit.blanket.validators
@toolkit.blanket.cli
class NfwfPermissionsPlugin(plugins.SingletonPlugin, NfwfPermissionLabels):
    """Registers the actions, auth functions, validators, CLI and labels.

    The blanket decorators pick the first four up automatically from
    ``logic/action.py``, ``logic/auth.py``, ``logic/validators.py`` and
    ``cli.py``, using the ``__all__`` declared in each.

    ``IPermissionLabels`` is different: ``get_permission_labels`` returns the
    plugin *object itself* and calls the label methods on it, so the behaviour
    has to be inherited rather than registered. ``NfwfPermissionLabels`` keeps
    that logic in its own module and testable on its own.
    """
    plugins.implements(plugins.IPermissionLabels)
