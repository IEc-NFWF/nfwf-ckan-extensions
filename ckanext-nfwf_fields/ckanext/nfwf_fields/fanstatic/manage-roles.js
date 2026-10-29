/*
 * Manage Roles modal on /user.
 *
 * Saves through nfwf_user_role_set in ckanext-nfwf_permissions, which owns the
 * role model.  Roles go on the wire as slugs and scopes as ids; the labels are
 * for reading only.  A user holds exactly one role, so saving replaces whatever
 * they held rather than adding to it.
 *
 * Programs are rendered up front and filtered here -- there are a handful.
 * Grants are not: they are grouped by program and paged in from nfwf_grant_list,
 * and the chosen ones are kept above the groups so a new query cannot silently
 * drop a selection.
 */
(function () {
  'use strict';

  // Grants per group per request
  var GRANT_PAGE = 10;

  // Existing assignments for every row, keyed by user name, which the modal
  // opens on; and what redrawing a row's Role and assignment cells needs from
  // the template -- see drawRoleCells.  Read before the guard below because the
  // status actions use both: deactivating removes every role.  Each degrades to
  // empty on a page that does not render it.
  var assignments = readAssignments();
  var rowMeta = readJson('nfwf-role-row-meta');

  // The account status actions share the kebab menu with Manage Roles but not the
  // modal, and the two are gated on different auth functions -- account status is
  // Platform Administrator only, role assignment is not.  Wired before the guard
  // below so the menu keeps working on a page with no modal.  Reads ahead of its
  // own definition on purpose: function declarations hoist.
  wireStatusActions();

  var modal = document.querySelector('.nfwf-roles-modal');
  if (!modal) { return; }

  var backdrop = document.querySelector('.nfwf-roles-backdrop');
  var form = modal.querySelector('.nfwf-roles-form');
  var select = modal.querySelector('.nfwf-roles-select');
  var scopeBox = modal.querySelector('.nfwf-roles-scope');
  var tree = modal.querySelector('.nfwf-roles-tree');
  var search = modal.querySelector('.nfwf-roles-search');
  var empty = modal.querySelector('.nfwf-roles-empty');
  var subject = modal.querySelector('[data-nfwf-roles-subject]');
  var note = modal.querySelector('.nfwf-roles-note');
  var saveBtn = modal.querySelector('.nfwf-roles-save');
  var programList = tree.querySelector('.nfwf-roles-programs');
  var grantPicker = tree.querySelector('.nfwf-roles-grant-picker');
  var grantSelected = tree.querySelector('.nfwf-roles-grants-selected');
  var grantHint = tree.querySelector('.nfwf-roles-hint');
  var programs = toArray(tree.querySelectorAll('.nfwf-roles-program'));
  // One per program, plus "(no program)", each paging on its own: the action
  // pages, this groups.  The sections are rendered by the template.
  var grantGroups = toArray(tree.querySelectorAll('.nfwf-roles-grant-group'))
    .map(function (section) {
      return {
        section: section,
        programId: section.getAttribute('data-program-id'),
        unassigned: section.getAttribute('data-unassigned') === 'true',
        list: section.querySelector('.nfwf-roles-grants-results'),
        countLabel: section.querySelector('.nfwf-roles-grant-group-count'),
        more: section.querySelector('.nfwf-roles-grant-more'),
        offset: 0,
        count: 0
      };
    });

  var lastFocus = null;
  // The one role the open user holds: {role, program_ids, grant_ids, grants}.
  var current = emptyAssignment();
  // Grants ticked in this session: id -> title.  Kept in JS because the groups
  // are rebuilt on every search.
  var chosenGrants = {};
  var searchTimer = null;
  var searchSeq = 0;
  // Set once the dual-scope warning has been shown for the open account, so the
  // second press of Save goes through.  Reset whenever the modal reopens or the
  // role changes, because both change what saving would discard.
  var dualScopeAcknowledged = false;

  function toArray(nodes) {
    return Array.prototype.slice.call(nodes);
  }

  function emptyAssignment() {
    return {role: '', program_ids: [], grant_ids: [], grants: [],
            dual_scope: false};
  }

  // Existing assignments for every row on the page, keyed by user name.
  function readAssignments() {
    return readJson('nfwf-roles-assignments');
  }

  // A role save's record or a status action's row -- both carry these fields --
  // in the shape the modal opens on.  dual_scope is re-read rather than
  // cleared: a role change can leave the account holding both scopes again,
  // so the next Save must warn afresh.
  function selectionFrom(record) {
    return {
      role: record.role || '',
      program_ids: (record.programs || []).map(function (p) { return p.id; }),
      grant_ids: (record.grants || []).map(function (g) { return g.id; }),
      grants: (record.grants || []).map(function (g) {
        return {id: g.id, title: g.title || g.name};
      }),
      dual_scope: !!record.dual_scope
    };
  }

  // The page hands JS its data in <script type="application/json"> blocks rather
  // than data attributes; a missing or malformed one degrades to empty.
  function readJson(id) {
    var blob = document.getElementById(id);
    if (!blob) { return {}; }
    try {
      return JSON.parse(blob.textContent) || {};
    } catch (e) {
      return {};
    }
  }

  // -- API ----------------------------------------------------------------

  // CKAN puts the token in a pair of metas; see ckan/templates/base.html.
  function csrfToken() {
    var field = document.querySelector('meta[name=csrf_field_name]');
    if (!field) { return null; }
    var meta = document.querySelector('meta[name="' + field.content + '"]');
    return meta ? meta.content : null;
  }

  function apiUrl(action) {
    return '/api/3/action/' + action;
  }

  function apiGet(action, params) {
    var query = Object.keys(params).map(function (key) {
      return encodeURIComponent(key) + '=' + encodeURIComponent(params[key]);
    }).join('&');
    return fetch(apiUrl(action) + '?' + query, {
      credentials: 'same-origin',
      headers: {'Accept': 'application/json'}
    }).then(readBody);
  }

  function apiPost(action, payload) {
    var headers = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };
    var token = csrfToken();
    if (token) { headers['X-CSRFToken'] = token; }

    return fetch(apiUrl(action), {
      method: 'POST',
      credentials: 'same-origin',
      headers: headers,
      body: JSON.stringify(payload)
    }).then(readBody);
  }

  // CKAN answers with {success, result} or {success, error}; a 403 from the
  // auth function and a 409 from validation both carry a useful body.
  function readBody(response) {
    return response.json().then(function (body) {
      if (response.ok && body && body.success) { return body.result; }
      throw new Error(errorMessage(body, response.status));
    }, function () {
      throw new Error('The server returned an unreadable response (HTTP ' +
                      response.status + ').');
    });
  }

  function errorMessage(body, status) {
    var error = body && body.error;
    if (!error) { return 'Request failed (HTTP ' + status + ').'; }
    if (error.message) { return error.message; }

    // Validation errors arrive keyed by field, e.g. {grant_ids: ["Unknown ids: x"]}.
    var parts = [];
    Object.keys(error).forEach(function (key) {
      if (key === '__type') { return; }
      var value = error[key];
      parts.push(Array.isArray(value) ? value.join(' ') : String(value));
    });
    return parts.length ? parts.join(' ') : 'Request failed (HTTP ' + status + ').';
  }

  // -- programs -----------------------------------------------------------

  function programBoxes() {
    return toArray(tree.querySelectorAll('.nfwf-roles-check-program'));
  }

  function filterPrograms() {
    var term = search.value.trim().toLowerCase();
    var anyVisible = false;

    programs.forEach(function (li) {
      var show = !term || li.getAttribute('data-title').indexOf(term) !== -1;
      li.hidden = !show;
      if (show) { anyVisible = true; }
    });

    empty.hidden = anyVisible;
  }

  // -- grants -------------------------------------------------------------

  function grantRow(id, title, checked) {
    var li = document.createElement('li');
    li.className = 'nfwf-roles-grant';

    var label = document.createElement('label');
    var box = document.createElement('input');
    box.type = 'checkbox';
    box.className = 'nfwf-roles-check nfwf-roles-check-grant';
    box.value = id;
    box.checked = Boolean(checked);
    box.addEventListener('change', function () {
      if (box.checked) {
        chosenGrants[id] = title;
      } else {
        delete chosenGrants[id];
      }
      hideNote();
      renderChosenGrants();
      // A row unticked in the selected list must lose its tick in the results
      // list too, and vice versa.
      syncGrantResults();
    });

    var text = document.createElement('span');
    text.textContent = title;

    label.appendChild(box);
    label.appendChild(text);
    li.appendChild(label);
    return li;
  }

  function renderChosenGrants() {
    grantSelected.textContent = '';
    Object.keys(chosenGrants).forEach(function (id) {
      grantSelected.appendChild(grantRow(id, chosenGrants[id], true));
    });
  }

  function isChosen(id) {
    return Object.prototype.hasOwnProperty.call(chosenGrants, id);
  }

  function syncGrantResults() {
    toArray(grantPicker.querySelectorAll(
      '.nfwf-roles-grants-results .nfwf-roles-check-grant'))
      .forEach(function (box) {
        box.checked = isChosen(box.value);
      });
  }

  function resetGroup(group) {
    group.offset = 0;
    group.count = 0;
    group.list.textContent = '';
    group.countLabel.textContent = '';
    group.more.hidden = true;
    group.more.disabled = false;
    group.section.hidden = true;
  }

  // Appends the group's next page.  `seq` is the search that asked for it, so a
  // slow reply to an old query -- or a "Show more" pressed just before the query
  // changed -- cannot land in the new results.
  function loadGroup(group, seq) {
    var params = {limit: GRANT_PAGE, offset: group.offset};
    var term = search.value.trim();
    if (term) { params.q = term; }
    if (group.unassigned) {
      params.unassigned = 'true';
    } else {
      params.program_id = group.programId;
    }
    group.more.disabled = true;

    return apiGet('nfwf_grant_list', params).then(function (page) {
      if (seq !== searchSeq) { return; }
      var records = page.results || [];
      records.forEach(function (record) {
        // Chosen grants are drawn ticked rather than skipped, so the count
        // beside the program stays true.
        group.list.appendChild(
          grantRow(record.id, record.title || record.name, isChosen(record.id)));
      });
      group.offset += records.length;
      group.count = page.count || 0;
      group.countLabel.textContent = '(' + group.count + ')';
      group.more.hidden = !records.length || group.offset >= group.count;
      group.more.disabled = false;
      // An empty group is hidden rather than drawn empty.  For "(no program)"
      // that is what the contract asks: a Program Administrator is given
      // nothing there by design, so an absent group is correct.
      group.section.hidden = group.count === 0;
    });
  }

  // Every group from its first page: when the picker is shown, and per search.
  function loadGrantGroups() {
    var seq = ++searchSeq;
    grantGroups.forEach(resetGroup);
    empty.hidden = true;
    grantHint.textContent = 'Loading…';
    grantHint.hidden = false;

    Promise.all(grantGroups.map(function (group) {
      return loadGroup(group, seq);
    }))
      .then(function () {
        if (seq !== searchSeq) { return; }
        grantHint.hidden = true;
        empty.hidden = grantGroups.some(function (group) {
          return !group.section.hidden;
        });
      })
      .catch(function (error) {
        if (seq !== searchSeq) { return; }
        grantHint.textContent = error.message;
        grantHint.hidden = false;
      });
  }

  // -- role selection -----------------------------------------------------

  function currentScope() {
    var option = select.options[select.selectedIndex];
    return (option && option.getAttribute('data-scope')) || '';
  }

  function clearSelections() {
    programBoxes().forEach(function (box) { box.checked = false; });
    chosenGrants = {};
    grantSelected.textContent = '';
    // Bumped so any group request still in flight is dropped on arrival.
    searchSeq++;
    grantGroups.forEach(resetGroup);
  }

  // Pre-select what this user already holds -- but only while the role on
  // screen is the one they hold.  Picking a different role is a replacement, so
  // it starts from nothing.
  function applyAssignments() {
    if (select.value !== current.role) { return; }
    var scope = currentScope();

    if (scope === 'program') {
      var held = current.program_ids || [];
      programBoxes().forEach(function (box) {
        box.checked = held.indexOf(box.value) !== -1;
      });
    } else if (scope === 'grant') {
      (current.grants || []).forEach(function (grant) {
        chosenGrants[grant.id] = grant.title;
      });
      renderChosenGrants();
    }
  }

  function applyScope() {
    var scope = currentScope();
    var scoped = scope === 'program' || scope === 'grant';

    tree.setAttribute('data-scope', scope);
    // Platform Administrator is site-wide, so it has nothing to scope.
    scopeBox.hidden = !scoped;
    programList.hidden = scope !== 'program';
    grantPicker.hidden = scope !== 'grant';
    empty.hidden = true;

    clearSelections();
    dualScopeAcknowledged = false;
    search.value = '';
    if (scope === 'program') {
      filterPrograms();
    } else if (scope === 'grant') {
      loadGrantGroups();
    }
    // Synchronous, so the held grants are chosen before any group page lands
    // and those rows are drawn ticked.
    applyAssignments();

    saveBtn.disabled = !select.value;
    hideNote();
  }

  function selectedIds() {
    var scope = currentScope();
    if (scope === 'program') {
      return programBoxes()
        .filter(function (box) { return box.checked; })
        .map(function (box) { return box.value; });
    }
    if (scope === 'grant') {
      return Object.keys(chosenGrants);
    }
    return [];
  }

  function roleLabel() {
    var option = select.options[select.selectedIndex];
    return (option && option.textContent.trim()) || select.value;
  }

  // -- notices ------------------------------------------------------------

  // Red only for problems: "Saving…" in red read as a failure.
  function showNote(message, isError) {
    note.textContent = message;
    if (isError) {
      note.classList.add('nfwf-roles-note-error');
    } else {
      note.classList.remove('nfwf-roles-note-error');
    }
    note.hidden = false;
  }

  function hideNote() {
    note.textContent = '';
    note.hidden = true;
  }

  // -- open / close -------------------------------------------------------

  function open(userName, displayName) {
    lastFocus = document.activeElement;
    subject.textContent = displayName || userName;
    // Deliberately not data-nfwf-roles-user: that attribute marks the kebab
    // menu items the open handlers are bound to.
    form.setAttribute('data-nfwf-roles-target', userName);
    current = assignments[userName] || emptyAssignment();
    // Preselect the role they hold so the modal opens showing the current
    // state; users with no role get the placeholder instead.
    select.value = current.role || '';
    applyScope();
    backdrop.hidden = false;
    modal.hidden = false;
    document.body.classList.add('nfwf-roles-open');
    select.focus();
  }

  function close() {
    modal.hidden = true;
    backdrop.hidden = true;
    document.body.classList.remove('nfwf-roles-open');
    if (lastFocus && lastFocus.focus) { lastFocus.focus(); }
    lastFocus = null;
  }

  // -- updating the row ---------------------------------------------------

  // Saving answers with the user's new role record, so the Role and Assigned
  // Grants / Programs cells are redrawn from it rather than the page being
  // reloaded, as the status actions do with Status.  The record says outright
  // whether its assignments are in effect.
  function applyRole(row, record) {
    if (!row) { return; }
    drawRoleCells(row, record, record.assignments_in_effect !== false);
    flashRow(row);
  }

  // -- wiring -------------------------------------------------------------

  toArray(document.querySelectorAll('[data-nfwf-roles-user]')).forEach(function (trigger) {
    trigger.addEventListener('click', function (event) {
      event.preventDefault();
      open(trigger.getAttribute('data-nfwf-roles-user'),
           trigger.getAttribute('data-nfwf-roles-display'));
    });
  });

  select.addEventListener('change', applyScope);

  search.addEventListener('input', function () {
    if (currentScope() === 'program') {
      filterPrograms();
      return;
    }
    // Debounced so typing a grant name is one round of requests, not one per
    // keystroke.
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(loadGrantGroups, 250);
  });

  grantGroups.forEach(function (group) {
    group.more.addEventListener('click', function () {
      var seq = searchSeq;
      loadGroup(group, seq).catch(function (error) {
        if (seq !== searchSeq) { return; }
        group.more.disabled = false;
        grantHint.textContent = error.message;
        grantHint.hidden = false;
      });
    });
  });

  programBoxes().forEach(function (box) {
    box.addEventListener('change', hideNote);
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();

    var role = select.value;
    var scope = currentScope();
    var chosen = selectedIds();
    var userName = form.getAttribute('data-nfwf-roles-target');

    if (!role) {
      showNote('Choose a role first.', true);
      return;
    }
    // The action enforces this too; checking here saves a round trip and gives
    // a message in the modal's own words.
    if (scope !== 'none' && !chosen.length) {
      showNote('Select at least one ' + scope + ' for "' + roleLabel() + '".',
               true);
      return;
    }
    // This account holds both program and grant assignments, and saving replaces
    // every one of them -- including the half this modal has no picker for.  The
    // server cannot catch it, because discarding them is exactly what a role
    // change is meant to do.
    if (current.dual_scope && !dualScopeAcknowledged) {
      dualScopeAcknowledged = true;
      showNote('This account also holds assignments of the other kind, which ' +
               'saving will remove. Press Save again to confirm.', true);
      return;
    }

    var payload = {id: userName, role: role};
    payload.program_ids = scope === 'program' ? chosen : [];
    payload.grant_ids = scope === 'grant' ? chosen : [];

    saveBtn.disabled = true;
    showNote('Saving…');

    apiPost('nfwf_user_role_set', payload)
      .then(function (result) {
        // Keep the page's copy in step so reopening the modal shows what was
        // just saved without a reload.
        assignments[userName] = selectionFrom(result);
        current = assignments[userName];
        dualScopeAcknowledged = false;
        saveBtn.disabled = false;
        // Done, so get out of the way: close, redraw the row, and report on
        // the page in the same place and words as a status change.
        var displayName = subject.textContent;
        close();
        applyRole(userRow(userName), result);
        showNotice((displayName || userName) + ' is now ' +
                   (result.role_label || roleLabel()) + '.', false);
      })
      .catch(function (error) {
        saveBtn.disabled = false;
        showNote(error.message, true);
      });
  });

  modal.querySelector('.nfwf-roles-close').addEventListener('click', close);
  modal.querySelector('.nfwf-roles-cancel').addEventListener('click', close);

  // The modal element is a full-viewport scroll container sitting above the
  // backdrop, so clicks on the dimmed area land here rather than on .backdrop.
  modal.addEventListener('click', function (event) {
    if (event.target === modal) { close(); }
  });
  backdrop.addEventListener('click', close);

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !modal.hidden) { close(); }
  });

  // -- account status actions ---------------------------------------------

  // Each status action returns a complete table row, so the row is updated from
  // the response rather than the page being reloaded.  Deactivating also
  // removes every role, so the Role and assignment cells are redrawn along with
  // the status cell and the menu that depends on it.
  //
  // Which actions suit which status, and the status colours, come from the
  // server (user_admin._table_meta) rather than being restated here.
  function wireStatusActions() {
    var meta = readJson('nfwf-user-table-meta');
    var labels = readJson('nfwf-status-labels');
    if (!meta.status_actions) { return; }

    toArray(document.querySelectorAll('[data-nfwf-status-action]'))
      .forEach(function (trigger) {
        bindStatusAction(trigger, meta, labels);
      });
  }

  function bindStatusAction(trigger, meta, labels) {
    trigger.addEventListener('click', function (event) {
      event.preventDefault();
      // The menu stays open under the pointer, so a second click before the
      // first resolves would send the action twice.
      if (trigger.getAttribute('aria-disabled') === 'true') { return; }

      var userName = trigger.getAttribute('data-nfwf-status-user');
      var displayName = trigger.getAttribute('data-nfwf-status-display');
      var action = trigger.getAttribute('data-nfwf-status-action');
      var row = userRow(userName);

      trigger.setAttribute('aria-disabled', 'true');
      showNotice('Working…', false);

      apiPost(action, {id: userName})
        .then(function (record) {
          applyStatus(row, record, meta, labels);
          showNotice((displayName || userName) + ' is now ' +
                     (record.status_label || record.status) + '.', false);
        })
        .catch(function (error) {
          // Refusals arrive as validation errors on `id`, not as a 403: closing
          // your own account, or the last Platform Administrator's.
          showNotice(error.message, true);
        })
        .then(function () {
          trigger.removeAttribute('aria-disabled');
        });
    });
  }

  // Matched by attribute rather than a selector, so a user name containing
  // quotes needs no escaping -- on this site they are email addresses.
  function userRow(userName) {
    return toArray(document.querySelectorAll('[data-nfwf-user-row]'))
      .filter(function (row) {
        return row.getAttribute('data-nfwf-user-row') === userName;
      })[0] || null;
  }

  // Shared by role saves and status actions.  Both report in the notice above
  // the table, which may be scrolled well out of view, so the changed row is
  // marked too.  Removed and re-added so changing the same row twice flashes it
  // twice; reading offsetWidth in between forces the reflow that restarts the
  // animation.
  function flashRow(row) {
    row.classList.remove('nfwf-user-row-updated');
    void row.offsetWidth;
    row.classList.add('nfwf-user-row-updated');
  }

  function applyStatus(row, record, meta, labels) {
    if (!row) { return; }

    var cell = row.querySelector('[data-nfwf-cell="status"]');
    if (cell) {
      cell.textContent = '';
      var badge = document.createElement('span');
      badge.className = (meta.status_classes || {})[record.status] || '';
      badge.textContent = record.status_label || '';
      cell.appendChild(badge);
    }

    rebuildStatusMenu(row, record, meta, labels);
    // Unlike a role save's record, this row does not say whether its
    // assignments are in effect, so that is looked up by role.  The other
    // status actions leave the role alone, and this redraws it unchanged.
    drawRoleCells(row, record,
                  (meta.assignments_in_effect || {})[record.role] !== false);
    assignments[record.name] = selectionFrom(record);
    flashRow(row);
  }

  // The Role and Assigned Grants / Programs cells, by the same rules as
  // user/list.html: a Platform Administrator's assignments are retained but
  // not in effect, so neither they nor the dual-scope qualifier are shown.
  function drawRoleCells(row, record, inEffect) {
    var roleCell = row.querySelector('[data-nfwf-cell="role"]');
    if (roleCell) {
      roleCell.textContent = record.role_label || '';
      if (record.dual_scope && inEffect) {
        var qualifier = document.createElement('span');
        qualifier.className = 'nfwf-user-dual-scope';
        qualifier.textContent = rowMeta.dual_scope_label || '';
        roleCell.appendChild(qualifier);
      }
    }

    var cell = row.querySelector('[data-nfwf-cell="assignments"]');
    if (!cell) { return; }
    cell.textContent = '';
    if (!inEffect) { return; }

    // Programs first, as the template lists them.
    var items = linkItems(record.programs, rowMeta.program_url)
      .concat(linkItems(record.grants, rowMeta.grant_url));
    if (!items.length) { return; }
    var list = document.createElement('ul');
    list.className = 'nfwf-user-assignments';
    items.forEach(function (item) { list.appendChild(item); });
    cell.appendChild(list);
  }

  // One linked list item per program or grant.  `url` carries a __name__
  // placeholder -- see nfwf-role-row-meta in user/list.html.
  function linkItems(groups, url) {
    return (groups || []).map(function (group) {
      var link = document.createElement('a');
      link.href = (url || '').replace('__name__', encodeURIComponent(group.name));
      link.textContent = group.title || group.name;
      var item = document.createElement('li');
      item.appendChild(link);
      return item;
    });
  }

  // The row's status is what decided which actions it offers, so the two move
  // together: a just-approved account should no longer offer Approve.
  function rebuildStatusMenu(row, record, meta, labels) {
    var list = row.querySelector('.nfwf-user-menu-list');
    if (!list) { return; }

    toArray(list.querySelectorAll('[data-nfwf-status-action]'))
      .forEach(function (item) {
        if (item.parentNode) { list.removeChild(item.parentNode); }
      });

    ((meta.status_actions || {})[record.status] || []).forEach(function (entry) {
      var label = labels[entry.key] || entry.key;
      var link = document.createElement('a');
      link.className = 'dropdown-item';
      link.href = '#';
      link.setAttribute('data-nfwf-status-user', record.name);
      link.setAttribute('data-nfwf-status-display',
                        record.display_name || record.name);
      link.setAttribute('data-nfwf-status-action', entry.action);
      link.setAttribute('data-nfwf-status-label', label);
      link.textContent = label;
      bindStatusAction(link, meta, labels);

      var item = document.createElement('li');
      item.appendChild(link);
      list.appendChild(item);
    });
  }

  function showNotice(message, isError) {
    var notice = document.querySelector('.nfwf-user-notice');
    if (!notice) { return; }
    notice.textContent = message;
    if (isError) {
      notice.classList.add('nfwf-user-notice-error');
    } else {
      notice.classList.remove('nfwf-user-notice-error');
    }
    notice.hidden = false;
  }
})();
