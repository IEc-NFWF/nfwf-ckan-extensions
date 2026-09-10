# encoding: utf-8
"""``ckan nfwf-permissions`` -- the role migration command.

Registered through ``toolkit.blanket.cli``, which imports this module and calls
``get_commands`` for the list named in ``__all__``.

Dry run is the default and there is no way to write without saying so twice:
``--apply`` plus a confirmation. That is not caution for its own sake. The
report exists because Q3 has decisions in it that Emily and Adrian have to sign
off on -- 116 accounts hold assignments of both scopes and have to lose one
side -- and applying anything before that conversation would pre-empt it.

What ``--apply`` actually writes is small: retired grant capacities held by
accounts that are already Platform Administrators, and nothing else. See
``migration`` for why the rest needs no write.
"""
import csv
import io

import click

from ckanext.nfwf_permissions import migration

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
def migrate_roles(report_path, apply_changes, assume_yes):
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

    _apply(plan_data, assume_yes)


def _summary(plan_data, totals):
    click.echo(u'Assignments: {0} across {1} accounts'.format(
        totals[u'assignments'], totals[u'accounts']))
    click.echo(u'  keep    {0:5d}  already express the right role, no write'
               .format(totals[u'keep']))
    click.echo(u'  drop    {0:5d}  retired capacity on a Platform Administrator'
               .format(totals[u'drop']))
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


def _apply(plan_data, assume_yes):
    from ckan import model

    droppable = migration.droppable(plan_data)
    if not droppable:
        click.echo(u'')
        click.echo(u'Nothing to drop.')
        return

    click.echo(u'')
    click.echo(u'About to remove {0} membership row(s): retired grant '
               u'capacities held by Platform Administrators.'.format(
                   len(droppable)))
    for account in sorted({row[u'account'] for row in droppable}):
        rows = [r for r in droppable if r[u'account'] == account]
        click.echo(u'  {0:<34} {1} row(s)'.format(account[:34], len(rows)))

    if not assume_yes and not click.confirm(u'Proceed?', default=False):
        click.echo(u'Aborted; nothing was written.')
        return

    removed = 0
    for row in droppable:
        user = model.User.get(row[u'account'])
        group = model.Group.get(row[u'group_name'])
        if user is None or group is None:
            continue
        member = model.Session.query(model.Member).filter(
            model.Member.table_name == u'user',
            model.Member.table_id == user.id,
            model.Member.group_id == group.id,
            model.Member.capacity == row[u'capacity'],
            model.Member.state == u'active').first()
        if member is None:
            continue
        member.state = u'deleted'
        removed += 1

    model.repo.commit()
    click.echo(u'')
    click.echo(u'Removed {0} row(s).'.format(removed))
    click.echo(u'No search reindex is needed: these rows only affected which '
               u'datasets those accounts could see, and dataset permission '
               u'labels are unchanged. A bulk owner_group change would be '
               u'different -- that needs `ckan search-index rebuild`.')
