const fmt = new Intl.NumberFormat('fr-FR');
const time = value => new Date(value).toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
const severityText = {none:'nominal', watch:'à surveiller', critical:'critique'};

function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }

function render(data) {
  document.querySelector('#events').textContent = fmt.format(data.total_events);
  document.querySelector('#alerts').textContent = fmt.format(data.open_alerts);
  document.querySelector('#routes').textContent = fmt.format(data.routes_seen);
  document.querySelector('#updated').textContent = 'maintenant';
  const open = data.events.filter(event => event.severity !== 'none');
  document.querySelector('#queue-count').textContent = `${open.length} alerte${open.length > 1 ? 's' : ''}`;
  document.querySelector('#alert-list').innerHTML = open.length ? open.map(event => `<article class="alert ${event.severity}"><i></i><div><h3>${escapeHtml(event.route_id)} · ${escapeHtml(event.vehicle_id)}</h3><p>${event.reasons.map(escapeHtml).join(' · ')}</p></div><b>${time(event.recorded_at)}</b></article>`).join('') : '<p class="empty">Aucun signal à traiter. Chargez le jeu de démonstration pour voir le parcours.</p>';
  document.querySelector('#event-list').innerHTML = data.events.length ? data.events.map(event => `<tr><td>${time(event.recorded_at)}</td><td>${escapeHtml(event.vehicle_id)}</td><td>${escapeHtml(event.route_id)}</td><td>${Math.round(event.delay_seconds / 60)} min</td><td>${event.occupancy_percent}%</td><td><span class="badge ${event.severity}">${severityText[event.severity]}</span></td></tr>`).join('') : '<tr><td colspan="6">Le tableau attend son premier événement.</td></tr>';
}

async function refresh() {
  const response = await fetch('/api/overview');
  render(await response.json());
}

document.querySelector('#demo').addEventListener('click', async event => {
  const button = event.currentTarget; button.disabled = true; button.textContent = 'Injection en cours…';
  await fetch('/api/demo', {method:'POST'}); await refresh();
  button.textContent = 'Service de démonstration chargé';
});
refresh();
