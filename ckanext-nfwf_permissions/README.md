# ckanext-nfwf_permissions

NFWF user roles, permissions and account approval — **Task 125**.

> **Status: implemented against the database.** Every action below reads and
> writes real data. The signatures, parameters and response shapes are unchanged
> from the stub release they replaced, so anything built against those keeps
> working — the only difference is that the `"stub": true` marker is gone.

This exists so the user management screen and the Manage Roles modal are not
blocked waiting on the roles backend.

**Not yet enabled anywhere.** Add `nfwf_permissions` to `CKAN__PLUGINS` before
any of it takes effect; see [Development](#development). Turning it on activates
the permission matrix for every user at once, so it is worth doing as its own
deliberate step.

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
design document and the Teams thread it summarises, which are **not in this
repository**. If you are reading a comment that leans on a decision you cannot
find, ask Janusz Strzepek or Emily; the substance is meant to be stated inline,
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
| Status | `status_label` (colour off `status`) |
| Last Login | `last_login` |
| Role | `role_label` — flag the row when `dual_scope` is true, see below |
| Assigned Grants | `grants[].title`, as a bulleted list |

**`dual_scope` means the role shown is not the whole story.** The account holds
both a program and a grant assignment, which one-role-per-user forbids and most
of the existing data does anyway — `ckan nfwf-permissions migrate-roles` counts
them, and it asks the same question this field answers, so the two cannot
disagree.

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

Grants are deliberately **not** returned here — see the open questions.

The response above is what a **Platform Administrator** gets. For a Program
Administrator both lists are narrowed to what they may actually save: `roles`
drops Platform Administrator and Program Administrator, and `programs` contains
only the programs they administer. Render whatever comes back rather than a
hard-coded list of four — the modal is then correct for both callers without
knowing which it is talking to, and `nfwf_user_role_set` refuses the rest anyway.

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

Two behaviours worth knowing:

- **A role change replaces, it does not add.** A user holds one role, so setting
  a program role clears any grant assignments and vice versa. Promoting someone
  to Platform Administrator is the exception: their assignments are *retained*
  and simply not consulted, so demoting them restores what they had. The
  response says which case you are in via `assignments_in_effect`.
- **A partial failure writes nothing.** One unknown id in `program_ids` fails
  the whole call rather than saving the role with the ids it recognised.

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

1. **Grant selection in the modal.** Programs are a three-item checkbox list, so
   `nfwf_role_options` returns them inline. Production has roughly **570 grants**,
   which is not a checkbox list. Suggest a searchable picker built on core
   `organization_autocomplete`, or a paged `organization_list`; a dedicated
   `nfwf_grant_list` can be added if neither fits. Needs a UI decision.
2. **Minimum one assignment.** `nfwf_user_role_set` currently *requires* at least
   one program for a program role and one grant for `grant_editor`, on the
   grounds that a Program Administrator of no programs has no permissions and is
   almost certainly a UI slip. Assumption, not a stated requirement — easy to
   relax.
3. **Reactivating a deactivated account.** Not in the mockups. If the ellipsis
   menu needs it, it is a one-line addition (`nfwf_user_reactivate`).
4. **Program Administrator scope for the user table** — implemented 2026-09-22;
   see [Authorization](#authorization). Two readings of it are still open and
   both are one-line changes in `roles.py`: whether a Program Administrator may
   appoint a *peer* Program Administrator (currently **no**, the narrower reading
   — the document names only Grant Editor and Program Reader), and whether they
   should see accounts that hold no assignment yet (currently **yes**, because
   otherwise they can never give anyone a first role).
5. **Which status transitions are legal?** Nothing currently stops
   `nfwf_user_reject` on an account that has been active for a year, or
   `nfwf_user_approve` on one that was already approved. Rejection reads like it
   is meant for *requests*, so rejecting a long-active account is plausibly a
   misclick that should be a deactivation instead. Needs a decision from Emily
   before the real implementation enforces anything; until then the API accepts
   any of them.

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
- `ckan nfwf-permissions migrate-roles [--report CSV] [--apply]` — the role
  migration report. Dry run by default.

- chained `member_roles_list` — narrows the Role dropdown on both stock member
  screens to the capacities the role model actually uses: Grant Editor on a
  grant, Program Administrator and Program Reader/Member on a program. Done by
  chaining the action rather than overriding the two templates, because
  `ckanext-nfwf_theme` already overrides both and a second override would depend
  on plugin order to win. Presentation only — the guards above still decide what
  is *accepted*.

### Still to come

- Nothing from the compliance pass. The four gaps it found against the redesign
  document were closed on 2026-09-22; what is left is the two open readings in
  [Open questions](#open-questions) 4, which need NFWF rather than code.

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
