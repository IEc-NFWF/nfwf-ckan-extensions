# encoding: utf-8
"""Record what a run changed, so somebody can put it back.

Everything both ``--apply`` paths do is a soft delete: ``state`` becomes
``deleted`` and the row stays. That makes the *data* recoverable, and it is
why these commands are safe to run. It does not make the *run* recoverable,
which is a different thing and the reason this module exists.

``member`` has no timestamp and no revision -- its columns are ``id``,
``table_id``, ``group_id``, ``state``, ``table_name`` and ``capacity``, and
that is all. The full sequence flips around 787 of those rows. Afterwards
nothing in the table distinguishes the ones this run flipped from the ones
that were already deleted before it started, so "put it back" has no answer
unless somebody wrote the ids down first. Nothing did.

So each run writes its ids out *before* it touches the database, and the file
it writes is the recovery procedure rather than the raw material for one:

* One statement per line, each one standing alone. There is no ``BEGIN`` and
  no ``COMMIT``, so a file cut short by a crash still applies cleanly as far
  as it got -- which is exactly the case where it is needed.
* Flushed after every line, for the same reason.
* Idempotent. Re-running it sets rows that are already active to active.

**It restores states, not collaborations.** ``user_delete`` also removes the
account's ``package_member`` rows, and that table has no ``state`` column, so
``delete()`` falls through to a real ``DELETE``. Those rows are destroyed and
no undo file can bring them back. Each one is written out as a comment naming
what was lost, which is the most that can honestly be offered. There are none
at all in the current data -- ``select count(*) from package_member`` is 0 --
so this costs nothing today and would cost everything the day it does not.
"""
import datetime
import io

__all__ = [
    u'MEMBER', u'USER', u'GROUP', u'Recorder', u'default_path', u'open_log',
]

MEMBER = u'member'
USER = u'user'
GROUP = u'group'

# Quoted because "user" and "group" are both reserved words in Postgres.
_RESTORE = {
    MEMBER: u"UPDATE member SET state='active' WHERE id = '{0}';",
    USER: u"UPDATE \"user\" SET state='active' WHERE id = '{0}';",
    GROUP: u"UPDATE \"group\" SET state='active' WHERE id = '{0}';",
}
_SYSADMIN = u"UPDATE \"user\" SET sysadmin = true WHERE id = '{0}';"


def default_path(command):
    u"""A file name nobody has to invent under pressure."""
    stamp = datetime.datetime.utcnow().strftime(u'%Y%m%d-%H%M%S')
    return u'nfwf-undo-{0}-{1}.sql'.format(command, stamp)


class Recorder(object):
    u"""Writes the undo file as the run goes, one statement at a time."""

    def __init__(self, handle, command):
        self._handle = handle
        self.count = 0
        self._line(u'-- Undo for: ckan nfwf-permissions {0} --apply'.format(
            command))
        self._line(u'-- Run started: {0}Z'.format(
            datetime.datetime.utcnow().replace(microsecond=0).isoformat()))
        self._line(u'--')
        self._line(u'-- Each statement stands alone: no transaction, so a '
                   u'file cut short by a')
        self._line(u'-- crash still applies as far as it got, and running it '
                   u'twice is harmless.')
        self._line(u'--')
        self._line(u'--   psql -U ckan -d ckan -f <this file>')
        self._line(u'--')
        self._line(u'-- Then rebuild the search index: ckan search-index '
                   u'rebuild')
        self._line(u'')

    def _line(self, text):
        self._handle.write(text + u'\n')
        # Flushed every time. The run this protects against is the one that
        # dies halfway, and a buffered file would lose exactly the part that
        # mattered.
        self._handle.flush()

    def restore(self, table, row_id):
        u"""Record that ``row_id`` in ``table`` is about to be soft deleted."""
        self._line(_RESTORE[table].format(row_id))
        self.count += 1

    def restore_sysadmin(self, user_id):
        u"""Record that an account is about to lose Platform Administrator."""
        self._line(_SYSADMIN.format(user_id))
        self.count += 1

    def lost(self, description):
        u"""Record something that cannot be restored, as a comment.

        Used for dataset collaborations, which are hard deleted. Written down
        because a person reading this file deserves to know what it does not
        cover, rather than discovering the gap by running it and finding
        something still missing.
        """
        self._line(u'-- NOT RECOVERABLE: {0}'.format(description))

    def note(self, text):
        self._line(u'-- {0}'.format(text))

    def close(self):
        self._line(u'')
        self._line(u'-- {0} statement(s). End of undo file.'.format(
            self.count))
        self._handle.close()


def open_log(path, command):
    u"""Open an undo file, or raise before anything has been written.

    Called ahead of the first database write on purpose. A run that cannot
    record itself must not start, because the whole argument for applying
    these changes is that they can be undone.

    Opened exclusively, so an existing file is never overwritten. The two
    commands are run one after the other against the same database, and
    RUNBOOK-style fixed paths make it easy to point the second at the file
    the first just wrote -- which would destroy the only record of it. The
    same goes for re-running a command after a partial failure, which is
    exactly when the earlier file matters most. Refusing costs a rename;
    overwriting costs the run.
    """
    try:
        handle = io.open(path, u'x', encoding=u'utf-8')
    except FileExistsError:
        raise IOError(
            u'Undo file already exists: {0} -- refusing to overwrite it, '
            u'because it may be the only record of an earlier run. Move it '
            u'aside, or pass a different --undo-file.'.format(path))
    return Recorder(handle, command)
