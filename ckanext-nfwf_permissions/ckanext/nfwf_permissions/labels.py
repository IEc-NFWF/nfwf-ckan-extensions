# encoding: utf-8
"""Program-wide visibility of private datasets -- ``IPermissionLabels``.

CKAN decides who may *see* a dataset by intersecting two sets of opaque
strings. ``get_dataset_labels`` runs at **index time** and its result is written
into the Solr document's ``permission_labels`` field; ``get_user_dataset_labels``
runs per request and becomes a Solr filter query
(``+permission_labels:(a OR b)``), and ``package_show``'s auth function
compares the two sets directly. A dataset is visible when they intersect.

Three consequences shape everything below.

**Labels are baked into the index, not evaluated live.** Changing a grant's
``owner_group`` changes the labels of every dataset in it, and nothing updates
Solr on its own. The chained ``organization_update`` action reindexes that
grant's datasets, and the role migration needs a full
``ckan search-index rebuild``.

**Sysadmins bypass the *user* side, by two different routes -- and not the
dataset side at all.** ``package_search`` sets ``labels = None`` for a sysadmin
and for ``ignore_auth`` (``ckan/logic/action/get.py:1906-1911``), so Platform
Administrators see everything without holding any label. ``package_show``'s
auth function has no such branch: it intersects the two sets unconditionally
(``ckan/logic/auth/get.py:105-118``), and sysadmins are safe there only
because ``authz.is_authorized`` returns before ever calling it. Worth knowing
if anything here is ever chained or decorated with
``@auth_sysadmins_check``, which would suppress that short-circuit and start
subjecting Platform Administrators to label intersection.

``get_dataset_labels`` is a different matter again: it runs at index time for
*every* dataset regardless of who triggered the write, so it must never be
short-circuited for a sysadmin -- a dataset a Platform Administrator saves
would otherwise be indexed with no program labels, and quietly vanish from the
searches this module exists to serve.

(The citation above used to point at ``get.py:1519-1524``, which is the same
four-line idiom inside ``package_autocomplete`` -- a different action. CKAN
2.11 contains it twice, so the wrong one verifies just as convincingly.)

**Only one plugin can provide labels.** ``get_permission_labels`` returns the
*first* ``IPermissionLabels`` implementation it finds
(``ckan/lib/plugins.py:338-342``) -- it does not merge them. No sibling
extension implements it, so this is the one, but a second implementation
anywhere would silently disable one of them.

This subclasses ``DefaultPermissionLabels`` and only ever *adds* labels, so
public datasets, a user's own drafts (``creator-``), organization membership
(``member-``) and collaborators are untouched.
"""
from ckan.lib.plugins import DefaultPermissionLabels

from ckanext.nfwf_permissions import roles

#: CKAN's label for a dataset anyone may read. Its presence means the dataset
#: needs no further labels at all.
PUBLIC = u'public'

#: One label per program, carrying private data to that program's members.
PROGRAM_LABEL = u'program-%s'

#: A single constant label meaning "this dataset's grant belongs to some
#: program". Program Administrators hold it, which is how they get read access
#: across every program without every program id being enumerated into their
#: label set.
#:
#: The breadth is a requirement, not an encoding artefact. "User Roles and
#: Permissions Redesign.docx" lists under Program Administrator:
#:
#:     View/read datasets and resources under other programs
#:     (no editing capability)
#:
#: Enumerating each program id into the label set would grant exactly the same
#: access for a larger index; the constant is the cheaper spelling of the same
#: rule. Verified against the document on 2026-09-25: read is allowed and every
#: write -- package and resource, update, delete and create -- is refused, which
#: is the "(no editing capability)" half.
IN_ANY_PROGRAM = u'in-any-program'


def program_label(program_id):
    return PROGRAM_LABEL % program_id


class NfwfPermissionLabels(DefaultPermissionLabels):
    """Adds program-scoped visibility on top of CKAN's defaults."""

    def get_dataset_labels(self, dataset_obj):
        """Labels written into this dataset's Solr document.

        Adds the owning grant's program, plus the ``in-any-program`` constant,
        to anything not already world-readable.
        """
        labels = super(NfwfPermissionLabels, self).get_dataset_labels(
            dataset_obj)

        # An active public dataset comes back as exactly ['public'] and is
        # visible to everyone already. Adding program labels to it would grant
        # nothing and only inflate the index.
        if PUBLIC in labels:
            return labels

        if not dataset_obj.owner_org:
            # No grant, so no program. CKAN has already added creator-<id>,
            # which is what keeps an unowned draft visible to its author.
            return labels

        program_id = roles.program_id_for_grant(dataset_obj.owner_org)
        if program_id:
            labels.append(program_label(program_id))
            labels.append(IN_ANY_PROGRAM)

        return labels

    def get_user_dataset_labels(self, user_obj):
        """Labels this user carries, used to filter search and dataset reads."""
        labels = super(NfwfPermissionLabels, self).get_user_dataset_labels(
            user_obj)

        if not user_obj or user_obj.is_anonymous:
            return labels

        # Program Readers and Program Administrators both see private data
        # across every grant in the programs they are assigned to. A Grant
        # Editor needs nothing here: CKAN's own member-<org_id> already covers
        # the grants they hold a row on.
        labels.extend(program_label(program_id) for program_id in
                      roles.programs_for_user(
                          user_obj,
                          [roles.CAPACITY_ADMIN, roles.CAPACITY_MEMBER]))

        # A Program Administrator reads private data in every grant that
        # belongs to *any* program, not just their own. This is the redesign
        # document's "View/read datasets and resources under other programs
        # (no editing capability)" -- see IN_ANY_PROGRAM above for the quote
        # and what was measured against it.
        #
        # Grants with no program stay invisible to them, which makes those
        # grants Platform-Administrator-only territory. That follows the same
        # sentence: a grant under no program is not "under other programs".
        #
        # CONFIRMED 2026-09-28, including the part the document cannot have
        # been weighing: the breadth is automatic. A new program's private
        # datasets become readable by every existing Program Administrator as
        # soon as a grant is filed under it, with no per-program decision.
        # That was put to the product owner as a scale question and kept.
        if roles.programs_for_user(user_obj, [roles.CAPACITY_ADMIN]):
            labels.append(IN_ANY_PROGRAM)

        return labels
