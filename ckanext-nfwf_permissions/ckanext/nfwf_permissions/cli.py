# encoding: utf-8
"""``ckan nfwf-permissions`` -- the role migration and the one-off cleanup.

Registered through ``toolkit.blanket.cli``, which imports this module and calls
``get_commands`` for the list named in ``__all__``.

Both commands dry run by default and neither writes without being told twice:
``--apply`` plus a confirmation. For ``migrate-roles`` that is not caution for
its own sake -- the report exists to be signed off before anything is applied,
because a large number of accounts hold assignments of both scopes and have to
lose one side, and that is a decision for the product owner, not a migration
rule. What ``--apply`` actually writes is small: retired grant capacities held
by accounts that are already Platform Administrators, and old Program Member
rows. See ``migration`` for why the rest needs no write.

``cleanup`` is the other shape entirely: it carries out deletions a person
decided on, so the dry run is there to show them what their own list does.
See ``cleanup`` for what it refuses to do regardless.
"""
import collections
import os
import csv
import io

import click

from ckanext.nfwf_permissions import cleanup, migration, undo

__all__ = [u'nfwf_permissions']


@click.group(u'nfwf-permissions', short_help=u'NFWF roles and permissions.')
def nfwf_permissions():
    """Commands for the NFWF role model."""


@nfwf_permissions.command(u'migrate-roles')
@click.option(u'--report', u'report_path', type=click.Path(dir_okay=False),
              help=u'Write the full per-assignment CSV here.')
@click.option(u'--apply', u'apply_changes', is_flag=True, default=False,
              help=u'Actually remove the droppable rows. Off by default.')
@click.option(u'--yes', u'assume_yes', is_flag=True, default=False,
              help=u'Skip the confirmation prompt. Only with --apply.')
@click.option(u'--undo-file', u'undo_path', type=click.Path(dir_okay=False),
              default=None,
              help=u'Where to write the undo script. Defaults to a '
                   u'timestamped file in the working directory.')
def migrate_roles(report_path, apply_changes, assume_yes, undo_path):
    """Report what the new role model makes of the existing assignments.

    Reads only, unless --apply is given.
    """
    plan_data = migration.plan()
    totals = plan_data[u'totals']

    _summary(plan_data, totals)

    if report_path:
        _write_csv(report_path, plan_data)
        click.echo(u'')
        click.echo(u'Wrote {0} assignment rows to {1}'.format(
            totals[u'assignments'], report_path))

    if not apply_changes:
        click.echo(u'')
        click.echo(u'Dry run: nothing was written. Re-run with --apply to '
                   u'remove the {0} droppable row(s).'.format(totals[u'drop']))
        return

    _apply(plan_data, assume_yes, undo_path)


def _summary(plan_data, totals):
    click.echo(u'Assignments: {0} across {1} accounts'.format(
        totals[u'assignments'], totals[u'accounts']))
    click.echo(u'  keep    {0:5d}  already express the right role, no write'
               .format(totals[u'keep']))
    click.echo(u'  drop    {0:5d}  retired capacity on a Platform '
               u'Administrator,'.format(totals[u'drop']))
    click.echo(u'                  or an old Program Member row')
    click.echo(u'  decide  {0:5d}  need a human'.format(totals[u'decide']))
    if totals[u'excluded_rows']:
        click.echo(u'  ({0} further active row(s) sit on deleted groups and are'
                   u' left out: they confer nothing)'.format(
                       totals[u'excluded_rows']))

    click.echo(u'')
    click.echo(u'Accounts needing a decision: {0}'.format(
        totals[u'accounts_to_decide']))
    click.echo(u'  of which hold both scopes at once: {0}'.format(
        totals[u'dual_scope_accounts']))

    dual = [a for a in plan_data[u'accounts']
            if a[u'dual_scope'] and not a[u'is_platform_admin']]
    if dual:
        click.echo(u'')
        click.echo(u'Both scopes -- each has to lose one side '
                   u'(showing the 10 with the most at stake):')
        click.echo(u'  {0:<34} {1:>8} {2:>10} {3:>9}'.format(
            u'account', u'programs', u'grants via', u'editable'))
        worst = sorted(dual, key=lambda a: (
            -a[u'grants_visible_via_programs'], -a[u'grants_editable']))
        for account in worst[:10]:
            click.echo(u'  {0:<34} {1:>8} {2:>10} {3:>9}'.format(
                account[u'account'][:34], account[u'programs_held'],
                account[u'grants_visible_via_programs'],
                account[u'grants_editable']))

    retired = [a for a in plan_data[u'accounts'] if a[u'retired_rows']]
    if retired:
        click.echo(u'')
        click.echo(u'Retired grant capacities, by account:')
        for account in sorted(retired, key=lambda a: -a[u'retired_rows']):
            click.echo(u'  {0:<34} {1:>4} row(s){2}'.format(
                account[u'account'][:34], account[u'retired_rows'],
                u'  [Platform Administrator]'
                if account[u'is_platform_admin'] else u''))

    orphans = plan_data[u'orphan_grants']
    click.echo(u'')
    click.echo(u'Grants with no program: {0} -- unreachable by any program '
               u'role, Platform Administrator only'.format(len(orphans)))

    inactive = plan_data[u'inactive_holders']
    if inactive:
        click.echo(u'')
        click.echo(u'Assignments held by non-active accounts:')
        for account in inactive:
            click.echo(u'  {0:<34} state={1}'.format(
                account[u'account'][:34], account[u'account_state']))


def _write_csv(path, plan_data):
    with io.open(path, u'w', newline=u'', encoding=u'utf-8') as handle:
        writer = csv.DictWriter(
            handle, fieldnames=migration.ASSIGNMENT_FIELDS)
        writer.writeheader()
        for row in plan_data[u'assignments']:
            writer.writerow(row)


def _open_undo(undo_path, command):
    u"""Open the undo file, turning a refusal into a readable message.

    Without this the operator gets a traceback at the worst possible moment.
    """
    try:
        return undo.open_log(undo_path, command)
    except IOError as exc:
        raise click.ClickException(str(exc))


def _apply(plan_data, assume_yes, undo_path):
    from ckan import model

    droppable = migration.droppable(plan_data)
    if not droppable:
        click.echo(u'')
        click.echo(u'Nothing to drop.')
        return

    retired = [r for r in droppable
               if r[u'drop_rule'] == migration.DROP_RETIRED_ON_ADMIN]
    legacy = [r for r in droppable
              if r[u'drop_rule'] == migration.DROP_LEGACY_MEMBERSHIP]
    retired_real = [r for r in droppable
                    if r[u'drop_rule'] == migration.DROP_RETIRED_GRANT_ROLE]

    click.echo(u'')
    click.echo(u'About to remove {0} membership row(s):'.format(
        len(droppable)))
    if retired:
        click.echo(u'  {0:>5}  retired grant capacities held by Platform '
                   u'Administrators'.format(len(retired)))
    if legacy:
        # Spelled out because this half, unlike the other, takes something
        # away from people who are using it.
        click.echo(u'  {0:>5}  old Program Member rows, which do not carry '
                   u'over to the new model'.format(len(legacy)))
        click.echo(u'         Those accounts keep any grant they hold. What '
                   u'they lose is the Program')
        click.echo(u'         Affiliation box on the dataset form, whose '
                   u'answer the site already')
        click.echo(u"         overrides with the grant's own program.")
        emptied = sorted({a[u'account'] for a in plan_data[u'accounts']
                          if u'left with no role' in a[u'reason']})
        if emptied:
            click.echo(u'         {0} account(s) are left holding no role at '
                       u'all: {1}'.format(
                           len(emptied), u', '.join(emptied[:5])
                           + (u', ...' if len(emptied) > 5 else u'')))
    if retired_real:
        # The other half that costs somebody something, and the newer of the
        # two decisions, so it is spelled out at the same length.
        click.echo(u'  {0:>5}  Grant Member or Grant Admin rows held by real '
                   u'people. The new model'.format(len(retired_real)))
        click.echo(u'         has no read-only role at grant level, so these '
                   u'are removed rather')
        click.echo(u"         than promoted: those accounts lose read access "
                   u"to those grants'")
        click.echo(u'         private datasets. Settled with the product '
                   u'owner on 2026-10-13.')
    click.echo(u'')
    for account in sorted({row[u'account'] for row in droppable}):
        rows = [r for r in droppable if r[u'account'] == account]
        click.echo(u'  {0:<34} {1} row(s)'.format(account[:34], len(rows)))

    if not assume_yes and not click.confirm(u'Proceed?', default=False):
        click.echo(u'Aborted; nothing was written.')
        return

    undo_path = os.path.abspath(undo_path or undo.default_path(
        u'migrate-roles'))
    # Opened before the first write, and deliberately not inside the try: if
    # the undo file cannot be created, this run must not happen at all.
    recorder = _open_undo(undo_path, u'migrate-roles')

    removed = 0
    skipped = 0
    try:
        for row in droppable:
            user = model.User.get(row[u'account'])
            group = model.Group.get(row[u'group_name'])
            if user is None or group is None:
                continue
            # Re-read the flag, but only for the rows that rest on it.
            # `plan()` ran before the confirmation prompt, which a person
            # can sit on for as long as they like, and "there is nothing to
            # restore it to" holds only while the account is still a
            # Platform Administrator; if it was demoted in the meantime that
            # row is a decision again, not a drop.
            #
            # A legacy program membership is dropped for a different reason
            # -- the role itself does not carry over -- which does not
            # depend on who owns the account. Applying the sysadmin check to
            # those would silently skip every one of them, since they are
            # held by ordinary people.
            if (row[u'drop_rule'] == migration.DROP_RETIRED_ON_ADMIN
                    and not user.sysadmin):
                skipped += 1
                continue
            member = model.Session.query(model.Member).filter(
                model.Member.table_name == u'user',
                model.Member.table_id == user.id,
                model.Member.group_id == group.id,
                model.Member.capacity == row[u'capacity'],
                model.Member.state == u'active').first()
            if member is None:
                continue
            recorder.restore(undo.MEMBER, member.id)
            member.state = u'deleted'
            removed += 1

        model.repo.commit()
    finally:
        # Closed even if the loop raises, so the file ends the way a
        # reader expects. Every statement is flushed as it is written,
        # so what is already there survives either way.
        recorder.close()
    click.echo(u'')
    click.echo(u'Removed {0} row(s).'.format(removed))
    click.echo(u'Undo script written to {0}'.format(undo_path))
    if skipped:
        click.echo(u'Skipped {0} row(s): the account is no longer a Platform '
                   u'Administrator, so those rows need a decision again. '
                   u'Re-run the report.'.format(skipped))
    click.echo(u'No search reindex is needed: these rows only affected which '
               u'datasets those accounts could see, and dataset permission '
               u'labels are unchanged. A bulk owner_group change would be '
               u'different -- that needs `ckan search-index rebuild`.')


@nfwf_permissions.command(u'cleanup')
@click.option(u'--accounts', u'accounts_path', type=click.Path(dir_okay=False),
              help=u'File of usernames to close, one per line.')
@click.option(u'--grants', u'grants_path', type=click.Path(dir_okay=False),
              help=u'File of grant names to delete, one per line.')
@click.option(u'--apply', u'apply_changes', is_flag=True, default=False,
              help=u'Actually write the deletions. Off by default.')
@click.option(u'--yes', u'assume_yes', is_flag=True, default=False,
              help=u'Skip the confirmation prompt. Only with --apply.')
@click.option(u'--undo-file', u'undo_path', type=click.Path(dir_okay=False),
              default=None,
              help=u'Where to write the undo script. Defaults to a '
                   u'timestamped file in the working directory.')
def cleanup_command(accounts_path, grants_path, apply_changes, assume_yes,
                    undo_path):
    """Close the accounts, and delete the grants, on a hand-written list.

    Takes the lists as files rather than arguments so the run is reproducible
    and the input can be read back afterwards -- a list this long typed onto a
    command line cannot be checked against the spreadsheet it came from.

    Reads only, unless --apply is given. See ``cleanup`` for what it refuses.
    """
    if not accounts_path and not grants_path:
        raise click.UsageError(
            u'Give --accounts, --grants, or both. There is nothing to do.')

    accounts = (cleanup.inspect_accounts(cleanup.read_list(accounts_path))
                if accounts_path else [])
    grants = (cleanup.inspect_grants(cleanup.read_list(grants_path))
              if grants_path else [])

    if accounts:
        _cleanup_report(u'ACCOUNTS', accounts)
    if grants:
        _cleanup_report(u'GRANTS', grants)

    doable = cleanup.actionable(accounts) + cleanup.actionable(grants)
    blocked = [r for r in accounts + grants
               if r[u'verdict'] == cleanup.BLOCKED]

    if blocked:
        # Said here rather than beside the confirmation prompt, because a run
        # whose every line was refused has nothing to confirm and would
        # otherwise reach "Nothing to do" without ever mentioning why. Loud,
        # because with --yes nobody reads a prompt either.
        click.echo(u'')
        click.echo(u'{0} line(s) REFUSED and will not be touched. Read the '
                   u'reasons above before going on.'.format(len(blocked)))

    if not apply_changes:
        click.echo(u'')
        click.echo(u'Dry run: nothing was written. Re-run with --apply to '
                   u'carry out the {0} deletion(s) above.'.format(len(doable)))
        return

    if not doable:
        click.echo(u'')
        click.echo(u'Nothing to do.')
        return

    warned = [r for r in doable if r[u'verdict'] == cleanup.WARN]
    if warned:
        click.echo(u'')
        click.echo(u'{0} of these need a second look:'.format(len(warned)))
        for row in warned:
            click.echo(u'  {0:<36} {1}'.format(row[u'name'][:36],
                                               row[u'reason']))

    click.echo(u'')
    if not assume_yes and not click.confirm(
            u'Delete {0} account(s) and {1} grant(s)?'.format(
                len(cleanup.actionable(accounts)),
                len(cleanup.actionable(grants))),
            default=False):
        click.echo(u'Aborted; nothing was written.')
        return

    undo_path = os.path.abspath(undo_path or undo.default_path(u'cleanup'))
    # Before the first write, so a run that cannot record itself never starts.
    recorder = _open_undo(undo_path, u'cleanup')
    try:
        closed, stale_accounts = cleanup.apply_accounts(accounts, recorder)
        deleted, stale_grants = cleanup.apply_grants(grants, recorder)
    finally:
        recorder.close()
    click.echo(u'')
    click.echo(u'Closed {0} account(s), deleted {1} grant(s).'.format(
        closed, deleted))
    click.echo(u'Both are CKAN soft deletes: the rows are still there with '
               u'state=deleted, so anything here can be put back.')
    click.echo(u'Undo script written to {0}'.format(undo_path))
    for row in stale_accounts + stale_grants:
        click.echo(u'  left alone: {0:<30} {1}'.format(
            row[u'name'][:30], row[u'reason']))
    if stale_accounts or stale_grants:
        click.echo(u'Those changed between the report and the confirmation. '
                   u'Re-run to see where they stand now.')
    if deleted:
        click.echo(u'Run `ckan search-index rebuild` -- a deleted grant has '
                   u'to leave the dataset search index.')


def _cleanup_report(heading, rows):
    """One line per line of the list, refusals first so they are read."""
    order = {cleanup.BLOCKED: 0, cleanup.WARN: 1,
             cleanup.DELETE: 2, cleanup.SKIP: 3}
    click.echo(u'')
    click.echo(heading)
    click.echo(u'  {0:<36} {1:<8} {2:<5} {3:<5} {4}'.format(
        u'name', u'verdict', u'rows', u'data', u'why'))
    for row in sorted(rows, key=lambda r: (order[r[u'verdict']], r[u'name'])):
        click.echo(u'  {0:<36} {1:<8} {2:<5} {3:<5} {4}'.format(
            row[u'name'][:36], row[u'verdict'], row[u'rows'],
            row[u'datasets'], row[u'reason']))
    counts = collections.Counter(r[u'verdict'] for r in rows)
    click.echo(u'  -- {0}'.format(
        u', '.join(u'{0} {1}'.format(n, v) for v, n in sorted(
            counts.items()))))
