const number = new Intl.NumberFormat('fr-FR');
const timeFormat = new Intl.DateTimeFormat('fr-FR', {hour: '2-digit', minute: '2-digit'});
const severityText = {none: 'nominal', watch: 'surveillance', critical: 'critique'};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[character]));
}

function atTime(value) {
  if (!value) return 'aucune';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'inconnue' : timeFormat.format(date);
}

function outcomeLabel(outcome) {
  return {accepted: 'accepté', duplicate: 'doublon', rejected: 'rejeté', acknowledged: 'pris en charge'}[outcome] || outcome;
}

function renderOverview(data) {
  document.querySelector('#metric-alerts').textContent = number.format(data.open_alerts);
  document.querySelector('#event-count').textContent = `${number.format(data.total_events)} événement${data.total_events > 1 ? 's' : ''}`;
  document.querySelector('#updated').textContent = timeFormat.format(new Date());
  const open = data.events.filter(event => event.severity !== 'none' && !event.acknowledged_at);
  document.querySelector('#queue-count').textContent = `${open.length} alerte${open.length > 1 ? 's' : ''} active${open.length > 1 ? 's' : ''}`;
  document.querySelector('#alert-list').innerHTML = open.length ? open.map(event => `
    <article class="alert">
      <span class="severity ${escapeHtml(event.severity)}">${severityText[event.severity] || escapeHtml(event.severity)}</span>
      <div><h3>Ligne ${escapeHtml(event.route_id)} · véhicule ${escapeHtml(event.vehicle_id)}</h3><p>${event.reasons.map(escapeHtml).join(' · ')}</p></div>
      <div class="alert-meta"><time>${atTime(event.recorded_at)}</time><button type="button" class="ack" data-event-id="${escapeHtml(event.event_id)}">Prendre en charge</button></div>
    </article>`).join('') : '<p class="empty">Aucune alerte active. Charge le scénario pour suivre une décision de bout en bout.</p>';
  document.querySelector('#event-list').innerHTML = data.events.length ? data.events.map(event => `
    <tr><td>${escapeHtml(event.vehicle_id)}</td><td>${escapeHtml(event.route_id)}</td><td>${number.format(event.priority_score)}</td><td><code>${event.rule_ids.map(escapeHtml).join(', ') || 'aucune'}</code></td><td><span class="badge ${escapeHtml(event.severity)}">${severityText[event.severity]}</span></td></tr>`).join('') : '<tr><td colspan="5">Le tableau attend son premier événement.</td></tr>';
}

function renderMetrics(data) {
  document.querySelector('#metric-accepted').textContent = number.format(data.accepted);
  document.querySelector('#metric-duplicates').textContent = number.format(data.duplicates);
  document.querySelector('#metric-rejected').textContent = number.format(data.rejected);
  document.querySelector('#delivery-semantics').textContent = data.delivery_semantics.replaceAll('_', ' ');
  document.querySelector('#contract-name').textContent = data.contract;
  document.querySelector('#dead-letter-topic').textContent = data.dead_letter_topic;
  document.querySelector('#last-activity').textContent = atTime(data.last_activity_at);
  if (data.latest_source) document.querySelector('#source-status').textContent = `${data.latest_source.source} · ${atTime(data.latest_source.captured_at)}`;
}

function renderAudit(payload) {
  const rows = payload.items || [];
  document.querySelector('#audit-list').innerHTML = rows.length ? rows.map(item => `
    <tr><td>${atTime(item.created_at)}</td><td><code>${escapeHtml(item.trace_id)}</code></td><td>${item.event_id ? `<code>${escapeHtml(item.event_id)}</code>` : 'sans identifiant'}</td><td>${escapeHtml(item.origin)}</td><td><span class="audit-outcome ${escapeHtml(item.outcome)}">${outcomeLabel(item.outcome)}</span></td><td>${escapeHtml(item.reason || 'contrat validé')}</td></tr>`).join('') : '<tr><td colspan="6">Le journal attend sa première activité.</td></tr>';
}

function renderSources(payload) {
  const rows = payload.sources || [];
  document.querySelector('#source-list').innerHTML = rows.length ? rows.map(source => `
    <tr><td><a href="${escapeHtml(source.source_url)}" target="_blank" rel="noopener">${escapeHtml(source.source)}</a></td><td>${number.format(source.entity_count)}</td><td>${number.format(source.byte_size)} octets</td><td><code>${escapeHtml(source.checksum)}</code></td><td>${atTime(source.captured_at)}</td></tr>`).join('') : '<tr><td colspan="5">Aucune photographie externe capturée.</td></tr>';
}

async function json(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Une erreur est survenue');
  return body;
}

async function refresh() {
  const [overview, metrics, audit, sources] = await Promise.all([json('/api/overview'), json('/api/metrics'), json('/api/audit'), json('/api/sources')]);
  renderOverview(overview);
  renderMetrics(metrics);
  renderAudit(audit);
  renderSources(sources);
}

async function checkReadiness() {
  const state = document.querySelector('.system-state');
  try {
    const ready = await json('/ready');
    document.querySelector('#readiness').textContent = `${ready.status} · ${ready.contract}`;
    state.classList.add('ready');
  } catch (error) {
    document.querySelector('#readiness').textContent = 'système indisponible';
  }
}

document.querySelector('#demo').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = 'Injection en cours…';
  try {
    const result = await json('/api/demo', {method: 'POST'});
    button.textContent = result.inserted ? `${result.inserted} événements intégrés` : 'Scénario déjà intégré';
    await refresh();
  } catch (error) {
    button.textContent = error.message;
  } finally {
    window.setTimeout(() => { button.disabled = false; button.textContent = 'Charger le scénario'; }, 2200);
  }
});

document.querySelector('#sync-sncf').addEventListener('click', async event => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = 'Synchronisation…';
  try {
    const result = await json('/api/sources/sncf/sync', {method: 'POST'});
    button.textContent = `${result.entity_count} entités capturées`;
    await refresh();
  } catch (error) {
    button.textContent = error.message;
  } finally {
    window.setTimeout(() => { button.disabled = false; button.textContent = 'Capturer le feed SNCF'; }, 2600);
  }
});

document.querySelector('#alert-list').addEventListener('click', async event => {
  const button = event.target.closest('.ack');
  if (!button) return;
  button.disabled = true;
  button.textContent = 'En cours…';
  try {
    await json(`/api/alerts/${encodeURIComponent(button.dataset.eventId)}/acknowledge`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({operator: 'ops-sandbox', note: 'Accusé depuis le poste de démonstration'}),
    });
    await refresh();
  } catch (error) {
    button.textContent = error.message;
  }
});

refresh().catch(() => { document.querySelector('#readiness').textContent = 'Erreur de chargement des données'; });
checkReadiness();
