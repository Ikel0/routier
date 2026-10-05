const number = new Intl.NumberFormat('fr-FR');
const clock = new Intl.DateTimeFormat('fr-FR', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
const severityText = {none: 'nominal', watch: 'surveillance', critical: 'critique'};
const deliveryText = {at_least_once_with_idempotent_sink: 'at least once avec sink idempotent'};

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[character]));
}

function plural(count, singular, pluralForm = `${singular}s`) {
  return `${number.format(count)} ${count > 1 ? pluralForm : singular}`;
}

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

function outcomeLabel(outcome) {
  return {accepted: 'accepté', duplicate: 'doublon', rejected: 'rejeté', acknowledged: 'pris en charge'}[outcome] || outcome;
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
      <td class="sev-${escapeHtml(event.severity)}">${severityText[event.severity] || escapeHtml(event.severity)}</td>
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
      <td class="${isOpen(event) ? `sev-${escapeHtml(event.severity)}` : ''}">${severityText[event.severity] || escapeHtml(event.severity)}</td>
      <td class="muted">${event.severity === 'none' ? 'sans objet' : event.acknowledged_at ? `${atTime(event.acknowledged_at)} par ${escapeHtml(event.acknowledged_by)}` : 'en attente'}</td>
    </tr>`).join('') : '<tr><td colspan="6" class="empty">Aucun événement intégré. Le scénario en produit quatre.</td></tr>';
}

// Le journal d'audit ne porte pas la ligne : on la retrouve dans les événements
// connus pour afficher la pastille, et on y lit si l'alerte est encore ouverte.
function renderAudit(audit, overview) {
  const events = new Map(overview.events.map(event => [event.event_id, event]));
  const rows = audit.items || [];
  document.querySelector('#audit-list').innerHTML = rows.length ? rows.map(item => {
    const event = events.get(item.event_id);
    let motive = escapeHtml(item.reason || 'contrat validé');
    let stateClass = '';
    if (item.outcome === 'accepted' && event && event.severity !== 'none') {
      const open = isOpen(event);
      motive = `alerte ${severityText[event.severity]} ${open ? 'ouverte' : 'prise en charge'} : ${event.reasons.map(escapeHtml).join(' ; ')}`;
      if (open) stateClass = 'state-open';
    }
    if (item.outcome === 'duplicate' && !item.reason) motive = 'relecture absorbée, décision déjà enregistrée';
    if (item.outcome === 'acknowledged') motive = `par ${escapeHtml(item.reason || 'opérateur inconnu')}`;
    return `
    <tr>
      <td class="time">${atTime(item.created_at)}</td>
      <td>${lineChip(event && event.route_id)}</td>
      <td>${item.event_id ? `<code>${escapeHtml(item.event_id)}</code>` : '<span class="muted">sans identifiant</span>'}</td>
      <td class="nowrap">${outcomeLabel(item.outcome)}</td>
      <td class="${stateClass}">${motive}</td>
      <td class="muted nowrap">${escapeHtml(item.origin)}</td>
      <td><code class="muted">${escapeHtml(item.trace_id)}</code></td>
    </tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">Rien d\'inscrit pour l\'instant. Charge le scénario pour ouvrir la main courante.</td></tr>';
}

function renderTerms(metrics) {
  document.querySelector('#delivery-semantics').textContent = deliveryText[metrics.delivery_semantics] || metrics.delivery_semantics.replaceAll('_', ' ');
  document.querySelector('#contract-name').textContent = metrics.contract;
  document.querySelector('#dead-letter-topic').textContent = metrics.dead_letter_topic;
  if (metrics.latest_source) document.querySelector('#source-status').textContent = `dernière capture ${metrics.latest_source.source}, ${atTime(metrics.latest_source.captured_at)}`;
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

async function json(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Le serveur a répondu ${response.status}.`);
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

async function checkReadiness() {
  const readiness = document.querySelector('#readiness');
  try {
    const ready = await json('/ready');
    readiness.textContent = ready.status === 'ready' ? 'Système prêt.' : `Système : ${ready.status}.`;
  } catch (error) {
    readiness.textContent = 'Système injoignable.';
  }
}

function showStatus(element, message, kind) {
  element.textContent = message;
  element.className = `status ${kind}`;
}

// Le libellé du bouton ne change jamais : le résultat ou l'erreur s'affiche
// dans la zone role="status" voisine, lue par les lecteurs d'écran.
async function runAction(button, statusElement, pendingMessage, action) {
  button.disabled = true;
  showStatus(statusElement, pendingMessage, '');
  try {
    showStatus(statusElement, await action(), 'ok');
    await refresh();
  } catch (error) {
    showStatus(statusElement, error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

const actionStatus = document.querySelector('#action-status');

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
      .catch(() => { throw new Error('Le feed SNCF n\'a pas répondu. Réessaie dans quelques instants.'); });
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

refresh().catch(error => {
  document.querySelector('#tally').textContent = `Les compteurs n'ont pas pu être lus : ${error.message}`;
  document.querySelector('#audit-list').innerHTML = `<tr><td colspan="7" class="empty">Le journal n'a pas pu être lu. Recharge la page dans quelques instants.</td></tr>`;
  document.querySelector('#event-list').innerHTML = '<tr><td colspan="6" class="empty">Les événements n\'ont pas pu être lus.</td></tr>';
});
checkReadiness();
