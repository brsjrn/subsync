/**
 * SubSync Web — Application frontend
 *
 * SPA avec navigation hiérarchique Films / Séries → Saisons → Épisodes.
 * Gère les appels API, les filtres, la sélection, la console SSE.
 */

// ===========================================================================
// État global
// ===========================================================================

const STATE = {
  mediaTree: null,         // Données de /api/tree
  currentView: 'home',     // Vue active
  currentPath: null,       // Chemin du dossier affiché dans la vue table
  currentContext: null,    // { type: 'films'|'series'|'season', ... }
  selectedFiles: new Set(),// Noms des fichiers sélectionnés
  activeFilters: new Set(['ok', 'warning', 'missing', 'validated', 'ignored']),
  jobRunning: false,
  currentJobId: null,
  eventSource: null,
};

// ===========================================================================
// Utilitaires
// ===========================================================================

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function showToast(msg, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  document.body.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// ===========================================================================
// Navigation
// ===========================================================================

function navigate(view, data = {}) {
  STATE.currentView = view;
  STATE.currentContext = data;
  STATE.currentPath = data.path || null;
  STATE.selectedFiles.clear();
  updateSelectionUI();

  // Sidebar
  $$('.nav-item').forEach(el => el.classList.remove('active'));
  const navItem = $(`.nav-item[data-view="${view}"]`);
  if (navItem) navItem.classList.add('active');

  // Views
  $$('.view').forEach(el => el.classList.remove('active'));

  switch (view) {
    case 'home':
      $('#view-home').classList.add('active');
      renderHome();
      updateBreadcrumb([{ label: 'Accueil', view: 'home' }]);
      break;
    case 'films':
      $('#view-table').classList.add('active');
      renderFilmsTable();
      updateBreadcrumb([
        { label: 'Accueil', view: 'home' },
        { label: 'Films', view: 'films' },
      ]);
      break;
    case 'series':
      $('#view-series-list').classList.add('active');
      renderAllSeries();
      updateBreadcrumb([
        { label: 'Accueil', view: 'home' },
        { label: 'Séries', view: 'series' },
      ]);
      break;
    case 'series-detail':
      $('#view-series').classList.add('active');
      renderSeriesDetail(data.seriesName);
      updateBreadcrumb([
        { label: 'Accueil', view: 'home' },
        { label: 'Séries', view: 'series' },
        { label: data.seriesName },
      ]);
      break;
    case 'season':
      $('#view-table').classList.add('active');
      renderSeasonTable(data.seriesName, data.seasonName);
      updateBreadcrumb([
        { label: 'Accueil', view: 'home' },
        { label: 'Séries', view: 'series' },
        { label: data.seriesName, view: 'series-detail', seriesName: data.seriesName },
        { label: data.seasonName },
      ]);
      break;
    case 'validated':
      $('#view-validated').classList.add('active');
      renderValidated();
      updateBreadcrumb([{ label: 'Accueil', view: 'home' }, { label: 'Whitelist' }]);
      break;
    case 'warnings':
      $('#view-warnings').classList.add('active');
      renderWarnings();
      updateBreadcrumb([{ label: 'Accueil', view: 'home' }, { label: 'Warnings' }]);
      break;
    case 'config':
      $('#view-config').classList.add('active');
      renderConfig();
      updateBreadcrumb([{ label: 'Accueil', view: 'home' }, { label: 'Configuration' }]);
      break;
    case 'help':
      openHelpPanel();
      break;
  }

  updateActionButtons();
}

function updateBreadcrumb(items) {
  const bc = $('#breadcrumb');
  bc.innerHTML = items.map((item, i) => {
    const isLast = i === items.length - 1;
    const sep = i > 0 ? '<span class="crumb-sep">›</span>' : '';
    if (isLast) {
      return `${sep}<span class="crumb">${escapeHtml(item.label)}</span>`;
    }
    // Use data attributes for complex navigation
    const dataAttrs = item.seriesName ? `data-series="${escapeHtml(item.seriesName)}"` : '';
    return `${sep}<span class="crumb" data-view="${item.view}" ${dataAttrs} role="link" tabindex="0">${escapeHtml(item.label)}</span>`;
  }).join('');

  // Click handlers for breadcrumbs
  $$('.crumb', bc).forEach(crumb => {
    crumb.addEventListener('click', () => {
      const view = crumb.dataset.view;
      if (view) {
        if (crumb.dataset.series) {
          navigate('series-detail', { seriesName: crumb.dataset.series });
        } else {
          navigate(view);
        }
      }
    });
  });
}

// ===========================================================================
// Chargement des données
// ===========================================================================

async function loadTree() {
  try {
    const resp = await fetch('/api/tree');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    STATE.mediaTree = await resp.json();
    renderSidebar();
    updateStatsBadges();
    if (STATE.currentView === 'home') renderHome();
    console.log('Arbre chargé :', STATE.mediaTree.series.stats, STATE.mediaTree.films.stats);
  } catch (err) {
    console.error('Erreur chargement arbre :', err);
    showToast('Erreur de chargement des données', 'error');
  }
}

async function refreshTree() {
  try {
    const resp = await fetch('/api/refresh', { method: 'POST' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    STATE.mediaTree = await resp.json();
    renderSidebar();
    updateStatsBadges();
    refreshCurrentView();
    showToast('Statuts rafraîchis');
  } catch (err) {
    console.error('Erreur refresh :', err);
    showToast('Erreur de rafraîchissement', 'error');
  }
}

function refreshCurrentView() {
  syncFilterChips();
  switch (STATE.currentView) {
    case 'home': renderHome(); break;
    case 'films': renderFilmsTable(); break;
    case 'config': renderConfig(); break;
    case 'series': renderAllSeries(); break;
    case 'series-detail':
      if (STATE.currentContext.seriesName) renderSeriesDetail(STATE.currentContext.seriesName);
      break;
    case 'season':
      if (STATE.currentContext.seriesName && STATE.currentContext.seasonName)
        renderSeasonTable(STATE.currentContext.seriesName, STATE.currentContext.seasonName);
      break;
    case 'validated': renderValidated(); break;
    case 'warnings': renderWarnings(); break;
  }
}

// ===========================================================================
// Sidebar
// ===========================================================================

function renderSidebar() {
  const tree = STATE.mediaTree;
  if (!tree) return;

  // Badges
  const fs = tree.films.stats;
  $('#badge-films').textContent = `${fs.ok + fs.validated}/${fs.total}`;

  const ss = tree.series.stats;
  // Use the global series stats badge or create one
  const seriesNav = $('.nav-item[data-view="series"]');
  const badge = seriesNav ? seriesNav.querySelector('.nav-badge') : null;

  // Series tree
  const container = $('#sidebar-series');
  container.innerHTML = '';

  for (const series of tree.series.series_list) {
    const worstStatus = getWorstStatus(series.stats);
    const dotClass = worstStatus || 'ok';

    const item = document.createElement('div');
    item.className = 'series-tree-item';
    item.innerHTML = `<span class="dot ${dotClass}"></span>${escapeHtml(series.name)}`;
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      navigate('series-detail', { seriesName: series.name });
    });
    container.appendChild(item);

    // Seasons (collapsible)
    if (series.season_names.length > 0) {
      const children = document.createElement('div');
      children.className = 'series-tree-children';

      for (const sname of series.season_names) {
        const child = document.createElement('div');
        child.className = 'season-tree-item';
        child.textContent = sname;
        child.addEventListener('click', (e) => {
          e.stopPropagation();
          navigate('season', { seriesName: series.name, seasonName: sname });
        });
        children.appendChild(child);
      }

      container.appendChild(children);

      // Toggle on click
      item.addEventListener('dblclick', () => {
        children.classList.toggle('open');
      });
      // Single click on the arrow area
      item.addEventListener('click', (e) => {
        if (e.target === item || e.target.classList.contains('dot')) {
          children.classList.toggle('open');
        }
      });
    }
  }
}

function getWorstStatus(stats) {
  if (stats.missing > 0) return 'missing';
  if (stats.warning > 0) return 'warning';
  if (stats.ignored > 0) return 'ignored';
  return 'ok';
}

function updateStatsBadges() {
  const tree = STATE.mediaTree;
  if (!tree) return;

  $('#badge-films').textContent = `${tree.films.stats.ok + tree.films.stats.validated}/${tree.films.stats.total}`;
  $('#badge-series').textContent = `${tree.series.stats.ok + tree.series.stats.validated}/${tree.series.stats.total}`;
  $('#badge-validated').textContent = tree.series.stats.validated + tree.films.stats.validated;
  $('#badge-warnings').textContent = tree.series.stats.warning + tree.films.stats.warning;
}

// ===========================================================================
// Vue Accueil
// ===========================================================================

function _collectAllMissing() {
  const tree = STATE.mediaTree;
  if (!tree) return [];

  const missing = [];

  // Films
  for (const film of (tree.films.videos || [])) {
    if (film.status === 'missing' && !film.is_ignored) {
      missing.push({
        name: film.name,
        path: film.path,
        type: 'film',
        context: '🎥 Films',
      });
    }
  }

  // Séries
  for (const series of (tree.series.series_list || [])) {
    for (const [sname, episodes] of Object.entries(series.seasons || {})) {
      for (const ep of episodes) {
        if (ep.status === 'missing' && !ep.is_ignored) {
          missing.push({
            name: ep.name,
            path: ep.path,
            type: 'episode',
            context: `📺 ${series.name} — ${sname}`,
          });
        }
      }
    }
  }

  return missing;
}

function renderHome() {
  const tree = STATE.mediaTree;
  if (!tree) {
    $('#stat-numbers-films').innerHTML = '<span class="muted">Chargement...</span>';
    return;
  }

  const fs = tree.films.stats;
  const ss = tree.series.stats;

  renderStatsNumbers('stat-numbers-films', fs);
  renderStatsNumbers('stat-numbers-series', ss);

  // --- Sous-titres manquants ---
  const allMissing = _collectAllMissing();
  $('#missing-count-label').textContent =
    allMissing.length === 0
      ? 'Aucun sous-titre manquant 🎉'
      : `${allMissing.length} vidéo(s) sans sous-titre français.`;

  const missingContainer = $('#missing-list');
  if (allMissing.length === 0) {
    missingContainer.innerHTML = '';
  } else {
    // Regrouper par contexte
    const grouped = {};
    for (const m of allMissing) {
      if (!grouped[m.context]) grouped[m.context] = [];
      grouped[m.context].push(m);
    }
    missingContainer.innerHTML = Object.entries(grouped).map(([ctx, items]) => `
      <div class="missing-group">
        <div class="missing-group-header">${escapeHtml(ctx)} (${items.length})</div>
        ${items.slice(0, 8).map(item => `
          <div class="missing-item" title="${escapeHtml(item.path)}">
            <span class="mi-name">${escapeHtml(item.name)}</span>
          </div>
        `).join('')}
        ${items.length > 8 ? `<div class="missing-more">… et ${items.length - 8} autre(s)</div>` : ''}
      </div>
    `).join('');
  }

  // --- Fichiers à scanner ---
  const unscannedContainer = $('#unscanned-list');
  if (allMissing.length === 0) {
    unscannedContainer.innerHTML = '<p class="muted">Tous les fichiers ont un sous-titre 👌</p>';
    $('#unscanned-actions').style.display = 'none';
  } else {
    unscannedContainer.innerHTML = allMissing.map(m => `
      <div class="unscanned-item" data-path="${escapeHtml(m.path)}">
        <input type="checkbox" class="unscanned-check" data-path="${escapeHtml(m.path)}">
        <span class="ui-name" title="${escapeHtml(m.path)}">${escapeHtml(m.name)}</span>
        <span class="ui-context">${escapeHtml(m.context)}</span>
      </div>
    `).join('');

    // Checkbox handlers
    $$('.unscanned-check', unscannedContainer).forEach(cb => {
      cb.addEventListener('change', _updateUnscannedActions);
    });

    // Row click → toggle checkbox
    $$('.unscanned-item', unscannedContainer).forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.tagName === 'INPUT') return;
        const cb = $('.unscanned-check', row);
        if (cb) {
          cb.checked = !cb.checked;
          cb.dispatchEvent(new Event('change'));
        }
      });
    });

    _updateUnscannedActions();
  }

  // Recent warnings
  const recentContainer = $('#recent-warnings');
  const allWarnings = (tree.series.series_list || [])
    .flatMap(s => Object.entries(s.seasons || {}))
    .flatMap(([, episodes]) => episodes)
    .filter(ep => ep.status === 'warning')
    .slice(0, 5);

  if (allWarnings.length === 0) {
    recentContainer.innerHTML = '<p class="muted">Aucun avertissement récent 🎉</p>';
  } else {
    recentContainer.innerHTML = allWarnings.map(ep => `
      <div class="warning-item">
        <span class="wn-file">${escapeHtml(ep.name)}</span>
        <span class="wn-gap">${escapeHtml(ep.warning_gap)}</span>
        <span class="wn-detail">${escapeHtml(ep.warning_detail)}</span>
      </div>
    `).join('');
  }
}

function renderStatsNumbers(containerId, stats) {
  const container = $('#' + containerId);
  container.innerHTML = `
    <span class="stat-num ok"><span class="count">${stats.ok + stats.validated}</span> ✅</span>
    <span class="stat-num warning"><span class="count">${stats.warning}</span> ⚠️</span>
    <span class="stat-num missing"><span class="count">${stats.missing}</span> ❌</span>
    <span class="stat-num validated"><span class="count">${stats.validated}</span> ✓</span>
    <span class="stat-num ignored"><span class="count">${stats.ignored || 0}</span> 🚫</span>
  `;
}

function _updateUnscannedActions() {
  const checked = $$('.unscanned-check:checked');
  const count = checked.length;
  $('#unscanned-count').textContent = count > 0 ? `${count} fichier(s) sélectionné(s)` : '';
  $('#unscanned-actions').style.display = count > 0 ? '' : 'none';
}

async function _startJob(payload) {
  // payload: { path: '...', mode: '...' }  ou  { paths: [...], mode: '...' }
  if (STATE.jobRunning) {
    showToast('Un job est déjà en cours', 'error');
    return;
  }

  try {
    const resp = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (resp.status === 409) {
      showToast('Un job est déjà en cours', 'error');
      return;
    }

    const data = await resp.json();
    if (!resp.ok) {
      showToast(data.error || 'Erreur', 'error');
      return;
    }

    STATE.jobRunning = true;
    STATE.currentJobId = data.job_id;
    updateActionButtons();
    updateJobIndicator(true);
    expandConsole();
    clearConsole();
    appendConsoleLine(`$ ${data.command}`, 'muted');
    connectSSE(data.job_id);
  } catch (err) {
    showToast('Erreur de connexion', 'error');
  }
}

async function scanSelectedFiles() {
  const checked = $$('.unscanned-check:checked');
  if (checked.length === 0) return;
  const paths = checked.map(cb => cb.dataset.path);
  await _startJob({ paths, mode: 'scan' });
}

async function scanSingleFile(path) {
  await _startJob({ path, mode: 'scan' });
}

async function forceSingleFile(path) {
  await _startJob({ path, mode: 'force' });
}

// ===========================================================================
// Vue Films (tableau)
// ===========================================================================

function renderFilmsTable() {
  const tree = STATE.mediaTree;
  if (!tree) return;

  const videos = tree.films.videos || [];
  renderVideoTable(videos, '/mnt/media/Multimédias/Films');

  // Update context for action buttons
  STATE.currentContext = { type: 'films' };
  STATE.currentPath = '/mnt/media/Multimédias/Films';
}

// ===========================================================================
// Vue Séries (liste)
// ===========================================================================

function renderAllSeries() {
  const tree = STATE.mediaTree;
  if (!tree) return;

  renderStatsNumbers('all-series-stats', tree.series.stats);

  const container = $('#all-series-list');
  container.innerHTML = tree.series.series_list.map(s => {
    const st = s.stats;
    return `
      <div class="series-card" data-series="${escapeHtml(s.name)}">
        <span class="sc-name">${escapeHtml(s.name)}</span>
        <span class="sc-stats">
          <span class="sc-stat" style="color:var(--ok)">✅ ${st.ok + st.validated}</span>
          <span class="sc-stat" style="color:var(--warning)">⚠️ ${st.warning}</span>
          <span class="sc-stat" style="color:var(--error)">❌ ${st.missing}</span>
        </span>
      </div>
    `;
  }).join('');

  // Click handlers
  $$('.series-card', container).forEach(card => {
    card.addEventListener('click', () => {
      navigate('series-detail', { seriesName: card.dataset.series });
    });
  });

  STATE.currentContext = { type: 'series' };
  STATE.currentPath = '/mnt/media/Multimédias/Séries';
}

// ===========================================================================
// Vue Série (saisons)
// ===========================================================================

function renderSeriesDetail(seriesName) {
  const tree = STATE.mediaTree;
  if (!tree) return;

  const series = tree.series.series_list.find(s => s.name === seriesName);
  if (!series) {
    $('#series-stats').innerHTML = '<p class="muted">Série introuvable</p>';
    return;
  }

  renderStatsNumbers('series-stats', series.stats);

  const grid = $('#seasons-grid');
  grid.innerHTML = '';

  for (const [sname, episodes] of Object.entries(series.seasons)) {
    const sstats = computeStats(episodes);
    const card = document.createElement('div');
    card.className = 'season-card';
    card.innerHTML = `
      <div class="season-name">${escapeHtml(sname)}</div>
      <div class="season-ep-count">${episodes.length} épisode(s)</div>
      <div class="season-mini-stats">
        <span style="color:var(--ok)">✅ ${sstats.ok + sstats.validated}</span>
        <span style="color:var(--warning)">⚠️ ${sstats.warning}</span>
        <span style="color:var(--error)">❌ ${sstats.missing}</span>
      </div>
    `;
    card.addEventListener('click', () => {
      navigate('season', { seriesName, seasonName: sname });
    });
    grid.appendChild(card);
  }

  STATE.currentContext = { type: 'series-detail', seriesName };
  STATE.currentPath = series.path;
}

// ===========================================================================
// Vue Saison (tableau d'épisodes)
// ===========================================================================

function renderSeasonTable(seriesName, seasonName) {
  const tree = STATE.mediaTree;
  if (!tree) return;

  const series = tree.series.series_list.find(s => s.name === seriesName);
  if (!series) return;

  const episodes = series.seasons[seasonName] || [];

  // Trouver le chemin du dossier saison
  const firstEp = episodes[0];
  const seasonPath = firstEp ? firstEp.path.replace(/\/[^/]+$/, '') : series.path;

  renderVideoTable(episodes, seasonPath);

  STATE.currentContext = { type: 'season', seriesName, seasonName };
  STATE.currentPath = seasonPath;
}

// ===========================================================================
// Tableau générique
// ===========================================================================

function renderVideoTable(videos, folderPath) {
  STATE.currentPath = folderPath;
  STATE.selectedFiles.clear();
  updateSelectionUI();

  const tbody = $('#table-body');
  const filtered = videos.filter(v => STATE.activeFilters.has(v.status));

  if (filtered.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-msg">Aucun fichier ne correspond aux filtres</td></tr>';
    return;
  }

  tbody.innerHTML = filtered.map(v => {
    const badgeClass = `badge-${v.status}`;
    let actionBtn = '';
    if (v.is_validated) {
      actionBtn = `<button class="btn btn-sm btn-ghost unvalidate-btn" data-file="${escapeHtml(v.name)}">✗ Retirer</button>`;
    } else if (v.status === 'warning') {
      actionBtn = `<button class="btn btn-sm btn-warning force-one-btn" data-path="${escapeHtml(v.path)}" data-name="${escapeHtml(v.name)}">⚡ Force</button>
                   <button class="btn btn-sm btn-accent validate-btn" data-file="${escapeHtml(v.name)}">✓ Valider</button>`;
    } else if (v.status === 'ignored') {
      actionBtn = `<button class="btn btn-sm btn-ghost unignore-btn" data-file="${escapeHtml(v.name)}">🌍 VO</button>`;
    } else if (v.status === 'missing') {
      actionBtn = `<button class="btn btn-sm btn-primary scan-one-btn" data-path="${escapeHtml(v.path)}" data-name="${escapeHtml(v.name)}">🔍 Scanner</button>
                   <button class="btn btn-sm btn-ghost ignore-btn" data-file="${escapeHtml(v.name)}">🇫🇷 VF</button>`;
    }

    const duration = v.duration && v.duration !== '?' ? v.duration : '--';

    return `
      <tr data-file="${escapeHtml(v.name)}">
        <td class="col-check"><input type="checkbox" class="file-check" data-file="${escapeHtml(v.name)}"></td>
        <td class="col-name" title="${escapeHtml(v.path)}">${escapeHtml(v.name)}</td>
        <td class="col-status"><span class="badge ${badgeClass}">${v.status_label}</span></td>
        <td class="col-duration">${duration}</td>
        <td class="col-actions">
          ${actionBtn}
          <button class="btn btn-sm btn-ghost play-btn" data-path="${escapeHtml(v.path)}" title="Lire avec VLC">▶️</button>
        </td>
      </tr>
    `;
  }).join('');

  // Checkboxes
  $$('.file-check', tbody).forEach(cb => {
    cb.addEventListener('change', () => {
      const file = cb.dataset.file;
      if (cb.checked) STATE.selectedFiles.add(file);
      else STATE.selectedFiles.delete(file);
      updateSelectionUI();
    });
  });

  // Validate buttons
  $$('.validate-btn', tbody).forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const file = btn.dataset.file;
      await validateFiles([file]);
    });
  });

  // Unvalidate buttons
  $$('.unvalidate-btn', tbody).forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const file = btn.dataset.file;
      await unvalidateFiles([file]);
    });
  });

  // Play buttons
  $$('.play-btn', tbody).forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const path = btn.dataset.path;
      try {
        const resp = await fetch('/api/play', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path }),
        });
        const data = await resp.json();
        if (!resp.ok) {
          showToast(data.error || 'Erreur', 'error');
        }
      } catch (err) {
        showToast('Erreur de connexion', 'error');
      }
    });
  });

  // Scan single file buttons
  $$('.scan-one-btn', tbody).forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await scanSingleFile(btn.dataset.path);
    });
  });

  // Force single file buttons
  $$('.force-one-btn', tbody).forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await forceSingleFile(btn.dataset.path);
    });
  });

  // Ignore buttons
  $$('.ignore-btn', tbody).forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await ignoreFiles([btn.dataset.file]);
    });
  });

  // Unignore buttons
  $$('.unignore-btn', tbody).forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await unignoreFiles([btn.dataset.file]);
    });
  });

  // Row click → toggle checkbox
  $$('tr[data-file]', tbody).forEach(row => {
    row.addEventListener('click', (e) => {
      if (e.target.tagName === 'BUTTON' || e.target.tagName === 'INPUT') return;
      const cb = $('.file-check', row);
      if (cb) {
        cb.checked = !cb.checked;
        cb.dispatchEvent(new Event('change'));
        row.classList.toggle('selected', cb.checked);
      }
    });
  });

  // Select all
  $('#check-all').checked = false;
  $('#check-all').onchange = () => {
    const checked = $('#check-all').checked;
    $$('.file-check', tbody).forEach(cb => {
      cb.checked = checked;
      if (checked) STATE.selectedFiles.add(cb.dataset.file);
      else STATE.selectedFiles.delete(cb.dataset.file);
      const row = cb.closest('tr');
      if (row) row.classList.toggle('selected', checked);
    });
    updateSelectionUI();
  };
}

function updateSelectionUI() {
  const count = STATE.selectedFiles.size;
  $('#selection-count').textContent = count > 0 ? `${count} sélectionné(s)` : '';
  $('#btn-validate-selection').style.display = count > 0 ? '' : 'none';
}

function computeStats(videos) {
  const stats = { total: 0, ok: 0, warning: 0, missing: 0, validated: 0, ignored: 0 };
  for (const v of videos) {
    stats[v.status] = (stats[v.status] || 0) + 1;
    stats.total++;
  }
  return stats;
}

// ===========================================================================
// Configuration
// ===========================================================================

async function renderConfig() {
  try {
    const resp = await fetch('/api/config');
    const config = await resp.json();
    $('#cfg-films-path').value = config.films_path || '';
    $('#cfg-series-path').value = config.series_path || '';
    $('#cfg-apikey').value = config.opensubtitles_apikey || '';
  } catch (err) {
    console.error('Erreur chargement config :', err);
  }
}

async function saveConfig() {
  const filmsPath = $('#cfg-films-path').value.trim();
  const seriesPath = $('#cfg-series-path').value.trim();
  const apikey = $('#cfg-apikey').value.trim();
  const status = $('#config-status');

  if (!filmsPath || !seriesPath) {
    status.textContent = 'Les chemins Films et Séries sont requis.';
    status.className = 'error';
    return;
  }

  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        films_path: filmsPath,
        series_path: seriesPath,
        opensubtitles_apikey: apikey,
      }),
    });
    const data = await resp.json();
    if (resp.ok) {
      status.textContent = '✅ Configuration sauvegardée.';
      status.className = 'saved';
      await loadTree();
    } else {
      status.textContent = data.error || 'Erreur';
      status.className = 'error';
    }
  } catch (err) {
    status.textContent = 'Erreur réseau.';
    status.className = 'error';
  }
}

// ===========================================================================
// Panneau d'aide latéral
// ===========================================================================

function openHelpPanel() {
  $('#help-panel').classList.add('open');
  $('#help-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeHelpPanel() {
  $('#help-panel').classList.remove('open');
  $('#help-overlay').classList.remove('open');
  document.body.style.overflow = '';
}

// ===========================================================================
// Filtres
// ===========================================================================

function syncFilterChips() {
  $$('.filter-chip').forEach(chip => {
    const filter = chip.dataset.filter;
    if (STATE.activeFilters.has(filter)) {
      chip.classList.add('active');
    } else {
      chip.classList.remove('active');
    }
  });
}

function initFilters() {
  $$('.filter-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const filter = chip.dataset.filter;
      if (STATE.activeFilters.has(filter)) {
        STATE.activeFilters.delete(filter);
      } else {
        STATE.activeFilters.add(filter);
      }
      syncFilterChips();
      refreshCurrentView();
    });
  });
}

// ===========================================================================
// Validation / Invalidation
// ===========================================================================

async function validateFiles(files) {
  try {
    const resp = await fetch('/api/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    });
    const data = await resp.json();
    if (resp.ok) {
      showToast(`${data.added} fichier(s) validé(s)`);
      await refreshTree();
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur réseau', 'error');
  }
}

async function unvalidateFiles(files) {
  try {
    const resp = await fetch('/api/unvalidate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    });
    const data = await resp.json();
    if (resp.ok) {
      showToast(`${data.removed} fichier(s) retiré(s) de la whitelist`);
      await refreshTree();
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur réseau', 'error');
  }
}

async function ignoreFiles(files) {
  try {
    const resp = await fetch('/api/ignore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    });
    const data = await resp.json();
    if (resp.ok) {
      showToast(`${data.added} fichier(s) marqué(s) VF`);
      await refreshTree();
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur réseau', 'error');
  }
}

async function unignoreFiles(files) {
  try {
    const resp = await fetch('/api/unignore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    });
    const data = await resp.json();
    if (resp.ok) {
      showToast(`${data.removed} fichier(s) repassé(s) en VO`);
      await refreshTree();
    } else {
      showToast(data.error || 'Erreur', 'error');
    }
  } catch (err) {
    showToast('Erreur réseau', 'error');
  }
}

// Batch validate selected
$('#btn-validate-selection').addEventListener('click', async () => {
  if (STATE.selectedFiles.size === 0) return;
  const files = [...STATE.selectedFiles];
  await validateFiles(files);
});

// ===========================================================================
// Whitelist view
// ===========================================================================

async function renderValidated() {
  try {
    const resp = await fetch('/api/validated');
    const data = await resp.json();
    const container = $('#validated-list');

    if (data.files.length === 0) {
      container.innerHTML = '<p class="muted">Aucun sous-titre validé manuellement.</p>';
    } else {
      container.innerHTML = data.files.map(f => `
        <div class="whitelist-item">
          <span style="flex:1">${escapeHtml(f)}</span>
          <button class="btn btn-sm btn-ghost unvalidate-btn" data-file="${escapeHtml(f)}">✗ Retirer</button>
        </div>
      `).join('');

      $$('.unvalidate-btn', container).forEach(btn => {
        btn.addEventListener('click', async () => {
          await unvalidateFiles([btn.dataset.file]);
          renderValidated();
        });
      });
    }
  } catch (err) {
    showToast('Erreur chargement whitelist', 'error');
  }
}

// ===========================================================================
// Warnings view
// ===========================================================================

async function renderWarnings() {
  try {
    const resp = await fetch('/api/warnings');
    const data = await resp.json();
    const container = $('#warnings-list');

    if (data.warnings.length === 0) {
      container.innerHTML = '<p class="muted">Aucun avertissement 🎉</p>';
    } else {
      container.innerHTML = data.warnings.map(w => `
        <div class="warning-item">
          <span class="wn-file">${escapeHtml(w.file)}</span>
          <span class="wn-gap">${escapeHtml(w.gap)}</span>
          <span class="wn-detail">${escapeHtml(w.detail)}</span>
          <button class="btn btn-sm btn-accent validate-btn" data-file="${escapeHtml(w.file)}">✓ Valider</button>
        </div>
      `).join('');

      $$('.validate-btn', container).forEach(btn => {
        btn.addEventListener('click', async () => {
          await validateFiles([btn.dataset.file]);
          renderWarnings();
        });
      });
    }
  } catch (err) {
    showToast('Erreur chargement warnings', 'error');
  }
}

// ===========================================================================
// Actions (Scan, Force, Dry-Run)
// ===========================================================================

function updateActionButtons() {
  const hasPath = !!STATE.currentPath;

  $('#btn-scan').disabled = !hasPath || STATE.jobRunning;
  $('#btn-force').disabled = !hasPath || STATE.jobRunning;
  $('#btn-dryrun').disabled = !hasPath || STATE.jobRunning;
}

async function runCommand(mode) {
  const path = STATE.currentPath;
  if (!path) {
    showToast('Aucun dossier cible', 'error');
    return;
  }
  await _startJob({ path, mode });
}

// ===========================================================================
// SSE (Server-Sent Events)
// ===========================================================================

function connectSSE(jobId) {
  if (STATE.eventSource) {
    STATE.eventSource.close();
  }

  const es = new EventSource(`/api/stream/${jobId}`);
  STATE.eventSource = es;

  es.addEventListener('start', (e) => {
    console.log('SSE démarré');
  });

  es.addEventListener('log', (e) => {
    const data = JSON.parse(e.data);
    appendConsoleLine(data.line || '');
  });

  es.addEventListener('progress', (e) => {
    const data = JSON.parse(e.data);
    if (data.file) {
      appendConsoleLine(`▶ ${data.file}`, 'c-cyan');
    }
  });

  es.addEventListener('done', (e) => {
    const data = JSON.parse(e.data);
    if (data.message) {
      const cls = data.exit_code === 0 ? 'c-green' : 'c-red';
      appendConsoleLine(data.message, cls);
    }
    // Important : onJobFinished() AVANT closeSSE() pour que
    // le onerror sache que le job est déjà terminé
    onJobFinished();
    closeSSE();
  });

  es.addEventListener('error', (e) => {
    if (e.data) {
      try {
        const data = JSON.parse(e.data);
        appendConsoleLine(`[ERROR] ${data.message}`, 'c-red');
      } catch (_) {
        appendConsoleLine('[ERROR] Connexion perdue', 'c-red');
      }
    }
    onJobFinished();
    closeSSE();
  });

  es.onerror = () => {
    // Si le job est déjà marqué comme terminé, fermer définitivement
    if (!STATE.jobRunning) {
      closeSSE();
    }
    // Sinon, laisser EventSource tenter de reconnecter automatiquement
  };
}

function closeSSE() {
  if (STATE.eventSource) {
    STATE.eventSource.close();
    STATE.eventSource = null;
  }
}

function onJobFinished() {
  STATE.jobRunning = false;
  STATE.currentJobId = null;
  updateActionButtons();
  updateJobIndicator(false);
  checkSetup();    // re-vérifier l'état de l'installation
  refreshTree();
}

// ===========================================================================
// Console
// ===========================================================================

function appendConsoleLine(text, cls = '') {
  const body = $('#console-body');
  const div = document.createElement('div');
  div.className = `console-line ${cls}`;

  // ANSI color parsing
  let html = escapeHtml(text);
  html = html.replace(/\x1b\[0;31m/g, '<span class="c-red">')
             .replace(/\x1b\[0;32m/g, '<span class="c-green">')
             .replace(/\x1b\[1;33m/g, '<span class="c-yellow">')
             .replace(/\x1b\[0;34m/g, '<span class="c-blue">')
             .replace(/\x1b\[0;36m/g, '<span class="c-cyan">')
             .replace(/\x1b\[0;35m/g, '<span class="c-magenta">')
             .replace(/\x1b\[0m/g, '</span>');

  div.innerHTML = html;
  body.appendChild(div);
  body.scrollTop = body.scrollHeight;
}

function clearConsole() {
  $('#console-body').innerHTML = '';
}

function expandConsole() {
  $('#console').classList.remove('console-collapsed');
  $('#console').classList.add('console-expanded');
  $('#btn-toggle-console').textContent = '▾';
}

function toggleConsole() {
  const con = $('#console');
  if (con.classList.contains('console-collapsed')) {
    con.classList.remove('console-collapsed');
    con.classList.add('console-expanded');
    $('#btn-toggle-console').textContent = '▾';
  } else {
    con.classList.remove('console-expanded');
    con.classList.add('console-collapsed');
    $('#btn-toggle-console').textContent = '▸';
  }
}

function stopJob() {
  if (!STATE.currentJobId) return;
  fetch(`/api/stop/${STATE.currentJobId}`, { method: 'POST' })
    .then(() => {
      appendConsoleLine('⏹ Job arrêté', 'c-yellow');
      closeSSE();
      onJobFinished();
    })
    .catch(() => {
      showToast('Erreur lors de l\'arrêt', 'error');
    });
}

function updateJobIndicator(running) {
  const ind = $('#job-indicator');
  if (running) {
    ind.textContent = '● En cours...';
    ind.className = 'job-running';
  } else {
    ind.textContent = '○ Inactif';
    ind.className = 'job-idle';
  }

  $('#btn-stop-job').style.display = running ? '' : 'none';
  $('#sidebar-status').className = running ? 'status-dot running' : 'status-dot idle';
}

// ===========================================================================
// Event listeners
// ===========================================================================

function init() {
  // Sidebar navigation
  $$('.nav-item').forEach(item => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const view = item.dataset.view;
      if (view) navigate(view);
    });
  });

  // Action buttons
  $('#btn-scan').addEventListener('click', () => runCommand('scan'));
  $('#btn-force').addEventListener('click', () => runCommand('force'));
  $('#btn-dryrun').addEventListener('click', () => runCommand('dry-run'));

  // Console buttons
  $('#btn-toggle-console').addEventListener('click', toggleConsole);
  $('#btn-clear-console').addEventListener('click', clearConsole);
  $('#btn-stop-job').addEventListener('click', stopJob);

  // Refresh
  $('#btn-refresh').addEventListener('click', refreshTree);

  // Scan selected files from home
  $('#btn-scan-selected').addEventListener('click', scanSelectedFiles);

  // Console header click → toggle
  $('.console-header').addEventListener('click', (e) => {
    if (e.target.tagName === 'BUTTON') return;
    toggleConsole();
  });

  // Stats card clicks → navigate
  $('#stat-card-films').addEventListener('click', () => navigate('films'));
  $('#stat-card-series').addEventListener('click', () => navigate('series'));

  // Config save
  $('#btn-save-config').addEventListener('click', saveConfig);

  // Help panel
  $('#btn-help').addEventListener('click', openHelpPanel);
  $('#btn-close-help').addEventListener('click', closeHelpPanel);
  $('#help-overlay').addEventListener('click', closeHelpPanel);

  // Filters
  initFilters();

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      // Priorité : fermer le panneau d'aide s'il est ouvert
      if ($('#help-panel').classList.contains('open')) {
        closeHelpPanel();
        return;
      }
      STATE.selectedFiles.clear();
      updateSelectionUI();
      $$('tr.selected').forEach(r => r.classList.remove('selected'));
      $$('.file-check').forEach(cb => cb.checked = false);
      $('#check-all').checked = false;
    }
    // Touche ? pour ouvrir l'aide
    if (e.key === '?' && !e.target.closest('input, textarea')) {
      e.preventDefault();
      openHelpPanel();
    }
    if (e.ctrlKey && e.key === 'Enter') {
      e.preventDefault();
      runCommand('scan');
    }
  });

  // Check setup
  checkSetup();

  // Load data
  loadTree();
}

// ===========================================================================
// Vérification d'installation
// ===========================================================================

async function checkSetup() {
  try {
    const resp = await fetch('/api/setup/check');
    STATE.setupStatus = await resp.json();
    renderSetupBanner();
  } catch (err) {
    console.error('Erreur check setup :', err);
  }
}

function renderSetupBanner() {
  const status = STATE.setupStatus;
  if (!status || status.ready) {
    const banner = $('#setup-banner');
    if (banner) banner.remove();
    return;
  }

  const home = $('#view-home');
  let banner = $('#setup-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'setup-banner';
    banner.className = 'setup-banner';
    home.insertBefore(banner, home.firstChild);
  }

  const checks = status.checks;
  const failed = Object.entries(checks).filter(([, c]) => !c.ok);

  banner.innerHTML = `
    <h3>⚙️ Configuration requise</h3>
    <p>${failed.length} élément(s) à installer ou configurer avant de pouvoir utiliser SubSync.</p>
    <div class="setup-checks">
      ${Object.entries(checks).map(([, c]) => `
        <div class="setup-check ${c.ok ? 'ok' : 'fail'}">
          <span class="check-icon">${c.ok ? '✅' : '❌'}</span>
          <span class="check-label">${c.label}</span>
          ${c.detail ? `<span class="check-detail">— ${c.detail}</span>` : ''}
          ${!c.ok ? `
            <span class="check-fix">
              ${c.action === 'page'
                ? `<button class="btn btn-sm btn-primary" onclick="${c.fix === 'config' ? "navigate('config')" : ''}">${c.fix_label}</button>`
                : `<code>${escapeHtml(c.fix)}</code>`
              }
            </span>
          ` : ''}
        </div>
      `).join('')}
    </div>
    <div class="setup-actions">
      <button class="btn btn-ghost" onclick="checkSetup()">🔄 Vérifier à nouveau</button>
    </div>
  `;
}

// Start
document.addEventListener('DOMContentLoaded', init);
