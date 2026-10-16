#!/bin/bash
# Rehearse the cleanup and the role migration end to end, against ckan_test.
# See MIGRATION.md.
#
# Copies the `ckan` database into `ckan_test`, runs both commands against the
# copy, replays both undo files, and checks the tables come back
# hash-identical. The `ckan` database is only ever read, and only by pg_dump.
# Nothing here touches staging or production.
#
# Usage, from anywhere:
#
#     ACCOUNTS=/path/cleanup_accounts_<date>.txt \
#     GRANTS=/path/cleanup_grants_<date>.txt \
#     bash migrate-rehearse.sh
#
# The two list files are not in this repo -- they name real people. Ask the
# maintainer. Both are copied into the container for the run.
#
# Override any of these if your setup differs:
#     REPO     checkout root holding docker-compose.dev.yml
#     COMPOSE  compose file name
#     APP      application service name
#     DB       database service name
#     WORK     scratch directory on the host
set -e

REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
COMPOSE="${COMPOSE:-docker-compose.dev.yml}"
APP="${APP:-ckan-dev}"
DB="${DB:-db}"
WORK="${WORK:-/tmp/nfwf-rehearsal}"
ACCOUNTS="${ACCOUNTS:-}"
GRANTS="${GRANTS:-}"

if [ -z "$ACCOUNTS" ] || [ -z "$GRANTS" ]; then
  echo "ERROR: set ACCOUNTS and GRANTS to the two list files." >&2
  echo "       They are distributed separately; see MIGRATION.md." >&2
  exit 2
fi
for f in "$ACCOUNTS" "$GRANTS"; do
  [ -r "$f" ] || { echo "ERROR: cannot read $f" >&2; exit 2; }
done

cd "$REPO"
export MSYS_NO_PATHCONV=1          # Git Bash: keep container paths intact
mkdir -p "$WORK"

DC="docker compose -f $COMPOSE"
TESTURL="postgresql://ckan:ckan@db/ckan_test"
IN=/tmp/rehearsal

psqlt() { $DC exec -T "$DB" psql -U ckan -X -q -d ckan_test "$@"; }
ckanc() { $DC exec -T -e CKAN_SQLALCHEMY_URL=$TESTURL "$APP" \
            ckan -c /srv/app/ckan.ini "$@"; }
say()   { echo ""; echo "=============== $* ==============="; }

counts() {
  psqlt -tA -c "
    SELECT 'users active=' || (SELECT count(*) FROM \"user\" WHERE state='active')
        || ' deleted='     || (SELECT count(*) FROM \"user\" WHERE state='deleted')
        || ' sysadmins='   || (SELECT count(*) FROM \"user\" WHERE sysadmin)
        || ' | grants='    || (SELECT count(*) FROM \"group\" WHERE is_organization AND state='active')
        || ' | user member rows active=' || (SELECT count(*) FROM member WHERE table_name='user' AND state='active')
        || ' deleted='     || (SELECT count(*) FROM member WHERE table_name='user' AND state='deleted');"
}

hashes() {
  psqlt -tA -c "SELECT md5(string_agg(id||state||sysadmin::text, ',' ORDER BY id)) FROM \"user\";"
  psqlt -tA -c "SELECT md5(string_agg(id||state, ',' ORDER BY id)) FROM member;"
  psqlt -tA -c "SELECT md5(string_agg(id||state, ',' ORDER BY id)) FROM \"group\";"
}

say "0. stage the list files into the container"
$DC exec -T "$APP" sh -c "mkdir -p $IN"
$DC exec -T "$APP" sh -c "cat > $IN/accounts.txt" < "$ACCOUNTS"
$DC exec -T "$APP" sh -c "cat > $IN/grants.txt"   < "$GRANTS"
echo "accounts: $(grep -cvE '^\s*(#|$)' "$ACCOUNTS") entries, \
grants: $(grep -cvE '^\s*(#|$)' "$GRANTS") entries"

say "1. rebuild ckan_test from the current database"
$DC exec -T "$DB" psql -U ckan -X -q -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE datname='ckan_test' AND pid <> pg_backend_pid();" > /dev/null
$DC exec -T "$DB" psql -U ckan -X -q -d postgres -c "DROP DATABASE IF EXISTS ckan_test;"
$DC exec -T "$DB" psql -U ckan -X -q -d postgres -c "CREATE DATABASE ckan_test OWNER ckan;"
$DC exec -T "$DB" sh -c "pg_dump -U ckan ckan | psql -U ckan -X -q -d ckan_test" > /dev/null
echo "restored"

say "2. baseline"
BASE=$(counts); echo "$BASE"
hashes > "$WORK/hash_before.txt"
cat "$WORK/hash_before.txt"

say "3. cleanup --apply"
ckanc nfwf-permissions cleanup \
  --accounts $IN/accounts.txt --grants $IN/grants.txt \
  --apply --yes --undo-file $IN/undo-cleanup.sql 2>&1 | tail -22

say "4. migrate-roles --apply"
ckanc nfwf-permissions migrate-roles \
  --apply --yes --undo-file $IN/undo-migrate.sql 2>&1 | tail -32

say "5. after the full sequence"
counts

say "6. the report, re-run against the migrated database"
ckanc nfwf-permissions migrate-roles 2>&1 | tail -22

say "7. every listed account closed, and nothing else"
$DC exec -T "$APP" sh -c "grep -vE '^[[:space:]]*(#|$)' $IN/accounts.txt" \
  | tr -d '\r' | paste -sd, - > "$WORK/names.csv"
psqlt -v n="$(cat "$WORK/names.csv")" -c "
  SELECT state, sysadmin, count(*)
  FROM \"user\" WHERE name = ANY(string_to_array(:'n', ','))
  GROUP BY state, sysadmin ORDER BY state;"
echo "(expect all 'deleted'/f, except the site user which stays active)"

say "8. no retired grant role survived"
psqlt -tA -c "
  SELECT 'active grant member/admin rows: ' || count(*) FROM member
  WHERE table_name='user' AND state='active' AND capacity IN ('member','admin')
    AND group_id IN (SELECT id FROM \"group\" WHERE is_organization);"
psqlt -tA -c "
  SELECT 'accounts holding more than one role: ' || count(*) FROM (
    SELECT table_id FROM member WHERE table_name='user' AND state='active'
    GROUP BY table_id HAVING count(*) > 1) AS m;"
echo "(both should be 0)"

say "9. the undo files"
$DC cp "$APP:$IN/undo-cleanup.sql" "$WORK/undo-cleanup.sql" > /dev/null
$DC cp "$APP:$IN/undo-migrate.sql" "$WORK/undo-migrate.sql" > /dev/null
echo "cleanup: $(grep -c '^UPDATE' "$WORK/undo-cleanup.sql") statements, \
$(grep -c 'NOT RECOVERABLE' "$WORK/undo-cleanup.sql" || true) unrecoverable"
echo "migrate: $(grep -c '^UPDATE' "$WORK/undo-migrate.sql") statements"

say "10. replay both undo files"
$DC cp "$WORK/undo-migrate.sql" "$DB:/tmp/undo-migrate.sql" > /dev/null
$DC cp "$WORK/undo-cleanup.sql" "$DB:/tmp/undo-cleanup.sql" > /dev/null
psqlt -f /tmp/undo-migrate.sql > /dev/null
psqlt -f /tmp/undo-cleanup.sql > /dev/null
AFTER=$(counts); echo "$AFTER"

say "11. is it back to the baseline?"
hashes > "$WORK/hash_after.txt"
if diff -q "$WORK/hash_before.txt" "$WORK/hash_after.txt" > /dev/null; then
  echo "IDENTICAL -- user, member and group tables are exactly back to the baseline"
else
  echo "DIFFERENT:"
  diff "$WORK/hash_before.txt" "$WORK/hash_after.txt" || true
fi
echo ""
echo "baseline: $BASE"
echo "restored: $AFTER"
