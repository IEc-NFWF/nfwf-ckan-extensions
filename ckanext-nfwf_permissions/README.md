# ckanext-nfwf_permissions

NFWF user roles, permissions and account approval — **Task 125**.

> **Status: API contract only.** Every action below is live and callable, validates
> its input for real, and enforces authorization for real. The bodies return
> **fixture data** mirroring the US 0117 / US 0126 mockups instead of reading the
> database. Responses carry `"stub": true` so it is obvious in the network tab.
>
> Build against these signatures now — they are not going to change. The `stub`
> key disappears when the real implementation lands; nothing should depend on it.

This exists so Tasks 117 (user management screen) and 126 (Manage Roles modal)
are not blocked waiting on the Task 125 backend.

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

**Platform Administrator only**, for every action here.

A Platform Administrator *is* a CKAN sysadmin — CKAN's authorization
short-circuits on the `sysadmin` flag before this extension's auth functions run,
so they get through automatically. Everyone else gets `NotAuthorized` (HTTP 403).

Task 117 also asks for Program Administrators to see the users in their own
program. That scoping is not implemented yet; it lands with the full permission
matrix. Until then, assume Platform Administrator only.

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
*Program*.

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
  "stub": true,
  "results": [
    {
      "id": "fixture-user-dyork",
      "name": "dyork",
      "display_name": "Dawn York",
      "email": "dyork5713@gmail.com",
      "status": "active",
      "status_label": "Active",
      "last_login": "2026-04-07T11:00:00",
      "role": "grant_editor",
      "role_label": "Grant Editor",
      "programs": [],
      "grants": [
        { "id": "fixture-grant-66991",
          "name": "grant-66991-cape-fear-resource-conservation-development",
          "title": "Grant 66991 (Cape Fear Resource Conservation & Development)",
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
| Role | `role_label` |
| Assigned Grants | `grants[].title`, as a bulleted list |

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
  "stub": true,
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
  "user_id": "fixture-user-dyork",
  "user_name": "dyork",
  "display_name": "Dawn York",
  "role": "program_reader",
  "role_label": "Program Reader/Member",
  "programs": [ { "id": "...", "name": "...", "title": "..." } ],
  "grants": [],
  "assignments_in_effect": true,
  "stub": true
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

## What the writes do while this is a stub

`nfwf_user_role_set`, `nfwf_user_approve`, `nfwf_user_reject` and
`nfwf_user_deactivate` authorize and validate for real, then **return the
correct "after" state without persisting anything.** The fixture data is
deep-copied per call, so a write cannot even leak into the next request in the
same worker.

For the UI that means: optimistic updates render correctly and the response is
safe to swap into the table row, but **a refresh reverts everything.** Build and
demo the flow against these; just don't write a test that asserts a change
survives a reload.

Error paths *are* real, so build against them:

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
4. **Program Administrator scope for the user table** — Task 117 mentions it;
   deferred to the full permission matrix.
5. **Which status transitions are legal?** Nothing currently stops
   `nfwf_user_reject` on an account that has been active for a year, or
   `nfwf_user_approve` on one that was already approved. Rejection reads like it
   is meant for *requests*, so rejecting a long-active account is plausibly a
   misclick that should be a deactivation instead. Needs a decision from Emily
   before the real implementation enforces anything; until then the API accepts
   any of them.

## Still to come in Task 125

Layered on top of this without any signature changing:

- `IPermissionLabels` — program-wide visibility of private datasets
- the full permission matrix in `logic/auth.py`
- chained membership actions rejecting the retired grant capacities
- validator so Program Admins face the same required grant fields as Platform Admins
- `ckan nfwf-permissions migrate-roles [--dry-run] [--report CSV]`
- two fixes in `ckanext-oauth2`: allow sysadmins to edit user records, and create
  new accounts as pending. **Approve, reject, deactivate and promote cannot work
  against the real database until the first of those lands** — they all go
  through `user_update`, which the login extension currently blocks for
  everyone, sysadmins included.

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
