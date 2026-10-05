// Fonctions pures partagées par app.js et par les tests (node, voir tests/test_web.py).
(function (scope) {
  const number = new Intl.NumberFormat('fr-FR');
  const severityText = {none: 'nominal', watch: 'surveillance', critical: 'critique'};

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[character]));
  }

  function plural(count, singular, pluralForm = `${singular}s`) {
    return `${number.format(count)} ${count > 1 ? pluralForm : singular}`;
  }

  // Décrit, à partir de la réponse réelle de /api/events, ce qu'un message du flux a produit.
  function describeResult(message, payload) {
    const id = message && typeof message.event_id === 'string' ? message.event_id : 'message sans identifiant';
    const line = message && typeof message.route_id === 'string' ? `, ligne ${message.route_id}` : '';
    if (!payload || payload.status === 'rejected') {
      return `${id}${line} : rejeté, ${payload && payload.error ? payload.error : 'motif inconnu'}.`;
    }
    if (payload.status === 'duplicate') return `${id}${line} : relecture absorbée, aucun doublon écrit.`;
    const decision = payload.decision || {};
    if (decision.severity && decision.severity !== 'none') {
      return `${id}${line} : accepté, alerte ${severityText[decision.severity] || decision.severity} ouverte.`;
    }
    return `${id}${line} : accepté, rien à signaler.`;
  }

  function summarizeRun(statuses) {
    const count = status => statuses.filter(item => item === status).length;
    return `Flux terminé : ${plural(statuses.length, 'message')}, ${plural(count('accepted'), 'accepté')}, ${plural(count('duplicate'), 'doublon')}, ${plural(count('rejected'), 'rejet')}.`;
  }

  const api = {escapeHtml, plural, describeResult, summarizeRun, severityText, number};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else scope.RoutierFormat = api;
})(typeof window !== 'undefined' ? window : globalThis);
