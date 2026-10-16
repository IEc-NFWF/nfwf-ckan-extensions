# ckanext-nfwf_permissions

NFWF user roles, permissions and account approval — **Task 125**.

> **Status: implemented against the database.** Every action below reads and
> writes real data. The signatures, parameters and response shapes are unchanged
> from the stub release they replaced, so anything built against those keeps
> working — the only difference is that the `"stub": true` marker is gone.

This exists so the user management screen and the Manage Roles modal are not
blocked waiting on the roles backend.

**Not deployed anywhere.** This extension exists only on the
`task-125-roles-permissions` branch — it is on no branch that staging or
production deploys, so nothing here describes a running system. Local
development is the exception, where it is enabled and everything in this
document applies.

Two steps, not one: the branch has to reach a deployed environment, and
`nfwf_permissions` has to be added to `CKAN__PLUGINS` there; see
[Development](#development). The second activates the permission matrix for
every user at once, so it is worth doing deliberately and on its own.

---

## Calling the API

Over HTTP, like any CKAN action:

```
GET  /api/3/action/nfwf_user_list?statuses=needs_review,active&limit=20
GET  /api/3/action/nfwf_role_options
POST /api/3/action/nfwf_user_role_set      {"id": "...", "role": "...", ...}
POST /api/3/action/nfwf_user_approve       {"id": "..."}
```

`nfwf_user_list`, `nfwf_user_role_show` and `nfwf_role_options` are marked
side-effect-free, so they work over `GET`. The rest are `POST` only.

From Python:

```python
toolkit.get_action(u'nfwf_user_list')(context, {u'limit': 20})
```

CKAN wraps every response in its usual envelope:

```json
{ "help": "...", "success": true, "result": { ... } }
```

Validation failures come back as HTTP 409 with per-field messages:

```json
{ "success": false,
  "error": { "__type": "Validation Error",
             "program_ids": ["Program Administrator must be assigned at least one program."] } }
```

## Authorization

A Platform Administrator *is* a CKAN sysadmin — CKAN's authorization
short-circuits on the `sysadmin` flag before this extension's auth functions run,
so they get through everything automatically.

The rest of the API splits in two, and the split is the redesign document's:

| Actions | Who |
|---|---|
| `nfwf_user_list`, `nfwf_user_role_show`, `nfwf_user_role_set`, `nfwf_role_options` | Platform Administrators, **and Program Administrators within their own program** |
| `nfwf_user_approve`, `nfwf_user_reject`, `nfwf_user_deactivate` | Platform Administrators only |

The document lists "Assign user permissions for their program-associated
grants/program reader" under Program Administrator, and lists "Approve
new/remove user accounts" under Platform Administrator alone. Everyone else gets
`NotAuthorized` (HTTP 403).

**What "within their own program" means, exactly** — a Program Administrator:

- sees only accounts **all** of whose assignments sit inside a program they
  administer, **plus** accounts with no assignment at all (otherwise they could
  never find a new registration in order to give it a first role);
- does **not** see an account that also holds an assignment elsewhere — most
  production accounts are currently like this, because one-role-per-user
  postdates the data. Requiring the whole account rather than any one row is
  deliberate: `nfwf_user_role_set` replaces assignments wholesale, so a partial
  view would mean either a save that cannot succeed or one that silently
  deletes the half the caller could not see. Resolving those accounts is a
  Platform Administrator's job and the migration report lists them;
- never sees, and cannot act on, a Platform Administrator — even one whose
  retained program rows fall inside their scope;
- may assign only **Grant Editor** and **Program Reader/Member**, and only to
  their own programs and the grants under them;
- gets `ObjectNotFound` (404), not `NotAuthorized`, for an account outside that
  scope. Deliberate: a 403 would confirm the account exists, and this screen is
  a list of real names and email addresses.

Each of those is one sentence of the redesign read a particular way, and each is
written in exactly one place. `roles.py` opens with **Where this code interprets
the redesign** — an index from the sentence to the function that decides it, so
a different reading is a rewrite of one short body rather than a hunt for the
three places that had to agree.

One core action is deliberately **not** Platform-Administrator-only:
`user_autocomplete` is open to Program Administrators as well. They are allowed
to add Grant Editors to the grants in their program and Program Readers to the
program itself, and the member screens have no user picker but that one — so
without it they would hold a permission they could never use. Core `user_list`
stays closed, which is the distinction: they can look up a named person, not
browse the whole directory. See `logic/auth.py`.

### What each role can read

Authorization above decides who reaches the *API*. What they can **see** is a
separate mechanism: CKAN's `IPermissionLabels`, implemented in `labels.py`. A
label is written into each dataset's Solr document at index time, and each user
carries a set of labels; a dataset is visible when the two sets intersect.

| Role | Private datasets it can read | Label |
|---|---|---|
| Platform Administrator | all | (sysadmin short-circuit, no label needed) |
| Program Administrator | **every grant under any program** | `in-any-program` |
| Program Reader/Member | grants under the programs they are assigned to | `program-<id>` |
| Grant Editor | the grants they hold a row on | CKAN's own `member-<org_id>` |

The second row is the one that surprises people, so it is worth being explicit
that it is a requirement rather than a convenience. The redesign document lists
under Program Administrator:

> View/read datasets and resources under other programs (no editing capability)

Both halves were measured against production data on 2026-09-25. A Program
Administrator reading a private dataset in a program they do **not** administer:
`package_show` and `resource_show` allowed; `package_update`, `package_delete`,
`package_patch`, `resource_create`, `resource_update` and `resource_delete` all
refused. Of 20 private datasets, 19 sit under a program and carry the label; the
one whose grant has no program stays Platform-Administrator-only, which follows
the same sentence — a grant under no program is not "under other programs".

Two properties worth knowing rather than rediscovering:

- **The breadth is automatic.** A new program's private datasets become readable
  by every existing Program Administrator the moment a grant is filed under it.
  No per-program decision is taken, and nothing re-asks the question. The
  document intends this, but it should be intended knowingly.
- **Labels are frozen at index time.** Changing a grant's program does not move
  its datasets' labels until something reindexes them — which is why
  `_reindex_if_program_changed` exists, and why a Solr failure during that move
  now warns the administrator rather than only the log.

---

## Vocabulary

Do not hard-code these labels — get them from `nfwf_role_options`, so renaming a
role stays a backend change.

| Role value | Label | Assigned to |
|---|---|---|
| `platform_admin` | Platform Administrator | nothing (site-wide) |
| `program_admin` | Program Administrator | one or more programs |
| `program_reader` | Program Reader/Member | one or more programs |
| `grant_editor` | Grant Editor | one or more grants |

A user holds **exactly one** role. Grant Member and Grant Admin are retired and
rejected if submitted.

One role per user is a **conflict-of-interest control**, confirmed by the
product owner in August 2026 — which is why the guards refuse the combination
outright rather than resolving it silently.

### How a grant knows its program

Through the `owner_group` extra on the grant organization, holding the program
group's id. Three things read it: the permission labels in `labels.py`, a
Program Administrator's reach in `roles.administered_scope`, and the program
facet `ckanext-nfwf_fields` builds at index time.

A CKAN `Member` row joining one group to another is refused — see
`_assert_no_group_hierarchy` for the hole that closes.

| Status value | Label | Shown by default |
|---|---|---|
| `needs_review` | Needs Review | yes |
| `active` | Active | yes |
| `deactivated` | Deactivated | no — needs the "Include Deactivated Accounts?" toggle |
| `rejected` | Account request rejected | no — needs the "Include Rejected Accounts?" toggle |

Terminology: a CKAN **organization** is a *Grant*; a CKAN **group** is a
*Program*. The code uses the NFWF words, so `roles.py` talks about grants and
programs while the queries underneath address `group` rows.

### Where the decisions live

Comments in this extension refer to decisions rather than restating them —
"settled 2026-08-19", "accepted deliberately". Those refer to the Task 125
design document and the Teams thread it summarizes, which are **not in this
repository**. If you are reading a comment that leans on a decision you cannot
find, ask the maintainers or the NFWF product owner; the substance is meant to be stated inline,
so a missing reference should never leave you unable to follow the reasoning. If
it does, that is a bug in the comment.

Counts are deliberately **not** quoted in comments — they go stale within days.
`ckan nfwf-permissions migrate-roles` prints the current numbers for anything a
comment describes qualitatively.

---

## Actions

### `nfwf_user_list`

Rows for the user management table.

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `q` | string | — | matches name, display name or email |
| `statuses` | list of strings | `["needs_review", "active"]` | the two mockup toggles |
| `role` | string | — | one role value |
| `program_id` | string | — | users assigned to that program |
| `grant_id` | string | — | users assigned to that grant |
| `limit` | int | `20` | maximum `100` |
| `offset` | int | `0` | |

Lists accept either a real JSON array or a comma-separated string.

```json
{
  "count": 6,
  "limit": 20,
  "offset": 0,
  "results": [
    {
      "id": "fixture-user-reditor",
      "name": "reditor",
      "display_name": "Sample Editor",
      "email": "editor@example.org",
      "status": "active",
      "status_label": "Active",
      "last_login": "2026-04-07T11:00:00",
      "role": "grant_editor",
      "role_label": "Grant Editor",
      "dual_scope": false,
      "programs": [],
      "grants": [
        { "id": "fixture-grant-10001",
          "name": "grant-10001-example-conservation-district",
          "title": "Grant 10001 (Example Conservation District)",
          "program_id": "fixture-program-ncrf" }
      ]
    }
  ]
}
```

`count` is the total number of matches **before** paging — use it for the pager,
not `len(results)`.

Mockup column → response field:

| Column | Field |
|---|---|
| Name | `display_name` |
| Email | `email` |
| Status | `status_label` (color off `status`) |
| Last Login | `last_login` |
| Role | `role_label` — flag the row when `dual_scope` is true, see below |
| Assigned Grants | `grants[].title`, as a bulleted list |

**`dual_scope` means the role shown is not the whole story.** The account holds
both a program and a grant assignment, which one-role-per-user forbids and most
of the existing data does anyway.

It is deliberately broader than the migration report's field of the same name,
and the two are *supposed* to disagree. This one describes the data as it
stands, so it counts any program row. The report describes what a migration
would leave behind, and a legacy Program Member row is dropped rather than
carried over, so it no longer puts an account in two scopes there. Until the
migration is run this field is the one that matches what an administrator sees
on the screen.

It matters because `role` is resolved by precedence and names only one of the
two. An account holding a program `member` row and a grant `editor` row reports
as **Program Reader/Member** — the read-only role — while holding a Grant
Editor's write permissions. Showing that label unqualified tells an
administrator the account is read-only when it is not, which is the wrong
direction for this table to be wrong in.

Surfaced rather than resolved in code: changing the precedence would just pick
a different wrong answer, and which side such an account keeps is a decision
for a Platform Administrator. Pair it with `role` before warning — a Platform
Administrator's assignments are retained but never consulted, so `dual_scope`
can be true for them without meaning anything.

`last_login` is ISO 8601; the mockup's `5/21/2025 11:00 am` is the UI's
formatting job. `last_login`, `role` and `role_label` are `null` when unset —
the mockup wants those cells blank.

**Why this is not core `user_list`:** core filters out deleted users in SQL, and
both Deactivated and Rejected are stored as CKAN's `deleted` state. Core also
has no status or role filter. The two mockup toggles cannot be served by it.

### `nfwf_role_options`

Everything the modal needs to render its controls.

```json
{
  "roles": [
    { "value": "platform_admin", "label": "Platform Administrator", "assigned_to": null },
    { "value": "program_admin",  "label": "Program Administrator",  "assigned_to": "program" },
    { "value": "program_reader", "label": "Program Reader/Member",  "assigned_to": "program" },
    { "value": "grant_editor",   "label": "Grant Editor",           "assigned_to": "grant" }
  ],
  "programs": [
    { "id": "fixture-program-ncrf",
      "name": "national-coastal-resilience-fund",
      "title": "National Coastal Resilience Fund" }
  ]
}
```

Use `assigned_to` to drive the conditional part of the form: `program` shows the
program checkboxes, `grant` shows the grant picker, `null` shows neither.

Grants are deliberately **not** returned here — there are 571 of them. Use
`nfwf_grant_list` below, which pages per program.

The response above is what a **Platform Administrator** gets. For a Program
Administrator both lists are narrowed to what they may actually save: `roles`
drops Platform Administrator and Program Administrator, and `programs` contains
only the programs they administer. Render whatever comes back rather than a
hard-coded list of four — the modal is then correct for both callers without
knowing which it is talking to, and `nfwf_user_role_set` refuses the rest anyway.

### `nfwf_grant_list`

The Grant Editor picker's grants. **This pages, you group.**

```
GET /api/3/action/nfwf_grant_list?program_id=<id>&limit=20&offset=0
GET /api/3/action/nfwf_grant_list?unassigned=true
GET /api/3/action/nfwf_grant_list?q=audubon
```

```json
{
  "count": 487,
  "limit": 20,
  "offset": 0,
  "results": [
    { "id": "fixture-grant-10001",
      "name": "grant-10001-example-conservation-district",
      "title": "Grant 10001 (Example Conservation District)",
      "program_id": "fixture-program-ncrf" }
  ]
}
```

| Parameter | Meaning |
|---|---|
| `program_id` | grants belonging to that program |
| `unassigned` | instead, grants belonging to no program |
| `q` | match the grant's title or name |
| `limit` / `offset` | default 20, maximum 100 |

**Why per program rather than one flat list.** The sizes are lopsided — one
program holds 487 of the 571 grants against 41 and 12 for the other two. A page
of a flat list can straddle two programs, and the screen then cannot tell a
finished group from a truncated one. Asking per program gives each group its own
`count` and its own "show more", which is what US 0126 slide 5 describes.

**Grouping is yours.** Every record carries `program_id`, and you already have
the program list from `nfwf_role_options`, so a nested response would only
re-encode what the flat one says.

**The fourth "(no program)" group.** `unassigned=true` returns the grants that
belong to no program. It returns nothing to a Program Administrator — a grant
under no program is administered by nobody — so **omit that group for them
rather than rendering it empty**. An absent group there is correct, not a
failed load.

Everything is narrowed to what the caller may actually assign, so a Program
Administrator asking for another program's grants gets an empty list rather
than a refusal.

### `nfwf_user_role_show`

`id` (user id or name) → the same shape `nfwf_user_role_set` returns. Use it to
pre-select the modal when it opens.

### `nfwf_user_role_set`

The single entry point for the modal's Save button. **Replaces** the user's role
rather than adding to it.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | user id or name |
| `role` | string | yes | one role value |
| `program_ids` | list of strings | for the two program roles | rejected for other roles |
| `grant_ids` | list of strings | for `grant_editor` | rejected for other roles |

```json
{
  "user_id": "fixture-user-reditor",
  "user_name": "reditor",
  "display_name": "Sample Editor",
  "role": "program_reader",
  "role_label": "Program Reader/Member",
  "dual_scope": false,
  "programs": [ { "id": "...", "name": "...", "title": "..." } ],
  "grants": [],
  "assignments_in_effect": true,
}
```

**`assignments_in_effect` matters for the table.** Promoting someone to
`platform_admin` does *not* discard their program and grant assignments — they
stay on the record and are simply never consulted, so demoting them later
restores exactly what they had. For a Platform Administrator the flag is `false`,
meaning "these are stored but inert". The mockup shows that row's Assigned Grants
cell blank, so **hide the assignments when `assignments_in_effect` is `false`.**

Switching between the *other* roles does clear the assignments that no longer
apply, because for those roles the assignment is the permission.

### `nfwf_user_approve` / `nfwf_user_reject` / `nfwf_user_deactivate`

Each takes `id` and returns the updated user, in the same shape as a
`nfwf_user_list` row — so the table row can be replaced from the response
without a refetch.

| Action | Resulting status |
|---|---|
| `nfwf_user_approve` | `active` |
| `nfwf_user_reject` | `rejected` |
| `nfwf_user_deactivate` | `deactivated` |

**No transition is currently refused** — approving an already-active account, or
rejecting one that has been active for a year, both succeed. Whether some of
those should be errors is an open question; see below. Don't rely on the API to
stop a nonsensical transition yet, so keep the ellipsis menu offering only the
actions that make sense for the row's status.

---

## What the writes do

`nfwf_user_role_set`, `nfwf_user_approve`, `nfwf_user_reject` and
`nfwf_user_deactivate` persist. A role change rewrites the user's membership
rows, or the `sysadmin` flag for Platform Administrator; a status change writes
`user.state` and, for the two "gone" statuses, a marker in `plugin_extras`.
Responses are safe to swap straight into a table row, and a refresh now shows
the same thing.

Two behaviors worth knowing:

- **A role change replaces, it does not add.** A user holds one role, so setting
  a program role clears any grant assignments and vice versa. Promoting someone
  to Platform Administrator is the exception: their assignments are *retained*
  and simply not consulted, so demoting them restores what they had. The
  response says which case you are in via `assignments_in_effect`.
- **A partial failure writes nothing.** One unknown id in `program_ids` fails
  the whole call rather than saving the role with the ids it recognized.

Error paths:

| Request | Response |
|---|---|
| unknown user `id` | 404 `Not Found` |
| unknown `program_ids` / `grant_ids` | 409, per-field `Unknown ids: ...` |
| assignments that don't match the role | 409, per-field message |
| role missing, or a retired role | 409, per-field message |
| caller is not a Platform Administrator | 403 `Not Authorized` |

---

## Open questions

*(none — the grant picker gap recorded here was closed on 2026-09-30 by
`nfwf_grant_list`; the two decisions behind it are in Settled below.)*

---

## Settled

Answered by the product owner on 2026-09-28. Recorded here so the reasoning
survives, and so nothing in the code still reads as awaiting a decision.

| Question | Answer | Where it lives |
|---|---|---|
| May a Program Administrator appoint a peer Program Administrator? | **No.** The document reserves peer appointment to Platform Administrators with an explicit parenthetical and says nothing of the kind for Program Administrators; naming it in one place and not the other excludes it. | `roles.PROGRAM_ADMIN_ASSIGNABLE_ROLES` |
| Do Program Administrators see accounts holding no role yet? | **Yes.** Otherwise they could never give anyone a first role, which is a permission the document grants them. | `roles.is_within_scope` |
| Must a role assignment carry at least one program or grant? | **Yes.** A role with no assignment confers nothing, so saving one is a UI slip. | `action._check_assignment_scope` |
| Do Program Administrators read private datasets in *every* program? | **Yes**, as the document asks -- and knowingly including the part the document cannot have weighed: it applies automatically to any future program the moment a grant is filed under it. | `labels.IN_ANY_PROGRAM` |
| Should an out-of-scope account answer 404 rather than 403? | **Yes.** A 403 confirms the account exists, and this screen is a list of real names and email addresses. | `action._assert_within_scope` |
| What may `nfwf_user_reject` act on? | **Accounts awaiting review only.** It used to accept any account, which made it an irreversible way to close a long-active one. | `action.nfwf_user_reject` |
| Can a deactivated account be reopened? | **Yes** -- `nfwf_user_reactivate`, added for this. Deactivation used to be one-way. | `action.nfwf_user_reactivate` |
| How many rows per page? | **A dropdown**, e.g. 5 / 10 / 20 / 50, as other table views do. Needs no API change -- all of those sit inside the 1-100 `nfwf_user_list` already accepts, and 20 stays the default per US 0117 slide 4. | `action.DEFAULT_LIMIT`, `MAX_LIMIT` |
| Should `reactivate` also undo a rejection? | **No.** Reopening a rejected *request* is approving it, and `nfwf_user_approve` already does that -- keeping them separate keeps the audit trail legible about why an account is open. | `action.nfwf_user_reactivate` |
| Does an existing **Grant Member** or **Grant Admin** row become a Grant Editor? | **No** (2026-10-13). Neither capacity exists in the new model, which has no read-only role at grant level, so each row had to become Grant Editor or nothing. It was a `decide` until the product owner answered -- and the restraint earned its keep: it is why the eight accounts holding these 61 rows were put to her at all, 49 of them one person's, rather than the access vanishing unremarked. Her answer was remove, for every one. People who turn out to need the grant are added back to it. | `migration._disposition`, `migration.DROP_RETIRED_GRANT_ROLE` |
| Does an existing **Program Member** row become a Program Reader? | **No** (2026-10-02). It was a stopgap: the role was handed out so a dataset could be filed under a program, back when a user's assignments were the only link between a grant and its program. `owner_group` replaced that, so the rows are dropped. Program Reader is not retired -- it is still a program `member` row -- but it is assigned deliberately from here, to the people who review a program, rather than inherited. | `migration._disposition`, `migration.DROP_LEGACY_MEMBERSHIP` |

### The account status machine

| Action | From | To |
|---|---|---|
| `nfwf_user_approve` | anything | Active |
| `nfwf_user_reject` | Needs Review **only** | Account request rejected |
| `nfwf_user_deactivate` | anything | Deactivated |
| `nfwf_user_reactivate` | Deactivated **only** | Active |

`approve` and `deactivate` stay unrestricted deliberately: `approve` is how a
rejected *request* is let in after a second look, and `deactivate` has to work
on anything that can currently be used. `reactivate` is deliberately not a way
to undo a rejection -- letting a rejected request in is approving it, and
`approve` leaves the right word in the audit trail.

## What else is in here

Beyond the API above, all landed and all layered on without a signature
changing:

- `labels.py` — `IPermissionLabels`, giving program-wide visibility of private
  datasets. Labels are written at **index time**, so a grant that changes
  program needs its datasets reindexed; the chained `organization_update` does
  that, and a bulk change needs `ckan search-index rebuild`.
- `logic/auth.py` — the permission matrix. Read its module docstring before
  changing anything there, especially the list of core functions deliberately
  left to stock CKAN.
- chained `organization_create` / `organization_update` — a grant must belong to
  a program the caller administers, enforced on create *and* update so a grant
  cannot be moved out from under its program.
- chained `member_create` / `organization_member_create` / `group_member_create`
  — reject the retired grant capacities and enforce one role per user. All three
  honour `ignore_auth`, which is load-bearing: CKAN makes the creator of a new
  organization an `admin` that way.
- `platform_or_program_admin_not_empty`, so Program Administrators face the same
  required grant fields as Platform Administrators. `ckanext-nfwf_fields`
  consumes it through a soft import and falls back to sysadmin-only if this
  extension is not installed.
- `ckan nfwf-permissions migrate-roles [--report CSV] [--apply] [--undo-file
  SQL]` — the role migration report. Dry run by default.
- `ckan nfwf-permissions cleanup [--accounts FILE] [--grants FILE] [--apply]` —
  closes accounts and deletes grants from a hand-written list. Dry run by
  default. It decides nothing: the list is the product owner's. What it adds is
  three refusals she cannot make from a spreadsheet — the site user named by
  `ckan.site_id`, a grant that still holds datasets, and a program handed in
  where a grant was meant — plus a warning on sysadmins and on anything signed
  into in the last 90 days. It also clears the `sysadmin` flag when it closes
  a Platform Administrator, which `user_delete` leaves set. See `cleanup.py`
  for why each refusal is there.

#### Applying these to a real database

`MIGRATION.md` is the order to run the two commands in, what to check
between steps, and how to reverse a run. `migrate-rehearse.sh` does the
whole sequence against a throwaway copy first, including replaying the
undo files to prove they restore the tables exactly.

The account and grant lists both commands take are **not in this repo** --
they name real people and the decisions made about their accounts. Ask the
maintainer for the current pair.

#### Undoing a run

Everything both `--apply` paths write is a CKAN soft delete, so nothing is
destroyed. That makes the data recoverable; it does not make the *run*
recoverable, and the difference is the whole reason `undo.py` exists.

`member` has no timestamp and no revision. Once a run has flipped several
hundred rows to `state='deleted'`, nothing in the table distinguishes them
from the rows that were already deleted before it started, so "put it back"
has no answer unless the ids were written down first.

So both commands write an undo script before they touch the database, and
refuse to run if they cannot. It is a plain SQL file, one statement per line,
no transaction — so a file cut short by a crash still applies as far as it
got, and running it twice is harmless:

    psql -U ckan -d ckan -f nfwf-undo-cleanup-20261013-142211.sql
    ckan search-index rebuild

Pass `--undo-file` to choose where it lands; the default is a timestamped
name in the working directory, echoed at the end of the run.

**One thing it cannot restore.** `user_delete` also removes the account's
dataset collaborations, and `package_member` has no `state` column, so those
rows are really deleted. Each one is written into the file as a comment
naming what was lost, which is the most that can honestly be offered. There
are none in the current data.

- chained `member_roles_list` — narrows the Role dropdown on both stock member
  screens to the capacities the role model actually uses: Grant Editor on a
  grant, Program Administrator and Program Reader/Member on a program. Done by
  chaining the action rather than overriding the two templates, because
  `ckanext-nfwf_theme` already overrides both and a second override would depend
  on plugin order to win. Presentation only — the guards above still decide what
  is *accepted*.

### Still to come

- Nothing from the compliance pass. The four gaps it found against the redesign
  document were closed on 2026-09-22, and the readings that were still open
  then have since been answered — see [Settled](#settled).

### Depends on `ckanext-oauth2`

Approve, reject, deactivate and promote all go through `user_update`, which that
extension used to refuse for everyone including sysadmins. That is fixed on its
`task-125-oauth2-approval` branch, along with creating new accounts as `pending`
so they can be approved at all. **These actions need that branch deployed to
work.**

## Development

Add `nfwf_permissions` to `CKAN__PLUGINS` in `.env`, then:

```bash
bin/install_src     # setup.py changed
bin/reload
```

Tests:

```bash
docker compose -f docker-compose.dev.yml exec \
  -w /srv/app/src_extensions/ckanext-nfwf_permissions \
  -e CKAN_SQLALCHEMY_URL=postgresql://ckan:ckan@db/ckan_test ckan-dev \
  pytest --ckan-ini=test.ini ckanext/nfwf_permissions/tests
```

The `-w` matters: `test.ini` and its `config:../../src/ckan/test-core.ini` reference
both resolve relative to the extension directory, not the container's default
`/srv/app`.

**Pin `CKAN_SQLALCHEMY_URL`, and not just here.** `test.ini` inherits
`sqlalchemy.url = .../ckan_test` from CKAN's `test-core.ini`, but the dev
container's `CKAN_SQLALCHEMY_URL` environment variable overrides it and points
at `.../ckan` — the **development** database. Run `pytest` without the override
and the suite operates on real data, and `clean_db` tries to `DROP` every table
in it. Every extension's `test.ini` in this repo has the same shape, so this
applies to all of them. `ckanext/nfwf_permissions/tests/conftest.py` aborts the
run if the configured database name does not end in `_test`; consider copying
that file into the other extensions.
