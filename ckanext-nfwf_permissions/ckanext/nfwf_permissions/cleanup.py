# encoding: utf-8
"""The one-off cleanup the product owner asked for: close stale accounts, and
remove grants that were created in error.

This is not part of the role migration. ``migration`` judges every membership
row against the new model and can explain each verdict from a rule; this module
carries out what a person decided, from a list they wrote by hand. So its job
is not to decide anything -- it is to refuse the decisions that would cost
something the list's author could not see from a spreadsheet.

Three of those are worth naming:

* **The site user.** ``ckan.site_id`` names an account CKAN uses for its own
  internal calls. It appears in the user list like any other account and reads
  like a leftover, but closing it is not a cleanup -- it takes away the
  identity the site acts under. Refused outright, not warned about.

* **A grant that still holds datasets.** ``organization_delete`` does not stop
  there. With ``ckan.auth.create_unowned_dataset`` off it raises; with it on it
  nulls ``owner_org`` and the datasets survive belonging to no grant at all,
  which no screen on this site can show. Refused, so it cannot happen by
  accident either way.

* **An account somebody is still using.** Nothing technical breaks, so this is
  a warning rather than a refusal -- but it is the one mistake a list written
  from a spreadsheet actually makes, so it is counted separately and named in
  the confirmation prompt.

Deletes here are CKAN's own soft deletes: ``state`` becomes ``deleted`` and the
row stays. Nothing is purged, so every one of them can be put back -- but only
if somebody knows *which* rows to put back, which is what ``undo`` records. A
run that cannot write its undo file does not start.

One thing is written beyond the deletes. Closing a Platform Administrator also
clears the ``sysadmin`` flag, which ``user_delete`` leaves set. The flag is
inert while the account is deleted, because ``ckanext-oauth2`` refuses a
session to anything that is not active -- but reactivating the account would
otherwise hand back Platform Administrator with nobody having decided to. It is
not fully durable either: the oauth2 callback re-grants the flag from the Auth0
group claim on any login attempt, before the login gate rejects it. Removing
the person from Auth0 is the only fix that holds, and Auth0 is not ours.
"""
import datetime
import io
import os

from ckanext.nfwf_permissions import undo

__all__ = [
    u'ACCOUNT', u'GRANT', u'DELETE', u'SKIP', u'WARN', u'BLOCKED',
    u'read_list', u'inspect_accounts', u'inspect_grants', u'apply_accounts',
    u'apply_grants', u'actionable', u'site_user_name',
    u'RECENTLY_ACTIVE_DAYS',
]

ACCOUNT = u'account'
GRANT = u'grant'

# What a run would do with each line of the list.
DELETE = u'delete'       # go ahead
WARN = u'warn'           # go ahead, but say something first
SKIP = u'skip'           # already in that state; nothing to write
BLOCKED = u'blocked'     # refused -- would cost something the list cannot see

# An account seen this recently is being used by somebody, whatever the list
# says. Ninety days rather than thirty: this site has seasonal users who sign
# in when a grant reports, and a reporting gap is not abandonment.
RECENTLY_ACTIVE_DAYS = 90


def site_user_name():
    u"""The account CKAN acts as internally. Never deletable."""
    from ckan.common import config
    return config.get(u'ckan.site_id') or u'default'


def read_list(path):
    u"""One identifier per line.

    Blank lines and ``#`` comments are ignored, and so is anything after a
    comma, so a column pasted straight out of a spreadsheet works without
    being edited first. Order is kept and duplicates are dropped, because the
    confirmation prompt is read against the spreadsheet it came from.
    """
    if not os.path.exists(path):
        raise IOError(u'No such file: {0}'.format(path))
    names = []
    seen = set()
    with io.open(path, encoding=u'utf-8') as handle:
        for line in handle:
            line = line.split(u'#')[0].split(u',')[0].strip()
            if not line or line.lower() in (u'username', u'grant', u'name'):
                continue
            if line not in seen:
                seen.add(line)
                names.append(line)
    return names


def _recently_active(user):
    u"""True if the account has been seen inside the window.

    ``last_active`` only starts in April 2025 on this site, so an empty value
    means "no record", not "never signed in" -- which is why this answers False
    for it rather than reading it as evidence of abandonment.
    """
    seen = getattr(user, u'last_active', None)
    if not seen:
        return False
    now = datetime.datetime.utcnow()
    if getattr(seen, u'tzinfo', None) is not None:
        now = datetime.datetime.now(seen.tzinfo)
    return (now - seen).days <= RECENTLY_ACTIVE_DAYS


def _blank_row(kind, name):
    return {u'kind': kind, u'name': name, u'title': u'', u'id': u'',
            u'verdict': DELETE, u'reason': u'', u'rows': 0, u'datasets': 0,
            u'sysadmin': False, u'state': u''}


def inspect_accounts(names):
    u"""What closing each named account would actually do. Reads only."""
    from ckan import model

    site = site_user_name()
    out = []
    for name in names:
        row = _blank_row(ACCOUNT, name)
        user = model.User.get(name)
        if user is None:
            row.update(verdict=SKIP, reason=u'no such account')
            out.append(row)
            continue

        row[u'id'] = user.id
        row[u'title'] = user.fullname or u''
        row[u'state'] = user.state
        row[u'sysadmin'] = bool(user.sysadmin)
        row[u'rows'] = model.Session.query(model.Member).filter(
            model.Member.table_name == u'user',
            model.Member.table_id == user.id,
            model.Member.state == u'active').count()
        row[u'datasets'] = model.Session.query(model.Package).filter(
            model.Package.creator_user_id == user.id,
            model.Package.state == u'active').count()

        if user.name == site:
            row.update(
                verdict=BLOCKED,
                reason=u'this is the site user named by ckan.site_id -- CKAN '
                       u'acts as this account internally')
        elif user.state == u'deleted':
            row.update(verdict=SKIP, reason=u'already deleted')
        elif user.sysadmin:
            row.update(
                verdict=WARN,
                reason=u'Platform Administrator -- confirm this is not an '
                       u'account the site is still administered from')
        elif _recently_active(user):
            row.update(
                verdict=WARN,
                reason=u'signed in within the last {0} days, so somebody is '
                       u'using it'.format(RECENTLY_ACTIVE_DAYS))
        out.append(row)
    return out


def inspect_grants(names):
    u"""What deleting each named grant would actually do. Reads only."""
    from ckan import model

    out = []
    for name in names:
        row = _blank_row(GRANT, name)
        group = model.Group.get(name)
        if group is None:
            row.update(verdict=SKIP, reason=u'no such grant')
            out.append(row)
            continue

        row[u'id'] = group.id
        row[u'title'] = group.title or group.name
        row[u'state'] = group.state
        row[u'datasets'] = model.Session.query(model.Package).filter(
            model.Package.owner_org == group.id,
            model.Package.state != u'deleted').count()
        row[u'rows'] = model.Session.query(model.Member).filter(
            model.Member.group_id == group.id,
            model.Member.state == u'active').count()

        if not group.is_organization:
            row.update(
                verdict=BLOCKED,
                reason=u'this is a program, not a grant -- deleting it would '
                       u'take every grant filed under it with it')
        elif group.state == u'deleted':
            row.update(verdict=SKIP, reason=u'already deleted')
        elif row[u'datasets']:
            row.update(
                verdict=BLOCKED,
                reason=u'still holds {0} dataset(s); move or delete those '
                       u'first'.format(row[u'datasets']))
        out.append(row)
    return out


def actionable(rows):
    u"""The rows a run would write, in the order the list gave them."""
    return [r for r in rows if r[u'verdict'] in (DELETE, WARN)]


def _sysadmin_context():
    from ckan import model

    return {u'model': model, u'session': model.Session,
            u'user': site_user_name(), u'ignore_auth': True}


def _record_account(row, recorder):
    u"""Write down what closing this account is about to change.

    Mirrors ``user_delete``'s own query rather than guessing at it: that
    action removes every ``member`` row whose ``table_id`` is the user's id,
    with no filter on ``table_name``. Only the active ones are recorded,
    because the rest are already deleted and restoring them would be a change
    this run did not make.
    """
    from ckan import model

    recorder.note(u'closing account {0}'.format(row[u'name']))
    recorder.restore(undo.USER, row[u'id'])
    member_ids = model.Session.query(model.Member.id).filter(
        model.Member.table_id == row[u'id'],
        model.Member.state == u'active').all()
    for (member_id,) in member_ids:
        recorder.restore(undo.MEMBER, member_id)
    collaborations = model.Session.query(
        model.PackageMember.package_id).filter(
            model.PackageMember.user_id == row[u'id']).all()
    for (package_id,) in collaborations:
        recorder.lost(
            u'{0} was a collaborator on dataset {1}. package_member has no '
            u'state column, so that row is really gone and no statement here '
            u'can bring it back.'.format(row[u'name'], package_id))


def _record_grant(row, recorder):
    u"""Write down what deleting this grant is about to change.

    Every member row on the group, not just the user ones: deleting a grant
    clears its dataset rows too.
    """
    from ckan import model

    recorder.note(u'deleting grant {0} ({1})'.format(row[u'name'],
                                                     row[u'title']))
    recorder.restore(undo.GROUP, row[u'id'])
    member_ids = model.Session.query(model.Member.id).filter(
        model.Member.group_id == row[u'id'],
        model.Member.state == u'active').all()
    for (member_id,) in member_ids:
        recorder.restore(undo.MEMBER, member_id)


def _clear_sysadmin(row, recorder):
    u"""Take Platform Administrator off an account that has just been closed.

    Runs after the delete, not before: if the delete fails, nobody has been
    quietly demoted. Recorded before it is written, like everything else.
    """
    if not row[u'sysadmin']:
        return
    from ckan import model

    user = model.User.get(row[u'id'])
    if user is None or not user.sysadmin:
        return
    recorder.restore_sysadmin(row[u'id'])
    user.sysadmin = False
    model.Session.add(user)
    model.repo.commit()


def _apply(rows, inspect, action_name, identifier, record, recorder,
           after=None):
    u"""Delete each actionable row, re-judging it first.

    The verdicts were worked out before the confirmation prompt, which a person
    can sit on for as long as they like, so every one of them is asked again
    here against the database as it stands now. A grant that was empty when the
    report ran and has since been given a dataset must not be deleted on the
    strength of the older answer -- ``organization_delete`` would strand it.

    ``record`` writes the row's ids to the undo file before anything is
    deleted, and ``after`` is anything that has to happen once the delete has
    gone through.

    Returns ``(done, stale)``: how many were deleted, and the rows whose
    verdict changed in between and were therefore left alone.
    """
    from ckan import logic

    delete = logic.get_action(action_name)
    done, stale = 0, []
    for row in actionable(rows):
        fresh = inspect([row[u'name']])[0]
        if fresh[u'verdict'] not in (DELETE, WARN):
            stale.append(fresh)
            continue
        record(fresh, recorder)
        delete(_sysadmin_context(), {u'id': identifier(fresh)})
        if after is not None:
            after(fresh, recorder)
        done += 1
    return done, stale


def apply_accounts(rows, recorder):
    u"""Close the accounts in ``rows``. Returns ``(closed, stale)``.

    Goes through ``user_delete`` rather than writing ``state`` directly,
    because that action also removes the account's membership rows and any
    dataset collaborations. Leaving those behind would keep a closed account
    attached to grants it can no longer reach.
    """
    return _apply(rows, inspect_accounts, u'user_delete',
                  lambda row: row[u'name'], _record_account, recorder,
                  after=_clear_sysadmin)


def apply_grants(rows, recorder):
    u"""Delete the grants in ``rows``. Returns ``(deleted, stale)``.

    Called with the grant's **id**, never its name: ``_group_or_org_delete``
    clears the group's membership rows by matching whatever identifier it was
    handed against ``Member.group_id``, so passing a name deletes the grant and
    silently leaves its rows behind, still pointing at it. The site's own
    delete button has this bug; this does not.
    """
    return _apply(rows, inspect_grants, u'organization_delete',
                  lambda row: row[u'id'] or row[u'name'], _record_grant,
                  recorder)
