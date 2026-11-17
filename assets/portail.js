/* Portail Scolarité — moteur partagé des écrans.
   Les données vivent sur le serveur (serveur/portail.py) : authentification, rôles,
   règles du workflow, notifications et pièces justificatives. Ce fichier charge l'état
   de l'utilisateur connecté, relaie les actions à l'API et garde la même interface
   P.* que le prototype, pour que les écrans restent inchangés. */
(function () {
  const DAY = 86400000;
  const UNIVERSITE = 'Université — nom à préciser';
  // Espace de la page : l'en-tête étudiant ou la barre latérale du back-office.
  const ESPACE = document.getElementById('s-top') ? 'etudiant' : document.getElementById('a-side') ? 'agent' : null;

  const SERVICES = {
    centrale: 'Scolarité centrale',
    composante: 'Scolarité de la composante',
    diplomes: 'Bureau des diplômes',
    stages: 'Bureau des stages',
    accueil: 'Accueil – cartes étudiantes',
  };

  const ANNEES = ['2026-2027', '2025-2026', '2024-2025'];

  // Chaque type porte son service de destination, son délai cible (jours ouvrés)
  // et ses champs ; showIf rend le formulaire adaptatif.
  const TYPES = [
    {
      id: 'attestation', label: 'Attestation de scolarité', service: 'centrale', sla: 2,
      desc: 'Justificatif d’inscription pour la CAF, une bourse, les transports ou un employeur.',
      fields: [
        { id: 'annee', label: 'Année universitaire', type: 'select', options: ANNEES, required: true, def: ANNEES[0] },
        { id: 'motif', label: 'Motif', type: 'radio', options: ['CAF / logement', 'Bourse', 'Transports', 'Employeur', 'Autre'], required: true, def: 'CAF / logement' },
        { id: 'motif_autre', label: 'Précisez le motif', type: 'text', required: true, showIf: d => d.motif === 'Autre' },
        { id: 'format', label: 'Format', type: 'radio', options: ['Numérique (PDF signé)', 'Papier'], required: true, def: 'Numérique (PDF signé)' },
        { id: 'exemplaires', label: 'Nombre d’exemplaires', type: 'number', min: 1, max: 3, def: 1, showIf: d => d.format === 'Papier' },
        { id: 'retrait', label: 'Mode de remise', type: 'radio', options: ['Retrait au guichet', 'Envoi postal'], required: true, def: 'Retrait au guichet', showIf: d => d.format === 'Papier' },
        { id: 'adresse', label: 'Adresse postale', type: 'textarea', required: true, showIf: d => d.format === 'Papier' && d.retrait === 'Envoi postal', help: 'Délai d’acheminement postal non inclus dans le délai cible.' },
      ],
    },
    {
      id: 'releve', label: 'Relevé de notes', service: 'composante', sla: 5,
      desc: 'Relevé officiel d’un ou plusieurs semestres, en français ou en anglais.',
      fields: [
        { id: 'annee', label: 'Année universitaire', type: 'select', options: ANNEES, required: true, def: ANNEES[1] },
        { id: 'semestres', label: 'Semestres concernés', type: 'checkbox', options: ['S1', 'S2', 'S3', 'S4', 'S5', 'S6'], required: true, def: [] },
        { id: 'session', label: 'Session', type: 'radio', options: ['Session 1', 'Session 2 (rattrapage)'], required: true, def: 'Session 1' },
        { id: 'langue', label: 'Langue', type: 'radio', options: ['Français', 'Anglais'], required: true, def: 'Français' },
        { id: 'destinataire', label: 'Établissement destinataire', type: 'text', required: true, showIf: d => d.langue === 'Anglais', help: 'Le relevé en anglais est transmis au bureau des relations internationales pour visa : +2 jours ouvrés.' },
        { id: 'cachet', label: 'Avec cachet et signature originale', type: 'switch', def: true },
      ],
      extraSla: d => (d.langue === 'Anglais' ? 2 : 0),
    },
    {
      id: 'reussite', label: 'Attestation de réussite', service: 'diplomes', sla: 7,
      desc: 'Atteste l’obtention d’un diplôme en attendant le parchemin officiel.',
      fields: [
        { id: 'diplome', label: 'Diplôme', type: 'select', options: ['Licence', 'Licence professionnelle', 'Master 1', 'Master 2', 'DUT / BUT'], required: true, def: 'Licence' },
        { id: 'annee', label: 'Année d’obtention', type: 'select', options: ANNEES, required: true, def: ANNEES[1] },
        { id: 'parcours', label: 'Mention / parcours', type: 'text', required: true },
        { id: 'parchemin', label: 'Demander aussi le parchemin du diplôme', type: 'switch', def: false },
        { id: 'piece', label: 'Pièce d’identité (recto/verso)', type: 'file', required: true, showIf: d => d.parchemin, help: 'Exigée pour la remise du parchemin original.' },
      ],
    },
    {
      id: 'convention', label: 'Convention de stage', service: 'stages', sla: 5,
      desc: 'Convention tripartite entre vous, l’organisme d’accueil et l’université.',
      fields: [
        { id: 'organisme', label: 'Organisme d’accueil', type: 'text', required: true },
        { id: 'tuteur', label: 'Tuteur en entreprise', type: 'text', required: true },
        { id: 'tuteur_email', label: 'E-mail du tuteur', type: 'email', required: true },
        { id: 'debut', label: 'Date de début', type: 'date', required: true },
        { id: 'fin', label: 'Date de fin', type: 'date', required: true },
        { id: 'etranger', label: 'Stage à l’étranger', type: 'switch', def: false },
        { id: 'pays', label: 'Pays', type: 'text', required: true, showIf: d => d.etranger },
        { id: 'assurance', label: 'Attestation d’assurance rapatriement', type: 'file', required: true, showIf: d => d.etranger },
      ],
    },
    {
      id: 'carte', label: 'Duplicata de carte étudiante', service: 'accueil', sla: 3,
      desc: 'Remplacement d’une carte perdue, volée ou abîmée.',
      fields: [
        { id: 'raison', label: 'Raison', type: 'radio', options: ['Perte', 'Vol', 'Carte abîmée'], required: true, def: 'Perte' },
        { id: 'declaration', label: 'Récépissé de déclaration de vol', type: 'file', required: true, showIf: d => d.raison === 'Vol' },
        { id: 'photo', label: 'Nouvelle photo d’identité', type: 'file', required: false, help: 'Facultatif : sinon la photo de votre dossier est réutilisée.' },
      ],
    },
  ];
  const typeById = id => TYPES.find(t => t.id === id);

  const STATUS = {
    soumise: { label: 'Soumise', short: 'Soumise' },
    en_cours: { label: 'En cours de traitement', short: 'En cours' },
    info_requise: { label: 'Complément demandé', short: 'Complément' },
    prete: { label: 'Prête', short: 'Prête' },
    refusee: { label: 'Refusée', short: 'Refusée' },
  };
  const OPEN = ['soumise', 'en_cours', 'info_requise'];
  const CLOSED = ['prete', 'refusee'];

  /* ── Jours ouvrés ────────────────────────────────────── */
  const isWeekend = d => d.getDay() === 0 || d.getDay() === 6;
  function addBusinessDays(ts, n) {
    const d = new Date(ts); let left = n;
    while (left > 0) { d.setTime(d.getTime() + DAY); if (!isWeekend(d)) left--; }
    return d.getTime();
  }
  function businessDaysBetween(a, b) {
    if (b <= a) return 0;
    let n = 0; const d = new Date(a);
    while (d.getTime() + DAY <= b) { d.setTime(d.getTime() + DAY); if (!isWeekend(d)) n++; }
    const rest = (b - d.getTime()) / DAY;
    return n + (isWeekend(d) ? 0 : rest);
  }
  const slaOf = r => { const t = typeById(r.type); return t.sla + (t.extraSla ? t.extraSla(r.data || {}) : 0); };
  const dueOf = r => addBusinessDays(r.createdAt, slaOf(r));
  const isLate = r => (r.closedAt || Date.now()) > dueOf(r);

  function defaultsFor(type) {
    const d = {};
    type.fields.forEach(f => { if (f.def !== undefined) d[f.id] = Array.isArray(f.def) ? [...f.def] : f.def; });
    return d;
  }

  /* ── Client API ──────────────────────────────────────── */
  class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }
  const loginUrl = espace => 'connexion.html?espace=' + espace + '&suite=' + encodeURIComponent(location.pathname + location.search);

  // Appels synchrones : les écrans attendent un résultat immédiat (référence créée, statut à jour).
  function call(method, url, body, opts) {
    opts = opts || {};
    const espace = opts.espace || ESPACE;
    const xhr = new XMLHttpRequest();
    xhr.open(method, url, false);
    xhr.setRequestHeader('X-Espace', espace || '');
    if (body && !(body instanceof FormData)) xhr.setRequestHeader('Content-Type', 'application/json');
    try { xhr.send(body ? (body instanceof FormData ? body : JSON.stringify(body)) : null); }
    catch (e) { throw new ApiError(0, 'Serveur du portail injoignable. Lancez « python serveur/portail.py » puis rechargez la page.'); }
    let json = null; try { json = JSON.parse(xhr.responseText); } catch (e) {}
    if (xhr.status === 401 && !opts.noRedirect) { location.href = loginUrl(espace); throw new ApiError(401, 'Session expirée.'); }
    if (xhr.status < 200 || xhr.status >= 300) throw new ApiError(xhr.status, (json && json.error) || 'Serveur du portail injoignable (' + (xhr.status || 'aucune réponse') + ').');
    if (url === '/api/state') etag = xhr.getResponseHeader('ETag');
    return json;
  }

  const EMPTY = { version: 1, role: null, demo: false, agents: [], requests: [], notifications: [], prefs: {}, profile: null };
  let state, etag = null, snapshot = null;
  function adopt(next) {
    state = next;
    // Copie de référence pour détecter ce que l'écran a modifié avant P.save().
    snapshot = JSON.stringify({ read: state.notifications.filter(n => n.read).map(n => n.id), prefs: state.prefs, profile: state.profile });
    return state;
  }
  function load() {
    if (!ESPACE) return adopt(Object.assign({}, EMPTY));
    try { return adopt(call('GET', '/api/state')); }
    catch (e) { if (e.status !== 401) setTimeout(() => toast('<b>Données indisponibles.</b> ' + esc(e.message)), 0); return adopt(Object.assign({}, EMPTY)); }
  }

  const channel = 'BroadcastChannel' in window ? new BroadcastChannel('portail-scolarite') : null;
  function mutate(method, url, body, opts) {
    try {
      const res = call(method, url, body, opts);
      if (res && res.state && (!opts || !opts.espace || opts.espace === ESPACE)) adopt(res.state);
      if (channel) channel.postMessage('maj');
      return res ? res.result : null;
    } catch (e) {
      if (e.status !== 401) {
        toast('<b>Action impossible.</b> ' + esc(e.message));
        if (ESPACE && e.status) { load(); setTimeout(fire, 0); }
      }
      throw e;
    }
  }

  // Envoie au serveur ce que l'écran a changé dans P.state (lectures, préférences, coordonnées).
  function save() {
    if (ESPACE !== 'etudiant' || !snapshot) return;
    const before = JSON.parse(snapshot), diff = {};
    const read = state.notifications.filter(n => n.read && !before.read.includes(n.id)).map(n => n.id);
    if (read.length) diff.read = read;
    if (JSON.stringify(state.prefs) !== JSON.stringify(before.prefs)) diff.prefs = state.prefs;
    if (JSON.stringify(state.profile) !== JSON.stringify(before.profile)) diff.profile = state.profile;
    if (Object.keys(diff).length) mutate('POST', '/api/moi', diff);
  }
  function reset() {
    try { return mutate('POST', '/api/demo/reinitialiser', {}, { espace: 'agent', noRedirect: true }); }
    catch (e) { if (e.status === 401) toast('Connectez-vous à l’<a href="' + loginUrl('agent') + '">espace scolarité</a> pour réinitialiser les données.'); throw e; }
  }
  function logout() {
    try { call('POST', '/api/logout', {}, { noRedirect: true }); } catch (e) {}
    if (channel) channel.postMessage('maj');
    location.href = 'connexion.html?espace=' + ESPACE;
  }

  const get = id => state.requests.find(r => r.id === id);
  const mineList = () => state.requests.filter(r => ME.id && r.student.id === ME.id).sort((a, b) => b.createdAt - a.createdAt);
  const unread = () => state.notifications.filter(n => !n.read).length;

  function createRequest(typeId, data, files) {
    const form = new FormData();
    form.append('payload', JSON.stringify({ type: typeId, data }));
    Object.entries(files || {}).forEach(([k, f]) => { if (f instanceof Blob) form.append(k, f, f.name); });
    return get(mutate('POST', '/api/demandes', form).id);
  }
  function transition(id, status, note) {
    const req = get(id); if (!req) return;
    mutate('POST', '/api/demandes/' + encodeURIComponent(id) + '/statut', { status, note: note || '', from: req.status });
    return get(id);
  }
  function answerInfo(id, text, file) {
    const form = new FormData();
    form.append('payload', JSON.stringify({ text }));
    if (file instanceof Blob) form.append('fichier', file, file.name);
    mutate('POST', '/api/demandes/' + encodeURIComponent(id) + '/complement', form);
    return get(id);
  }
  const remind = id => !!(mutate('POST', '/api/demandes/' + encodeURIComponent(id) + '/relance', {}) || {}).ok;
  function transfer(id, service) { mutate('POST', '/api/demandes/' + encodeURIComponent(id) + '/transfert', { service }); return true; }

  // Pièces justificatives réellement déposées (téléchargement contrôlé par le serveur).
  const FILE_LABEL = { complement: 'Complément de l’étudiant·e' };
  function attachmentsHTML(r) {
    if (!r.files || !r.files.length) return '';
    const t = typeById(r.type);
    const label = f => FILE_LABEL[f.field] || (t.fields.find(x => x.id === f.field) || {}).label || 'Pièce jointe';
    const size = n => n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' Ko' : (n / 1048576).toLocaleString('fr-FR', { maximumFractionDigits: 1 }) + ' Mo';
    return '<dl class="kv">' + r.files.map(f => '<dt>' + esc(label(f)) + '</dt><dd><a href="/api/fichiers/' + f.id + '?espace=' + ESPACE + '" download="' + esc(f.name) + '">' + esc(f.name) + '</a> <span class="meta">· ' + size(f.size) + '</span></dd>').join('') + '</dl>';
  }

  /* ── Formats ─────────────────────────────────────────── */
  function downloadDemo(id) {
    const req = get(id); if (!req || req.student.id !== ME.id || req.status !== 'prete') return;
    const rows = [['Référence', req.id], ['Demandeur', req.student.name], ['Document', typeById(req.type).label], ...dataRows(req)];
    const text = 'PORTAIL SCOLARITÉ - DÉMONSTRATION\nSans valeur administrative. Aucune signature officielle.\n\n' + rows.map(([k,v]) => k + ' : ' + v).join('\n');
    const url = URL.createObjectURL(new Blob([text], {type:'text/plain;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = req.id + '-demonstration.txt';
    document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const fmtDate = ts => new Date(ts).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
  const fmtShort = ts => new Date(ts).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
  const fmtTime = ts => new Date(ts).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  function fmtRel(ts) {
    const diff = Date.now() - ts, m = Math.round(diff / 60000);
    if (m < 1) return 'à l’instant';
    if (m < 60) return 'il y a ' + m + ' min';
    const h = Math.round(m / 60); if (h < 24) return 'il y a ' + h + ' h';
    const d = Math.round(h / 24); if (d < 7) return d === 1 ? 'hier' : 'il y a ' + d + ' jours';
    return 'le ' + fmtShort(ts);
  }
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const badge = st => '<span class="badge st-' + st + '">' + STATUS[st].short + '</span>';
  function dueLabel(r) {
    if (CLOSED.includes(r.status)) return r.closedAt <= dueOf(r) ? '<span class="meta">Dans le délai</span>' : '<span class="late">Hors délai</span>';
    const d = dueOf(r), days = Math.ceil((d - Date.now()) / DAY);
    if (days < 0) return '<span class="late">En retard de ' + (-days) + ' j</span>';
    if (days === 0) return '<span class="late">Aujourd’hui</span>';
    return '<span>' + fmtShort(d) + '</span> <span class="meta">· J-' + days + '</span>';
  }
  function dataRows(req) {
    const t = typeById(req.type);
    return t.fields.filter(f => !f.showIf || f.showIf(req.data)).map(f => {
      let v = req.data[f.id];
      if (f.type === 'switch') v = v ? 'Oui' : 'Non';
      else if (Array.isArray(v)) v = v.join(', ');
      else if (f.type === 'date' && v) v = fmtDate(v);
      if (v === undefined || v === '') v = '—';
      return [f.label, v];
    });
  }

  function timeline(req, newestFirst) {
    const title = h => h.auto ? 'Acheminement automatique' : ({
      soumise: 'Demande déposée', en_cours: 'Prise en charge par ' + h.by, info_requise: 'Complément demandé par ' + h.by,
      complement: 'Complément envoyé par l’étudiant·e', prete: 'Document prêt', refusee: 'Demande refusée par ' + h.by }[h.status]);
    const items = req.history.slice(); if (newestFirst) items.reverse();
    return '<ol class="timeline">' + items.map(h => '<li class="t-' + (h.auto ? 'auto' : h.status) + '"><div class="t-title">' + esc(title(h)) + '</div><div class="meta">' + fmtTime(h.at) + (h.auto ? ' · Power Automate' : '') + '</div>' +
      (h.note && !h.auto ? '<div class="t-note">' + esc(h.note) + '</div>' : h.auto ? '<div class="meta">' + esc(h.note) + '</div>' : '') + '</li>').join('') + '</ol>';
  }
  function stepsHTML(req) {
    const s = req.status;
    const a = 'done', b = s === 'soumise' ? '' : (CLOSED.includes(s) ? 'done' : 'current');
    const c = s === 'prete' ? 'ok' : s === 'refusee' ? 'ko' : '';
    const l2 = s === 'info_requise' ? 'Complément demandé' : 'En cours de traitement';
    return '<div class="steps" aria-label="Avancement : ' + STATUS[s].label + '"><div class="step ' + a + '"><span class="bar"></span>Soumise</div><div class="step ' + b + '"><span class="bar"></span>' + l2 + '</div><div class="step ' + c + '"><span class="bar"></span>' + (s === 'refusee' ? 'Refusée' : 'Prête') + '</div></div>';
  }

  /* ── Interface commune ───────────────────────────────── */
  const ICON = {
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
    list: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/></svg>',
    bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9Z"/><path d="M10 20a2.2 2.2 0 0 0 4 0"/></svg>',
    inbox: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 13h5l1.5 3h5L16 13h5"/><path d="M5 5h14l2 8v6H3v-6Z"/></svg>',
    chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/></svg>',
    swap: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7h13l-3-3M17 17H4l3 3"/></svg>',
    download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11m0 0 4-4m-4 4-4-4M5 20h14"/></svg>',
    trend: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>',
  };

  // Logo : toque universitaire dans un écusson.

  function mountStudent(active) {
    const n = unread();
    const links = [['nouvelle', 'nouvelle-demande.html', 'Nouvelle demande', ICON.plus], ['suivi', 'mes-demandes.html', 'Mes demandes', ICON.list], ['notifs', 'notifications.html', 'Notifications', ICON.bell]];
    const top = document.getElementById('s-top');
    top.className = 's-top'; top.setAttribute('data-od-id', 'student-header');
    top.innerHTML = '<div class="s-top-inner"><a class="brand" href="mes-demandes.html" aria-label="Portail Scolarité — mes demandes"><img class="s-logo" src="assets/logo-ensa-khouribga.png" alt="ENSA Khouribga"></a>' +
      '<nav class="s-nav" aria-label="Navigation principale">' + links.map(([k, h, l]) => '<a href="' + h + '" data-od-id="nav-' + k + '"' + (k === active ? ' aria-current="page"' : '') + '>' + l + (k === 'notifs' && n ? ' <span class="dot-count" data-unread>' + n + '</span>' : '') + '</a>').join('') + '</nav>' +
      '<a class="s-user" href="profil.html" data-od-id="nav-profil" aria-label="Mon profil, ' + esc(ME.name) + '"' + (active === 'profil' ? ' aria-current="page"' : '') + '><div class="who"><b>' + esc(ME.name) + '</b><span>' + esc(ME.programme) + '</span></div><div class="avatar" aria-hidden="true">' + esc(ME.initials) + '</div></a></div>';
    document.querySelectorAll('.s-tabbar').forEach(n => n.remove());
    const bar = document.createElement('nav'); bar.className = 's-tabbar'; bar.setAttribute('aria-label', 'Navigation');
    bar.innerHTML = links.map(([k, h, l, ic]) => '<a href="' + h + '"' + (k === active ? ' aria-current="page"' : '') + '>' + ic + (k === 'notifs' && n ? '<span class="dot-count">' + n + '</span>' : '') + '<span>' + l.replace('Nouvelle demande', 'Nouvelle') + '</span></a>').join('');
    document.body.appendChild(bar);
  }

  function mountAgent(active) {
    const open = state.requests.filter(r => OPEN.includes(r.status));
    const late = open.filter(isLate).length;
    const side = document.getElementById('a-side');
    side.className = 'a-side'; side.setAttribute('data-od-id', 'agent-sidebar');
    side.innerHTML = '<a class="brand" href="index.html" aria-label="Portail Scolarité — accueil"><img class="a-logo" src="assets/logo-ensa-khouribga.png" alt="ENSA Khouribga"></a>' +
      '<nav class="a-nav" aria-label="Back-office"><div class="eyebrow">Traitement</div>' +
      '<a href="file-traitement.html" data-od-id="nav-file"' + (active === 'file' ? ' aria-current="page"' : '') + '>' + ICON.inbox + 'File de traitement <span class="n' + (late ? ' alert' : '') + '" title="' + late + ' en retard">' + (late || open.length) + '</span></a>' +
      '<a href="tableau-de-bord.html" data-od-id="nav-dashboard"' + (active === 'dash' ? ' aria-current="page"' : '') + '>' + ICON.chart + 'Tableau de bord</a>' +
      '<a href="statistiques.html" data-od-id="nav-stats"' + (active === 'stats' ? ' aria-current="page"' : '') + '>' + ICON.trend + 'Statistiques</a></nav>' +
      '<nav class="a-nav" aria-label="Autres espaces"><div class="eyebrow">Prototype</div><a href="mes-demandes.html" data-od-id="nav-student">' + ICON.swap + 'Espace étudiant</a><a href="connexion.html?espace=agent" data-logout data-od-id="btn-logout">' + ICON.back + 'Se déconnecter</a></nav>' +
      '<div class="a-me"><div class="avatar" aria-hidden="true">' + esc(AGENT.initials) + '</div><div><b>' + esc(AGENT.name) + '</b><span>' + esc(AGENT.service) + '</span></div></div>';
  }

  function toast(html) {
    let z = document.querySelector('.toast-zone');
    if (!z) { z = document.createElement('div'); z.className = 'toast-zone'; z.setAttribute('role', 'status'); z.setAttribute('aria-live', 'polite'); document.body.appendChild(z); }
    const t = document.createElement('div'); t.className = 'toast'; t.innerHTML = html; z.appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  /* ── Mises à jour en direct ──────────────────────────── */
  // Interrogation légère du serveur (ETag) + signal immédiat entre onglets du même navigateur.
  const listeners = [];
  let pending = false;
  function busy() {
    const a = document.activeElement;
    return (a && a.matches && a.matches('textarea, input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit])') && a.value) || !!document.querySelector('dialog[open]');
  }
  function fire() {
    if (busy()) { pending = true; return; }
    pending = false;
    listeners.forEach(fn => fn());
  }
  let polling = false;
  async function poll() {
    if (!ESPACE || polling || document.visibilityState === 'hidden') return;
    polling = true;
    try {
      const res = await fetch('/api/state', { headers: { 'X-Espace': ESPACE, 'If-None-Match': etag || '' }, cache: 'no-store' });
      if (res.status === 401) { location.href = loginUrl(ESPACE); return; }
      if (res.status === 200) { etag = res.headers.get('ETag'); adopt(await res.json()); fire(); }
    } catch (e) { /* serveur momentanément indisponible : nouvel essai au prochain cycle */ }
    finally { polling = false; }
  }
  function onExternalChange(fn) {
    listeners.push(fn);
    if (listeners.length > 1) return;
    setInterval(() => { if (pending && !busy()) fire(); else poll(); }, 8000);
    document.addEventListener('visibilitychange', poll);
    document.addEventListener('focusout', () => setTimeout(() => { if (pending && !busy()) fire(); }, 0));
    if (channel) channel.onmessage = poll;
  }

  load();
  const ME = ESPACE === 'etudiant' && state.me ? state.me : { id: null, name: '', initials: '', programme: '', email: '' };
  const AGENT = ESPACE === 'agent' && state.agent ? state.agent : { name: '', initials: '', service: '' };
  const AGENTS = state.agents || [];
  document.addEventListener('click', e => { if (e.target.closest && e.target.closest('[data-logout]')) { e.preventDefault(); logout(); } });

  window.P = { DAY, UNIVERSITE, ME, AGENT, AGENTS, SERVICES, TYPES, STATUS, OPEN, CLOSED, typeById, get state() { return state; },
    load, save, reset, logout, get, mineList, unread, createRequest, transition, answerInfo, remind, transfer, downloadDemo, attachmentsHTML,
    addBusinessDays, businessDaysBetween, slaOf, dueOf, isLate, defaultsFor,
    fmtDate, fmtShort, fmtTime, fmtRel, esc, badge, dueLabel, dataRows, timeline, stepsHTML, ICON, mountStudent, mountAgent, toast, onExternalChange };
})();
