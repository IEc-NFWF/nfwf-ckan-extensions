# Running the cleanup and the role migration

The procedure for applying `nfwf-permissions cleanup` and
`nfwf-permissions migrate-roles` to a database — a local copy, staging, or
production. The two commands are documented in `README.md`; this is the
order to run them in, what to check between steps, and how to undo a run.

**The account and grant lists are not in this repo.** They name real people
and the decisions made about their accounts, so they are distributed
separately. Ask the maintainer for the current pair. Everything else you
need is here.

---

## Before you start

**The extension has to be deployed.** Both commands live in
`ckanext-nfwf_permissions`; a database without the current code installed
cannot run them.

**You need two list files**, one account name per line, one grant id or name
per line, blank lines and `#` comments ignored:

    --accounts  cleanup_accounts_<date>.txt
    --grants    cleanup_grants_<date>.txt

**You need a durable path for the undo files.** Not `/tmp` inside a
container that may be recreated. If the undo file is lost the run cannot be
reversed except from a backup — see *If something is wrong*.

### Commands below are written in local shapes

Every `ckan` command assumes it runs inside the application container:

    docker compose -f docker-compose.dev.yml exec -T ckan-dev \
      ckan -c /srv/app/ckan.ini <command>

and every `psql` inside the database container:

    docker compose -f docker-compose.dev.yml exec -T db \
      psql -U ckan -d ckan -c "<sql>"

Adjust for your environment. On a server the `ckan` binary and `psql` are
usually on the path directly.

---

## The numbers, and how to make them exact

The figures quoted below came from a production snapshot taken 2026-10-13.
They are aggregate counts, useful as a sanity check: if your run reports
something in the same neighbourhood, nothing has gone sideways.

They will not match exactly on a database of a different vintage. Accounts
sign in, grants gain datasets, roles get edited. **To get exact numbers,
rehearse on a copy of the database you are about to change** — Step 0b. A
dry run of either command against that copy prints precisely what the real
run will do.

---

## Step 0 — back up, and prove the backup

    pg_dump -U ckan -Fc ckan > ckan-pre-migration-$(date +%Y%m%d).dump

Then prove it restores, because an unverified backup is not a backup:

    psql -U ckan -d postgres -c "CREATE DATABASE restore_check OWNER ckan;"
    pg_restore -U ckan -d restore_check ckan-pre-migration-YYYYMMDD.dump
    psql -U ckan -d restore_check -c \
      "SELECT (SELECT count(*) FROM \"user\"),
              (SELECT count(*) FROM \"group\"),
              (SELECT count(*) FROM member);"
    psql -U ckan -d postgres -c "DROP DATABASE restore_check;"

The three counts should match the source database.

---

## Step 0b — rehearse on a copy, with today's data

Strongly recommended, and nearly free: the dump from Step 0 is already the
snapshot you need. A compressed dump of this database is a few megabytes,
and the rehearsal takes a couple of minutes.

Restore it over a scratch database, then run:

    bash migrate-rehearse.sh

The script copies the database into `ckan_test`, applies both commands,
replays both undo files, and checks the tables come back hash-identical. It
writes only to `ckan_test`.

**Read the output and keep it.** Whatever it prints for the cleanup, the
migration and the final report is what the real run will print, because it
is the same data — use those figures in place of the reference ones here.
If it ends with

    IDENTICAL -- user, member and group tables are exactly back to the baseline

then the undo has been proven on the rows you are about to change.

Rebuild the search index afterwards so the site matches its new database:

    ckan -c /srv/app/ckan.ini search-index clear
    ckan -c /srv/app/ckan.ini search-index rebuild

**Then run for real while the site is quiet**, so little changes between the
dump and the run. Drift in that window is mostly harmless: both commands
re-check every row at write time, so a grant that has gained a dataset is
refused and an account already closed is skipped, whatever the older report
said.

---

## Step 1 — dry runs, both commands, writing nothing

Neither command writes anything without `--apply`. Run both and read them
before going further.

    ckan -c /srv/app/ckan.ini nfwf-permissions cleanup \
      --accounts /path/to/cleanup_accounts_<date>.txt \
      --grants   /path/to/cleanup_grants_<date>.txt

Reference output:

    ACCOUNTS   33 delete, 2 warn
    GRANTS     7 delete
    Dry run: nothing was written ... 42 deletion(s)

Warnings flag accounts that signed in recently or hold Platform
Administrator; **a warning is for a person to read, not a veto.** Each one
on the current list was confirmed by the product owner before it went on
there.

    ckan -c /srv/app/ckan.ini nfwf-permissions migrate-roles

Run before the cleanup this reports more than it will afterwards, because
the accounts about to be closed still hold rows:

    Assignments: 955 across 180 accounts
      keep      196
      drop      757
      decide      2
    Accounts needing a decision: 1

Any `decide` here is an account holding a combination the migration will not
resolve on its own. On the current list the one such account is itself due
for closure, so it resolves at Step 2. **After the cleanup the same command
reports 680 to drop and 0 to decide.** If your run shows a non-zero `decide`
after the cleanup, stop and ask — that is a question for the product owner,
not something to force through.

---

## Step 2 — the cleanup

    ckan -c /srv/app/ckan.ini nfwf-permissions cleanup \
      --accounts /path/to/cleanup_accounts_<date>.txt \
      --grants   /path/to/cleanup_grants_<date>.txt \
      --apply \
      --undo-file /durable/path/undo-cleanup.sql

**Do not pass `--yes`.** It skips the confirmation, and the confirmation is
where the warnings are put in front of you one last time. Type `y`.

    Closed 35 account(s), deleted 7 grant(s).
    Undo script written to /durable/path/undo-cleanup.sql

Check:

```sql
SELECT count(*) FROM "user"  WHERE state='deleted';   -- 2  -> 37
SELECT count(*) FROM "user"  WHERE sysadmin;          -- 7  -> 6
SELECT count(*) FROM "group" WHERE is_organization AND state='active';  -- 571 -> 564
```

The sysadmin count dropping is a closed Platform Administrator losing the
flag, which `user_delete` on its own would have left set.

Confirm the undo file exists and is not empty — **134 statements** on the
reference snapshot (35 accounts + 7 grants + 91 membership rows + 1 sysadmin
flag):

    grep -c '^UPDATE' /durable/path/undo-cleanup.sql


**If a run aborts partway, move its undo file aside before you retry.**
Both commands refuse to start when the file they were given already
exists, rather than overwriting it -- a half-written undo file is still
the only record of the rows that run did change, and every statement in
it is flushed as it is written, so it applies as far as it got. Rename
it and pass the same path again, or pass a new one.

---

## Step 3 — the migration

    ckan -c /srv/app/ckan.ini nfwf-permissions migrate-roles \
      --apply \
      --undo-file /durable/path/undo-migrate.sql

Again, no `--yes`. The prompt lists what is about to go, grouped by rule, and
two of the three rules take access away from someone.

    Removed 680 row(s).
    Undo script written to /durable/path/undo-migrate.sql

---

## Step 4 — rebuild the search index

    ckan -c /srv/app/ckan.ini search-index rebuild

Needed because of the deleted grants, not the role rows. A deleted grant has
to leave the dataset search index; membership rows do not affect dataset
permission labels and need no reindex of their own.

Expect roughly **450 datasets** and no errors.

---

## Step 5 — verify

**The report should now be empty of work:**

    ckan -c /srv/app/ckan.ini nfwf-permissions migrate-roles

```
Assignments: 186 across 164 accounts
  keep      186
  drop        0
  decide      0

Accounts needing a decision: 0
```

`drop 0` means it is done. `decide 0` means nothing is waiting on a person.

**Every account on the list is closed, and nothing else is:**

```sql
-- substitute the names from cleanup_accounts_<date>.txt
SELECT name, state, sysadmin FROM "user"
WHERE name = ANY(string_to_array(:names, ','))
ORDER BY state, name;
```

All should read `deleted` with `sysadmin = f`.

**Nobody kept a retired grant role:**

```sql
SELECT count(*) FROM member
WHERE table_name = 'user' AND state = 'active'
  AND capacity IN ('member', 'admin')
  AND group_id IN (SELECT id FROM "group" WHERE is_organization);
```

Should be `0`. Grant Member and Grant Admin do not exist in the new model.

**Accounts that kept a role still have exactly one:**

```sql
SELECT count(*) FROM (
  SELECT table_id FROM member
  WHERE table_name = 'user' AND state = 'active'
  GROUP BY table_id HAVING count(*) > 1
) AS multi;
```

Should be `0` under one-role-per-user.

**Finally, spot-check the site in a browser.** Sign in, open a grant, open a
program, open a dataset. The numbers above say the data is right; only this
says the site still works.

---

## If something is wrong

Each undo file is a plain SQL script. One statement per line, no
transaction, so a file cut short still applies as far as it got, and running
it twice is harmless.

Reverse the migration only:

    psql -U ckan -d ckan -f /durable/path/undo-migrate.sql
    ckan -c /srv/app/ckan.ini search-index rebuild

Reverse everything, migration first:

    psql -U ckan -d ckan -f /durable/path/undo-migrate.sql
    psql -U ckan -d ckan -f /durable/path/undo-cleanup.sql
    ckan -c /srv/app/ckan.ini search-index rebuild

In rehearsal this put the `user`, `member` and `group` tables back
hash-identical to the starting state.

**What the undo does not cover.** `user_delete` also removes an account's
dataset collaborations, and `package_member` has no `state` column, so those
rows are really deleted. Each one is written into the undo file as a
`NOT RECOVERABLE` comment naming what was lost. There were none on the
reference snapshot — `select count(*) from package_member` was 0 — so if
that comment appears on your run, something has changed since and it is
worth reading before you go on.

If the undo files are gone, or the damage is outside what they cover, the
Step 0 backup is the fallback.

---

## What this does not do

**It does not touch Auth0.** A closed CKAN account cannot log in — oauth2
refuses a session to anything that is not active — but the identity still
exists at the identity provider. Removing it there is a separate job for
whoever owns that tenant.

**It does not assign anyone a new role.** The migration removes rows the new
model has no place for. Giving someone Program Reader, or adding a person
back to a grant if they turn out to need it, is ordinary day-to-day
administration through the UI.

**It does not fix the delete buttons.** These commands exist because
accounts and grants could not be deleted from the UI. The account-delete
cause is known — `ckanext-oauth2` denied `user_update` to everyone,
sysadmins included, fixed by commit `bcb0f44` on branch
`task-125-oauth2-approval`. That fix lives in the `ckanext-oauth2`
repository, not this one. The grant-delete failure has not been
reproduced and is still open.
