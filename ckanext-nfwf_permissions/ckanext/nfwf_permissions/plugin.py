# encoding: utf-8
"""NFWF roles and permissions -- Task 125.

At this stage the plugin registers only the API contract that Tasks 117 and 126
build against, so the front-end work is not blocked on the backend. Still to
come, on top of this and without changing any signature:

* ``IPermissionLabels`` for program-wide visibility of private datasets
* the full permission matrix in ``logic/auth.py``
* chained membership actions rejecting the retired grant capacities
* ``ckan nfwf-permissions migrate-roles`` for the role migration

This lives in its own extension rather than in ``ckanext-nfwf_fields`` because
authorization is a separate concern from field and facet logic, and separate
files mean effectively no merge conflicts with Tasks 117/126.
"""
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit


@toolkit.blanket.actions
@toolkit.blanket.auth_functions
@toolkit.blanket.validators
class NfwfPermissionsPlugin(plugins.SingletonPlugin):
    """Registers the ``nfwf_user_*`` actions, their auth functions and validators.

    The blanket decorators pick these up automatically from
    ``logic/action.py``, ``logic/auth.py`` and ``logic/validators.py``, using the
    ``__all__`` declared in each.
    """
    pass
