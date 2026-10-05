const {escapeHtml, plural, describeResult, summarizeRun, severityText, number} = window.RoutierFormat;
const clock = new Intl.DateTimeFormat('fr-FR', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
const deliveryText = {at_least_once_with_idempotent_sink: 'at least once avec sink idempotent'};

// Chaque onglet a sa propre base côté serveur : ce qu'un visiteur envoie
// n'apparaît jamais chez un autre.
const session = (() => {
  const fresh = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 14)}`);
  try {
    const stored = sessionStorage.getItem('routier-session');
    if (stored) return stored;
    const created = fresh();
    sessionStorage.setItem('routier-session', created);
    return created;
  } catch (error) {
    return fresh();
  }
})();

function atTime(value, fallback = '—') {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'heure inconnue' : clock.format(date);
}

function lineChip(routeId) {
  return routeId ? `<span class="line">${escapeHtml(routeId)}</span>` : '<span class="muted">—</span>';
}

function isOpen(event) {
  return event.severity !== 'none' && !event.acknowledged_at;
}

function severityLabel(severity) {
  return escapeHtml(severityText[severity] || severity);
}

function outcomeLabel(outcome) {
  return escapeHtml({accepted: 'accepté', duplicate: 'doublon', rejected: 'rejeté', acknowledged: 'pris en charge'}[outcome] || outcome);
}

function renderTally(overview, metrics) {
  const parts = [
    `<b>${plural(metrics.accepted, 'accepté')}</b>`,
    `<b>${plural(metrics.duplicates, 'doublon')}</b>`,
    `<b>${plural(metrics.rejected, 'rejet')}</b>`,
    `<b class="${overview.open_alerts ? 'open' : ''}">${plural(overview.open_alerts, 'alerte ouverte', 'alertes ouvertes')}</b>`,
  ];
  const last = metrics.last_activity_at ? `dernière écriture à ${atTime(metrics.last_activity_at)}` : 'aucune écriture';
  document.querySelector('#tally').innerHTML = `${parts.join(' <span class="sep">·</span> ')} <span class="sep">·</span> <span class="muted">${last}</span>`;
}

function renderQueue(overview) {
  const open = overview.events.filter(isOpen);
  // Après la dernière prise en charge, le bloc reste affiché pour que le
  // message de confirmation ne disparaisse pas avec lui.
  document.querySelector('#queue').hidden = open.length === 0 && !document.querySelector('#queue-status').textContent;
  document.querySelector('#alert-list').innerHTML = open.length === 0 ? '<tr><td colspan="6" class="empty">Plus aucune alerte à prendre en charge.</td></tr>' : open.map(event => `
    <tr>
      <td class="time">${atTime(event.recorded_at)}</td>
      <td>${lineChip(event.route_id)}</td>
      <td class="nowrap">${escapeHtml(event.vehicle_id)}</td>
      <td><span class="label label-open label-${escapeHtml(event.severity)}">${severityLabel(event.severity)}</span></td>
      <td>${event.reasons.map(escapeHtml).join(' ; ')}</td>
      <td class="action"><button type="button" class="ack" data-event-id="${escapeHtml(event.event_id)}" aria-label="Prendre en charge l'alerte ligne ${escapeHtml(event.route_id)}, véhicule ${escapeHtml(event.vehicle_id)}">Prendre en charge</button></td>
    </tr>`).join('');
}

function renderEvents(overview) {
  document.querySelector('#event-count').textContent = plural(overview.total_events, 'événement');
  document.querySelector('#event-list').innerHTML = overview.events.length ? overview.events.map(event => `
    <tr>
      <td>${lineChip(event.route_id)}</td>
      <td class="nowrap">${escapeHtml(event.vehicle_id)}</td>
      <td class="num">${number.format(event.priority_score)}</td>
      <td><code>${event.rule_ids.map(escapeHtml).join(', ') || 'aucune'}</code></td>
      <td><span class="label${isOpen(event) ? ` label-open label-${escapeHtml(event.severity)}` : ''}">${severityLabel(event.severity)}</span></td>
      <td class="muted">${event.severity === 'none' ? 'sans objet' : event.acknowledged_at ? `${atTime(event.acknowledged_at)} par ${escapeHtml(event.acknowledged_by)}` : 'en attente'}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty">Aucun événement intégré.</td></tr>';
}

// Le journal d'audit ne porte pas la ligne : on la retrouve dans les événements
// connus pour afficher la pastille, et on y lit si l'alerte est encore ouverte.
function renderAudit(audit, overview) {
  const events = new Map(overview.events.map(event => [event.event_id, event]));
  const rows = audit.items || [];
  document.querySelector('#audit-list').innerHTML = rows.length ? rows.map(item => {
    const event = events.get(item.event_id);
    // Les motifs de rejet sont le texte brut du validateur de contrat.
    let motive = item.outcome === 'rejected' && item.reason ? `validateur : ${escapeHtml(item.reason)}` : escapeHtml(item.reason || 'contrat validé');
    let stateClass = '';
    if (item.outcome === 'accepted' && event && event.severity !== 'none') {
      const open = isOpen(event);
      motive = `alerte ${severityLabel(event.severity)} ${open ? 'ouverte' : 'prise en charge'} : ${event.reasons.map(escapeHtml).join(' ; ')}`;
      if (open) stateClass = 'state-open';
    }
    if (item.outcome === 'duplicate' && !item.reason) motive = 'relecture absorbée, décision déjà enregistrée';
    if (item.outcome === 'acknowledged') motive = `par ${escapeHtml(item.reason || 'opérateur inconnu')}`;
    return `
    <tr>
      <td class="time">${atTime(item.created_at)}</td>
      <td>${lineChip(event && event.route_id)}</td>
      <td>${item.event_id ? `<code>${escapeHtml(item.event_id)}</code>` : '<span class="muted">sans identifiant</span>'}</td>
      <td class="nowrap"><span class="label label-${escapeHtml(item.outcome)}">${outcomeLabel(item.outcome)}</span></td>
      <td class="${stateClass}">${motive}</td>
      <td class="muted nowrap">${escapeHtml(item.origin)}</td>
      <td><code class="muted">${escapeHtml(item.trace_id)}</code></td>
    </tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">Rien d\'inscrit pour l\'instant. Lance le flux pour remplir la main courante.</td></tr>';
}

function renderTerms(metrics) {
  document.querySelector('#delivery-semantics').textContent = deliveryText[metrics.delivery_semantics] || metrics.delivery_semantics.replaceAll('_', ' ');
  document.querySelector('#contract-name').textContent = metrics.contract;
  document.querySelector('#dead-letter-topic').textContent = metrics.dead_letter_topic;
  document.querySelector('#source-status').textContent = metrics.latest_source
    ? `dernière capture ${escapeHtml(metrics.latest_source.source)}, ${atTime(metrics.latest_source.captured_at)}` : 'aucune capture';
}

function renderSources(payload) {
  const rows = payload.sources || [];
  document.querySelector('#source-list').innerHTML = rows.length ? rows.map(source => `
    <tr>
      <td><a href="${escapeHtml(source.source_url)}" target="_blank" rel="noopener">${escapeHtml(source.source)}</a></td>
      <td class="num">${number.format(source.entity_count)}</td>
      <td class="num nowrap">${number.format(source.byte_size)} octets</td>
      <td><code>${escapeHtml(source.checksum)}</code></td>
      <td class="time">${atTime(source.captured_at)}</td>
    </tr>`).join('') : '<tr><td colspan="5" class="empty">Aucune capture du feed pour l\'instant.</td></tr>';
}

class HttpError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

// allowRejection : pour /api/events, un 422 est un résultat (rejet inscrit au
// journal), pas une panne.
async function json(url, {allowRejection = false, ...options} = {}) {
  const headers = {'X-Routier-Session': session, ...(options.headers || {})};
  const response = await fetch(url, {...options, headers});
  const body = await response.json().catch(() => ({}));
  if (!response.ok && !(allowRejection && response.status === 422)) throw new HttpError(body.error || `Le serveur a répondu ${response.status}.`, response.status, body);
  return body;
}

async function refresh() {
  const [overview, metrics, audit, sources] = await Promise.all([json('/api/overview'), json('/api/metrics'), json('/api/audit'), json('/api/sources')]);
  renderTally(overview, metrics);
  renderQueue(overview);
  renderAudit(audit, overview);
  renderEvents(overview);
  renderTerms(metrics);
  renderSources(sources);
  document.querySelector('#updated').textContent = clock.format(new Date());
}

function markNewestRow() {
  const row = document.querySelector('#audit-list tr');
  if (!row) return;
  row.classList.add('fresh');
  setTimeout(() => row.classList.remove('fresh'), 1400);
}

function showStatus(element, message, kind = '') {
  element.textContent = message;
  element.className = `status ${kind}`;
}

const actionStatus = document.querySelector('#action-status');
const startButton = document.querySelector('#stream-start');
const pauseButton = document.querySelector('#stream-pause');

// Le libellé d'un bouton d'action ne change pas : le résultat ou l'erreur
// s'affiche dans la zone role="status" voisine, lue par les lecteurs d'écran.
async function runAction(button, statusElement, pendingMessage, action) {
  button.disabled = true;
  showStatus(statusElement, pendingMessage);
  try {
    showStatus(statusElement, await action(), 'ok');
    await refresh();
  } catch (error) {
    showStatus(statusElement, error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

// Flux : les messages viennent de data/stream_events.jsonl via /api/stream et
// passent un par un par la vraie route /api/events (contrat, règles, audit).
const stream = {messages: [], interval: 1600, index: 0, statuses: [], timer: null, running: false, paused: false, run: 0};

function setStreamControls() {
  startButton.disabled = stream.running;
  pauseButton.disabled = !stream.running;
  pauseButton.textContent = stream.paused ? 'Reprendre' : 'Pause';
  pauseButton.setAttribute('aria-pressed', String(stream.paused));
}

function stopStream() {
  stream.run += 1;
  clearTimeout(stream.timer);
  stream.timer = null;
  stream.running = false;
  stream.paused = false;
  setStreamControls();
}

async function sendNext() {
  stream.timer = null;
  if (!stream.running || stream.paused) return;
  const run = stream.run;
  const message = stream.messages[stream.index];
  try {
    const payload = await json('/api/events', {
      allowRejection: true,
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Routier-Origin': 'flux-demo'},
      body: JSON.stringify(message),
    });
    if (run !== stream.run) return;
    stream.statuses.push(payload.status);
    stream.index += 1;
    await refresh();
    if (run !== stream.run) return;
    markNewestRow();
    const done = stream.index >= stream.messages.length;
    showStatus(actionStatus, `Message ${stream.index} sur ${stream.messages.length}. ${describeResult(message, payload)}${done ? ` ${summarizeRun(stream.statuses)}` : ''}`);
    if (done) { stopStream(); return; }
  } catch (error) {
    if (run !== stream.run) return;
    showStatus(actionStatus, `Flux interrompu : ${error.message}`, 'error');
    stopStream();
    return;
  }
  if (stream.running && !stream.paused) stream.timer = setTimeout(sendNext, stream.interval);
}

startButton.addEventListener('click', async () => {
  stream.running = true;
  stream.paused = false;
  setStreamControls();
  showStatus(actionStatus, 'Lecture du scénario de flux…');
  try {
    const payload = await json('/api/stream');
    stream.messages = payload.messages || [];
    stream.interval = Math.max(1500, payload.interval_ms || 1600);
  } catch (error) {
    showStatus(actionStatus, `Le scénario de flux n'a pas pu être lu : ${error.message}`, 'error');
    stopStream();
    return;
  }
  if (!stream.running) return;
  stream.index = 0;
  stream.statuses = [];
  sendNext();
});

pauseButton.addEventListener('click', () => {
  if (!stream.running) return;
  stream.paused = !stream.paused;
  setStreamControls();
  if (stream.paused) {
    clearTimeout(stream.timer);
    stream.timer = null;
    showStatus(actionStatus, `Flux en pause après ${plural(stream.index, 'message')} sur ${stream.messages.length}.`);
  } else {
    showStatus(actionStatus, 'Reprise du flux…');
    sendNext();
  }
});

document.querySelector('#reset').addEventListener('click', event => {
  stopStream();
  showStatus(document.querySelector('#queue-status'), '');
  runAction(event.currentTarget, actionStatus, 'Remise à l\'état de départ…', async () => {
    await json('/api/reset', {method: 'POST'});
    return 'Main courante revenue au scénario de référence.';
  });
});

document.querySelector('#demo').addEventListener('click', event => runAction(
  event.currentTarget, actionStatus, 'Injection du scénario…', async () => {
    const result = await json('/api/demo', {method: 'POST'});
    const parts = [`${plural(result.inserted, 'événement intégré', 'événements intégrés')}`];
    if (result.duplicates) parts.push(`${plural(result.duplicates, 'relecture absorbée', 'relectures absorbées')} comme doublon${result.duplicates > 1 ? 's' : ''}`);
    return `${parts.join(', ')}.`;
  }));

document.querySelector('#sync-sncf').addEventListener('click', event => runAction(
  event.currentTarget, actionStatus, 'Capture du feed SNCF…', async () => {
    const result = await json('/api/sources/sncf/sync', {method: 'POST'})
      .catch(error => { throw new Error(error.status === 429 ? error.message : 'Le feed SNCF n\'a pas répondu. Réessaie dans quelques instants.'); });
    return `${plural(result.entity_count, 'entité capturée', 'entités capturées')} depuis le feed SNCF.`;
  }));

document.querySelector('#alert-list').addEventListener('click', event => {
  const button = event.target.closest('.ack');
  if (!button) return;
  runAction(button, document.querySelector('#queue-status'), 'Prise en charge…', async () => {
    await json(`/api/alerts/${encodeURIComponent(button.dataset.eventId)}/acknowledge`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({operator: 'ops-sandbox', note: 'Accusé depuis le poste de démonstration'}),
    });
    return 'Alerte prise en charge, inscrite au journal.';
  });
});

async function checkReadiness() {
  const readiness = document.querySelector('#readiness');
  try {
    const ready = await json('/ready');
    readiness.textContent = ready.status === 'ready' ? 'Système prêt.' : `Système : ${ready.status}.`;
  } catch (error) {
    readiness.textContent = 'Système injoignable.';
  }
}

// L'instance gratuite Render s'endort : au réveil, l'API peut répondre 502
// ou très lentement. On le dit plutôt que de laisser un chargement muet.
async function firstLoad() {
  const tally = document.querySelector('#tally');
  const slow = setTimeout(() => { tally.textContent = 'Le service démarre, environ 40 s.'; }, 3000);
  const started = Date.now();
  while (true) {
    try {
      await refresh();
      clearTimeout(slow);
      checkReadiness();
      return;
    } catch (error) {
      if (Date.now() - started > 120000) {
        clearTimeout(slow);
        tally.textContent = 'Le service ne répond pas. Recharge la page dans une minute.';
        document.querySelector('#audit-list').innerHTML = '<tr><td colspan="7" class="empty">Le journal n\'a pas pu être lu.</td></tr>';
        document.querySelector('#event-list').innerHTML = '<tr><td colspan="6" class="empty">Les événements n\'ont pas pu être lus.</td></tr>';
        document.querySelector('#readiness').textContent = 'Système injoignable.';
        return;
      }
      tally.textContent = 'Le service démarre, environ 40 s.';
      await new Promise(resolve => setTimeout(resolve, 5000));
    }
  }
}

setStreamControls();
firstLoad();
