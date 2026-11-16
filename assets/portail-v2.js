/* Portail Scolarité — moteur partagé du prototype.
   Équivalent Power Platform : table Dataverse « Demande » + flux Power Automate
   (acheminement, transitions de statut, notifications). Ici tout vit en localStorage
   pour que les écrans étudiant et agent partagent le même état. */
(function () {
  const KEY = 'portail-scolarite-v1';
  const DAY = 86400000;
  const UNIVERSITE = 'Université — nom à préciser';

  const ME = { id: 'E21400187', name: 'Inès Benali', initials: 'IB', programme: 'Licence 3 Économie-Gestion', email: 'ines.benali@etu.universite.fr' };
  const AGENT = { name: 'Samira Haddad', initials: 'SH', service: 'Scolarité centrale' };
  const AGENTS = ['Samira Haddad', 'Julien Durand', 'Claire Lefèvre', 'Moussa Ndiaye'];

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

  /* ── Données de démonstration ────────────────────────── */
  function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  const STUDENTS = ['Yanis Martin', 'Léa Dubois', 'Omar El Idrissi', 'Chloé Bernard', 'Hugo Petit', 'Aya Benjelloun', 'Lucas Moreau', 'Sarah Cohen', 'Nathan Girard', 'Fatou Diallo', 'Emma Roux', 'Karim Mansouri', 'Manon Fournier', 'Théo Lambert', 'Zoé Garnier', 'Rayan Haddou', 'Camille Faure', 'Adam Chevalier'];
  const PROGRAMMES = ['Licence 1 Droit', 'Licence 2 Psychologie', 'Licence 3 Économie-Gestion', 'Master 1 Finance', 'Master 2 Data Science', 'BUT GEA 2'];

  function defaultsFor(type) {
    const d = {};
    type.fields.forEach(f => { if (f.def !== undefined) d[f.id] = Array.isArray(f.def) ? [...f.def] : f.def; });
    return d;
  }
  function demoData(type, r) {
    const d = defaultsFor(type);
    if (type.id === 'releve') d.semestres = r() > .5 ? ['S3', 'S4'] : ['S5'];
    if (type.id === 'reussite') d.parcours = 'Économie-Gestion, parcours Finance';
    if (type.id === 'convention') { d.organisme = ['Crédit Agricole', 'Decathlon', 'Mairie de Lyon', 'Capgemini', 'Clinique du Parc'][Math.floor(r() * 5)]; d.tuteur = 'M. Leroy'; d.tuteur_email = 'tuteur@organisme.fr'; d.debut = '2027-02-01'; d.fin = '2027-06-30'; }
    return d;
  }

  function seed() {
    const r = rng(20261015);
    const now = Date.now();
    const weights = [['attestation', .32], ['releve', .24], ['convention', .18], ['reussite', .14], ['carte', .12]];
    const pickType = () => { let x = r(), acc = 0; for (const [id, w] of weights) { acc += w; if (x <= acc) return id; } return 'attestation'; };
    const requests = [];
    let seq = 300;
    for (let i = 0; i < 64; i++) {
      const type = typeById(pickType());
      const age = Math.floor(r() * 84 * r() + r() * 6);
      const createdAt = now - age * DAY - Math.floor(r() * 8) * 3600000;
      const name = STUDENTS[Math.floor(r() * STUDENTS.length)];
      const req = {
        id: 'DEM-2026-' + String(++seq).padStart(4, '0'), type: type.id, service: type.service,
        student: { id: 'E2' + Math.floor(1e7 + r() * 9e7), name, programme: PROGRAMMES[Math.floor(r() * PROGRAMMES.length)] },
        data: demoData(type, r), createdAt, status: 'soumise', agent: null, closedAt: null, history: [],
      };
      req.history.push({ status: 'soumise', at: createdAt, by: name, note: '' });
      req.history.push({ auto: true, at: createdAt + 60000, by: 'Flux automatique', note: 'Acheminée vers ' + SERVICES[type.service] + ' · délai cible ' + slaOf(req) + ' j ouvrés' });
      const agent = AGENTS[Math.floor(r() * AGENTS.length)];
      const sla = slaOf(req);
      const takeAt = Math.min(now - 3600000, addBusinessDays(createdAt, 1) - Math.floor(r() * 20) * 3600000);
      if (age > 16) {
        const proc = Math.max(1, Math.round(sla * (0.3 + r() * 1.2)));
        const closedAt = Math.min(now - DAY, addBusinessDays(createdAt, proc));
        req.agent = agent;
        req.history.push({ status: 'en_cours', at: Math.min(takeAt, closedAt - 3600000), by: agent, note: '' });
        const refused = r() < .1;
        req.status = refused ? 'refusee' : 'prete'; req.closedAt = closedAt;
        req.history.push({ status: req.status, at: closedAt, by: agent, note: refused ? 'Dossier incomplet : pièce justificative manquante.' : '' });
      } else if (age > 2) {
        const x = r();
        req.agent = agent;
        req.history.push({ status: 'en_cours', at: takeAt, by: agent, note: '' });
        if (x < .18) { req.status = 'info_requise'; req.history.push({ status: 'info_requise', at: takeAt + 5 * 3600000, by: agent, note: 'Merci de joindre la pièce justificative demandée.' }); }
        else if (x < .45) { req.status = 'prete'; req.closedAt = Math.min(now - 3600000, addBusinessDays(createdAt, Math.max(1, Math.round(sla * (.5 + r()))))); req.history.push({ status: 'prete', at: req.closedAt, by: agent, note: '' }); }
        else req.status = 'en_cours';
      } else if (r() < .45 && age >= 1) {
        req.agent = agent; req.status = 'en_cours'; req.history.push({ status: 'en_cours', at: takeAt, by: agent, note: '' });
      }
      requests.push(req);
    }

    // Demandes de l'étudiante connectée, scénarisées
    const mine = (type, ageDays, steps, data) => {
      const t = typeById(type); const createdAt = now - ageDays * DAY - 3 * 3600000;
      const req = { id: 'DEM-2026-' + String(++seq).padStart(4, '0'), type, service: t.service, student: { id: ME.id, name: ME.name, programme: ME.programme }, data: Object.assign(defaultsFor(t), data), createdAt, status: 'soumise', agent: null, closedAt: null, history: [] };
      req.history.push({ status: 'soumise', at: createdAt, by: ME.name, note: '' });
      req.history.push({ auto: true, at: createdAt + 60000, by: 'Flux automatique', note: 'Acheminée vers ' + SERVICES[t.service] + ' · délai cible ' + slaOf(req) + ' j ouvrés' });
      steps.forEach(([status, hoursAfter, by, note]) => {
        const at = createdAt + hoursAfter * 3600000;
        req.history.push({ status, at, by, note: note || '' }); req.status = status;
        if (status === 'en_cours') req.agent = by;
        if (CLOSED.includes(status)) req.closedAt = at;
      });
      requests.push(req); return req;
    };
    const a = mine('attestation', 9, [['en_cours', 20, 'Samira Haddad'], ['prete', 26, 'Samira Haddad', 'Votre attestation signée est disponible en téléchargement.']], { motif: 'CAF / logement' });
    const b = mine('reussite', 21, [['en_cours', 30, 'Claire Lefèvre'], ['refusee', 52, 'Claire Lefèvre', 'Les résultats de la Licence 3 ne sont pas encore délibérés. Vous pourrez redéposer la demande après le jury du 2 juillet.']], { diplome: 'Licence', parcours: 'Économie-Gestion' });
    const c = mine('releve', 4, [['en_cours', 22, 'Julien Durand'], ['info_requise', 30, 'Julien Durand', 'Souhaitez-vous le relevé de la session 1 ou celui intégrant le rattrapage du S5 ? Merci de préciser.']], { semestres: ['S5'], annee: ANNEES[1] });
    const d = mine('convention', 2, [['en_cours', 18, 'Moussa Ndiaye']], { organisme: 'Banque Populaire Auvergne-Rhône-Alpes', tuteur: 'Mme Garcia', tuteur_email: 'l.garcia@bpaura.fr', debut: '2027-01-11', fin: '2027-04-30' });

    const notifications = [];
    const notif = (req, at, kind, title, body, read) => notifications.push({ id: 'N' + notifications.length + '-' + req.id, reqId: req.id, at, kind, title, body, read });
    notif(b, b.createdAt + 60000, 'soumise', 'Demande reçue', 'Votre demande d’attestation de réussite a été transmise au Bureau des diplômes.', true);
    notif(b, b.closedAt, 'refusee', 'Demande refusée', 'Attestation de réussite : ' + b.history[b.history.length - 1].note, true);
    notif(a, a.createdAt + 60000, 'soumise', 'Demande reçue', 'Votre demande d’attestation de scolarité a été transmise à la Scolarité centrale.', true);
    notif(a, a.closedAt, 'prete', 'Document prêt', 'Votre attestation de scolarité est disponible en téléchargement.', true);
    notif(c, c.createdAt + 60000, 'soumise', 'Demande reçue', 'Votre demande de relevé de notes a été transmise à la Scolarité de la composante.', true);
    notif(c, c.history[c.history.length - 1].at, 'info_requise', 'Information complémentaire requise', 'Relevé de notes : ' + c.history[c.history.length - 1].note, false);
    notif(d, d.createdAt + 60000, 'soumise', 'Demande reçue', 'Votre convention de stage a été transmise au Bureau des stages.', true);
    notif(d, d.history[d.history.length - 1].at, 'en_cours', 'Prise en charge', 'Moussa Ndiaye (Bureau des stages) traite votre convention de stage.', false);

    return { version: 1, seq, requests, notifications, prefs: { email: true, sms: false, push: true } };
  }

  /* ── Stockage ────────────────────────────────────────── */
  let state;
  function load() {
    try { state = JSON.parse(localStorage.getItem(KEY)); } catch (e) { state = null; }
    if (!state || state.version !== 1) { state = seed(); save(); }
    return state;
  }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }
  function reset() { state = seed(); save(); return state; }
  const get = id => state.requests.find(r => r.id === id);
  const mineList = () => state.requests.filter(r => r.student.id === ME.id).sort((a, b) => b.createdAt - a.createdAt);
  const unread = () => state.notifications.filter(n => !n.read).length;

  function notifyStudent(req, kind, title, body) {
    if (req.student.id !== ME.id) return;
    state.notifications.push({ id: 'N' + Date.now() + Math.random().toString(36).slice(2, 6), reqId: req.id, at: Date.now(), kind, title, body, read: false });
  }

  function createRequest(typeId, data) {
    const t = typeById(typeId); const now = Date.now();
    const req = { id: 'DEM-2026-' + String(++state.seq).padStart(4, '0'), type: typeId, service: t.service, student: { id: ME.id, name: ME.name, programme: ME.programme }, data, createdAt: now, status: 'soumise', agent: null, closedAt: null, history: [] };
    req.history.push({ status: 'soumise', at: now, by: ME.name, note: '' });
    req.history.push({ auto: true, at: now + 1000, by: 'Flux automatique', note: 'Acheminée vers ' + SERVICES[t.service] + ' · délai cible ' + slaOf(req) + ' j ouvrés' });
    state.requests.push(req);
    notifyStudent(req, 'soumise', 'Demande reçue', t.label + ' : transmise à ' + SERVICES[t.service] + '. Disponibilité estimée le ' + fmtDate(dueOf(req)) + '.');
    save(); return req;
  }

  const NOTIF_TEXT = {
    en_cours: (req, t) => ['Prise en charge', req.agent + ' (' + SERVICES[req.service] + ') traite votre demande : ' + t.label.toLowerCase() + '.'],
    info_requise: (req, t, note) => ['Information complémentaire requise', t.label + ' : ' + note],
    prete: (req, t, note) => ['Document prêt', t.label + ' disponible. ' + (note || '')],
    refusee: (req, t, note) => ['Demande refusée', t.label + ' : ' + note],
  };
  function transition(id, status, note, by) {
    const req = get(id); if (!req) return;
    const t = typeById(req.type);
    req.status = status;
    if (status === 'en_cours' && !req.agent) req.agent = by || AGENT.name;
    req.closedAt = CLOSED.includes(status) ? Date.now() : null;
    req.history.push({ status, at: Date.now(), by: by || AGENT.name, note: note || '' });
    const [title, body] = NOTIF_TEXT[status](req, t, note);
    notifyStudent(req, status, title, body);
    save(); return req;
  }
  function answerInfo(id, text, fileName) {
    const req = get(id); if (!req) return;
    req.history.push({ status: 'complement', at: Date.now(), by: ME.name, note: text + (fileName ? ' · Pièce jointe : ' + fileName : '') });
    req.status = 'en_cours';
    req.history.push({ auto: true, at: Date.now() + 1000, by: 'Flux automatique', note: 'Complément reçu : demande renvoyée à ' + (req.agent || SERVICES[req.service]) });
    save(); return req;
  }

  /* ── Formats ─────────────────────────────────────────── */
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
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>',
  };

  function mountStudent(active) {
    const n = unread();
    const links = [['nouvelle', 'nouvelle-demande.html', 'Nouvelle demande', ICON.plus], ['suivi', 'mes-demandes.html', 'Mes demandes', ICON.list], ['notifs', 'notifications.html', 'Notifications', ICON.bell]];
    const top = document.getElementById('s-top');
    top.className = 's-top'; top.setAttribute('data-od-id', 'student-header');
    top.innerHTML = '<div class="s-top-inner"><a class="brand" href="index.html" data-od-id="brand"><b>Portail Scolarité</b><small>' + UNIVERSITE + '</small></a>' +
      '<nav class="s-nav" aria-label="Navigation principale">' + links.map(([k, h, l]) => '<a href="' + h + '" data-od-id="nav-' + k + '"' + (k === active ? ' aria-current="page"' : '') + '>' + l + (k === 'notifs' && n ? ' <span class="dot-count" data-unread>' + n + '</span>' : '') + '</a>').join('') + '</nav>' +
      '<div class="s-user"><div class="who"><b>' + ME.name + '</b><span>' + ME.programme + '</span></div><div class="avatar" aria-hidden="true">' + ME.initials + '</div></div></div>';
    const bar = document.createElement('nav'); bar.className = 's-tabbar'; bar.setAttribute('aria-label', 'Navigation');
    bar.innerHTML = links.map(([k, h, l, ic]) => '<a href="' + h + '"' + (k === active ? ' aria-current="page"' : '') + '>' + ic + (k === 'notifs' && n ? '<span class="dot-count">' + n + '</span>' : '') + '<span>' + l.replace('Nouvelle demande', 'Nouvelle') + '</span></a>').join('');
    document.body.appendChild(bar);
  }

  function mountAgent(active) {
    const open = state.requests.filter(r => OPEN.includes(r.status));
    const late = open.filter(isLate).length;
    const side = document.getElementById('a-side');
    side.className = 'a-side'; side.setAttribute('data-od-id', 'agent-sidebar');
    side.innerHTML = '<a class="brand" href="index.html"><b>Scolarité</b><small>Back-office</small></a>' +
      '<nav class="a-nav" aria-label="Back-office"><div class="eyebrow">Traitement</div>' +
      '<a href="file-traitement.html" data-od-id="nav-file"' + (active === 'file' ? ' aria-current="page"' : '') + '>' + ICON.inbox + 'File de traitement <span class="n' + (late ? ' alert' : '') + '" title="' + late + ' en retard">' + (late || open.length) + '</span></a>' +
      '<a href="tableau-de-bord.html" data-od-id="nav-dashboard"' + (active === 'dash' ? ' aria-current="page"' : '') + '>' + ICON.chart + 'Tableau de bord</a></nav>' +
      '<nav class="a-nav" aria-label="Autres espaces"><div class="eyebrow">Prototype</div><a href="mes-demandes.html" data-od-id="nav-student">' + ICON.swap + 'Espace étudiant</a></nav>' +
      '<div class="a-me"><div class="avatar" aria-hidden="true">' + AGENT.initials + '</div><div><b>' + AGENT.name + '</b><span>' + AGENT.service + '</span></div></div>';
  }

  function toast(html) {
    let z = document.querySelector('.toast-zone');
    if (!z) { z = document.createElement('div'); z.className = 'toast-zone'; z.setAttribute('role', 'status'); z.setAttribute('aria-live', 'polite'); document.body.appendChild(z); }
    const t = document.createElement('div'); t.className = 'toast'; t.innerHTML = html; z.appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  // Les écrans ouverts dans d'autres onglets se mettent à jour en direct.
  function onExternalChange(fn) { window.addEventListener('storage', e => { if (e.key === KEY) { load(); fn(); } }); }

  load();
  window.P = { KEY, DAY, UNIVERSITE, ME, AGENT, AGENTS, SERVICES, TYPES, STATUS, OPEN, CLOSED, typeById, get state() { return state; },
    load, save, reset, get, mineList, unread, createRequest, transition, answerInfo,
    addBusinessDays, businessDaysBetween, slaOf, dueOf, isLate, defaultsFor,
    fmtDate, fmtShort, fmtTime, fmtRel, esc, badge, dueLabel, dataRows, timeline, stepsHTML, ICON, mountStudent, mountAgent, toast, onExternalChange };
})();
