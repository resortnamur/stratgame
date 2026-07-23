"use strict";

/* Client web de Jeux Strat — étape 3a : lobby + vue de partie en direct.
 *
 * Trois écrans : identité (nom + jeton en localStorage), lobby (parties,
 * nouvelle partie, sauvegardes) et partie (carte canvas fidèle à x45,
 * sièges, chat, journal). Les actions de jeu viendront à l'étape 3b.
 */

// ---------------------------------------------------------------------------
// Constantes graphiques — mêmes valeurs que x45 pour un rendu fidèle
// ---------------------------------------------------------------------------

const COULEURS_JOUEURS = [
  [93, 109, 126], [84, 153, 199], [88, 214, 141], [244, 208, 63],
  [165, 105, 189], [236, 112, 99], [133, 193, 233], [118, 215, 196],
  [214, 162, 92], [127, 140, 141],
  [255, 87, 51], [52, 211, 153], [139, 92, 246], [251, 191, 36],
  [236, 72, 153], [20, 184, 166], [249, 115, 22], [99, 179, 237],
  [161, 220, 93], [248, 113, 113],
];
const COULEUR_EAU = [42, 118, 175];
const COULEUR_FOND = [18, 32, 52];
const COULEUR_NEUTRE = [90, 100, 110];
const LARGEUR_CARTE = 1200;
const HAUTEUR_CARTE = 620;

// ---------------------------------------------------------------------------
// État du client
// ---------------------------------------------------------------------------

const client = {
  jeton: localStorage.getItem("jeux_strat_jeton"),
  nom: localStorage.getItem("jeux_strat_nom"),
  ws: null,
  partieId: null,
  etat: null,        // dernier état complet reçu du serveur
  sieges: [],        // dernier message de présence (sièges + connectés)
  spectateurs: [],
  monSiege: null,
  selection: null,   // territoire sélectionné sur la carte
  fermetureVoulue: false,
};

function $(id) { return document.getElementById(id); }

function montrerEcran(nom) {
  for (const ecran of document.querySelectorAll("body > section")) {
    ecran.hidden = ecran.id !== "ecran-" + nom;
  }
}

async function api(chemin, corps) {
  const options = corps === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corps),
  };
  const reponse = await fetch(chemin, options);
  if (!reponse.ok) {
    let detail = "";
    try { detail = (await reponse.json()).detail; } catch (e) { /* sans corps */ }
    throw new Error(detail || `Erreur ${reponse.status}`);
  }
  return reponse.json();
}

function rgb(couleur) { return `rgb(${couleur[0]},${couleur[1]},${couleur[2]})`; }

function couleurJoueur(joueur) {
  return joueur >= 0
    ? COULEURS_JOUEURS[joueur % COULEURS_JOUEURS.length]
    : COULEUR_NEUTRE;
}

// ---------------------------------------------------------------------------
// Écran identité
// ---------------------------------------------------------------------------

$("form-identite").addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  $("erreur-identite").textContent = "";
  try {
    const identite = await api("/api/joueurs", { nom: $("champ-nom").value });
    client.jeton = identite.jeton;
    client.nom = identite.nom;
    localStorage.setItem("jeux_strat_jeton", identite.jeton);
    localStorage.setItem("jeux_strat_nom", identite.nom);
    entrerAuLobby();
  } catch (erreur) {
    $("erreur-identite").textContent =
      erreur.message === "nom_pris" ? "Ce nom est déjà pris." : "Nom invalide.";
  }
});

// ---------------------------------------------------------------------------
// Écran lobby
// ---------------------------------------------------------------------------

function entrerAuLobby() {
  client.partieId = null;
  location.hash = "";
  $("lobby-nom").textContent = client.nom;
  montrerEcran("lobby");
  rafraichirLobby();
}

async function rafraichirLobby() {
  $("erreur-lobby").textContent = "";
  try {
    const [parties, cartes, sauvegardes] = await Promise.all([
      api("/api/parties"), api("/api/cartes"), api("/api/sauvegardes"),
    ]);
    afficherParties(parties.parties);
    afficherCartes(cartes.cartes);
    afficherSauvegardes(sauvegardes.sauvegardes);
  } catch (erreur) {
    $("erreur-lobby").textContent = "Serveur injoignable : " + erreur.message;
  }
}

function afficherParties(parties) {
  const liste = $("liste-parties");
  liste.textContent = "";
  if (!parties.length) {
    liste.innerHTML = "<li>Aucune partie ouverte pour l'instant.</li>";
    return;
  }
  for (const partie of parties) {
    const element = document.createElement("li");
    const humains = partie.sieges.filter((s) => !s.ia && s.actif);
    const occupants = humains.filter((s) => s.nom).map((s) => s.nom);
    const texte = document.createElement("span");
    texte.textContent =
      `Partie ${partie.id} — tour ${partie.tour}, ` +
      `${humains.length} humain(s)` +
      (occupants.length ? ` (${occupants.join(", ")})` : "") +
      (partie.source ? ` — ${partie.source}` : "");
    const bouton = document.createElement("button");
    bouton.textContent = "Rejoindre";
    bouton.addEventListener("click", () => entrerEnPartie(partie.id));
    element.append(texte, bouton);
    liste.append(element);
  }
}

function afficherCartes(cartes) {
  const champ = $("champ-carte");
  champ.textContent = "";
  for (const carte of cartes) {
    const option = document.createElement("option");
    option.value = carte.fichier;
    option.textContent = `${carte.fichier.replace(/\.json$/, "")} (${carte.territoires} terr.)`;
    champ.append(option);
  }
}

function afficherSauvegardes(sauvegardes) {
  const liste = $("liste-sauvegardes");
  liste.textContent = "";
  for (const sauvegarde of sauvegardes) {
    const element = document.createElement("li");
    const texte = document.createElement("span");
    texte.textContent =
      `${sauvegarde.fichier} — tour ${sauvegarde.tour}, ` +
      `${sauvegarde.num_players} joueurs`;
    const bouton = document.createElement("button");
    bouton.textContent = "Ouvrir";
    bouton.addEventListener("click", async () => {
      try {
        const resume = await api("/api/parties", { sauvegarde: sauvegarde.fichier });
        entrerEnPartie(resume.id);
      } catch (erreur) {
        $("erreur-lobby").textContent = erreur.message;
      }
    });
    element.append(texte, bouton);
    liste.append(element);
  }
}

$("bouton-rafraichir").addEventListener("click", rafraichirLobby);

$("form-nouvelle").addEventListener("submit", async (evenement) => {
  evenement.preventDefault();
  $("erreur-lobby").textContent = "";
  try {
    const resume = await api("/api/parties", {
      carte: $("champ-carte").value,
      joueurs: Number($("champ-joueurs").value),
      ia: Number($("champ-ia").value),
      mode: $("champ-mode").value,
      tribus: $("champ-tribus").checked,
    });
    entrerEnPartie(resume.id);
  } catch (erreur) {
    $("erreur-lobby").textContent = erreur.message;
  }
});

// ---------------------------------------------------------------------------
// Écran partie — connexion WebSocket
// ---------------------------------------------------------------------------

function entrerEnPartie(partieId) {
  client.partieId = partieId;
  client.etat = null;
  client.monSiege = null;
  client.selection = null;
  location.hash = "partie=" + partieId;
  $("messages-chat").textContent = "";
  $("journal").textContent = "";
  $("bandeau-victoire").hidden = true;
  montrerEcran("partie");
  connecterAuServeur();
}

function connecterAuServeur() {
  if (client.ws) {
    client.fermetureVoulue = true;
    client.ws.close();
  }
  client.fermetureVoulue = false;
  const protocole = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocole}//${location.host}/ws/parties/${client.partieId}`);
  client.ws = ws;

  ws.addEventListener("open", () => {
    majConnexion(true);
    // Avec le jeton, le serveur nous rend notre siège réservé s'il existe.
    ws.send(JSON.stringify({ type: "rejoindre", jeton: client.jeton }));
  });

  ws.addEventListener("message", (evenement) => {
    traiterMessage(JSON.parse(evenement.data));
  });

  ws.addEventListener("close", (evenement) => {
    majConnexion(false);
    if (client.fermetureVoulue) return;
    if (evenement.code === 4000) {
      journal("Connexion remplacée : la partie est ouverte ailleurs.");
      return;
    }
    if (evenement.code === 4004) {
      journal("Partie inconnue du serveur.");
      entrerAuLobby();
      return;
    }
    // Coupure involontaire : on retente, le siège nous attend.
    journal("Connexion perdue, nouvelle tentative dans 2 s…");
    setTimeout(() => {
      if (client.partieId !== null && !client.fermetureVoulue) {
        connecterAuServeur();
      }
    }, 2000);
  });
}

function majConnexion(connecte) {
  const badge = $("info-connexion");
  badge.textContent = connecte ? "connecté" : "déconnecté";
  badge.classList.toggle("coupe", !connecte);
}

function envoyer(message) {
  if (client.ws && client.ws.readyState === WebSocket.OPEN) {
    client.ws.send(JSON.stringify(message));
  }
}

function traiterMessage(message) {
  switch (message.type) {
    case "bienvenue":
      client.monSiege = message.joueur;
      client.etat = message.etat;
      if (message.joueur !== null) {
        journal(`Assis au siège ${message.joueur}.`);
      }
      toutRafraichir();
      break;
    case "presence":
      client.sieges = message.sieges;
      client.spectateurs = message.spectateurs;
      afficherSieges();
      break;
    case "resultat":
      client.etat = message.etat;
      journalResultat(message);
      toutRafraichir();
      break;
    case "refus":
      journal("Refus du serveur : " + message.code);
      break;
    case "chat":
      afficherMessageChat(message);
      break;
    case "siege_pris":
      client.monSiege = message.joueur;
      journal(`Assis au siège ${message.joueur}.`);
      toutRafraichir();
      break;
    case "siege_quitte":
      client.monSiege = null;
      journal("Siège libéré : tu es spectateur.");
      toutRafraichir();
      break;
    case "question_soumission": {
      const reponse = confirm(
        `${message.nom} est conquis (${message.regiments_vaincus} régiments vaincus).\n` +
        "OK = soumettre (tribut), Annuler = annexer.",
      );
      envoyer({ type: "decision_soumission", reponse });
      break;
    }
    case "victoire": {
      const bandeau = $("bandeau-victoire");
      bandeau.textContent =
        `Victoire de ${nomDuJoueur(message.vainqueur)} — ${message.raison}`;
      bandeau.hidden = false;
      break;
    }
    default:
      break;
  }
}

// ---------------------------------------------------------------------------
// Panneaux (tour, sièges, chat, journal, territoire)
// ---------------------------------------------------------------------------

function nomDuJoueur(joueur) {
  const siege = client.sieges.find((s) => s.joueur === joueur);
  if (siege && siege.nom) return siege.nom;
  if (client.etat && client.etat.commercial_city_players.includes(joueur)) {
    return `Cité comm. ${joueur}`;
  }
  if (siege && siege.ia) return `IA ${joueur}`;
  return `Joueur ${joueur}`;
}

function toutRafraichir() {
  afficherEnTete();
  afficherSieges();
  afficherDetailTerritoire();
  dessinerCarte();
}

function afficherEnTete() {
  const etat = client.etat;
  if (!etat) return;
  const phases = { attack: "attaque", move: "déplacements" };
  const phase = etat.phase === "shopping"
    ? "achats"
    : (phases[etat.turn_phase] || etat.turn_phase);
  $("info-tour").textContent =
    `Tour ${etat.turn} — ${nomDuJoueur(etat.current_player)} (${phase})`;
  if (client.monSiege !== null) {
    const or = etat.player_money[String(client.monSiege)] || 0;
    const science = etat.player_science[String(client.monSiege)] || 0;
    $("info-tresor").textContent = `Or : ${or} — Science : ${science}`;
  } else {
    $("info-tresor").textContent = "Spectateur";
  }
}

function afficherSieges() {
  const liste = $("liste-sieges");
  liste.textContent = "";
  const etat = client.etat;
  for (const siege of client.sieges) {
    if (etat && etat.commercial_city_players.includes(siege.joueur)) continue;
    const element = document.createElement("li");
    if (!siege.actif) element.classList.add("hors-jeu");
    if (etat && siege.joueur === etat.current_player) element.classList.add("au-trait");

    const pion = document.createElement("span");
    pion.className = "pion";
    pion.style.background = rgb(couleurJoueur(siege.joueur));

    const texte = document.createElement("span");
    if (siege.ia) {
      texte.textContent = `IA ${siege.joueur}`;
    } else if (siege.nom) {
      texte.textContent = siege.nom + (siege.joueur === client.monSiege ? " (toi)" : "");
      if (!siege.connecte) {
        texte.classList.add("deconnecte");
        texte.textContent += " — absent";
      }
    } else {
      texte.textContent = `Siège ${siege.joueur} libre`;
    }
    element.append(pion, texte);

    if (!siege.ia && siege.actif) {
      if (siege.joueur === client.monSiege) {
        const bouton = document.createElement("button");
        bouton.textContent = "Quitter";
        bouton.className = "danger";
        bouton.addEventListener("click", () => envoyer({ type: "quitter_siege" }));
        element.append(bouton);
      } else if (!siege.nom && client.monSiege === null) {
        const bouton = document.createElement("button");
        bouton.textContent = "S'asseoir";
        bouton.addEventListener("click", () =>
          envoyer({ type: "prendre_siege", joueur: siege.joueur }));
        element.append(bouton);
      }
    }
    liste.append(element);
  }
  $("liste-spectateurs").textContent = client.spectateurs.length
    ? "Spectateurs : " + client.spectateurs.map((n) => n || "anonyme").join(", ")
    : "";
}

$("form-chat").addEventListener("submit", (evenement) => {
  evenement.preventDefault();
  const texte = $("champ-chat").value.trim();
  if (texte) envoyer({ type: "chat", texte });
  $("champ-chat").value = "";
});

function afficherMessageChat(message) {
  const zone = $("messages-chat");
  const ligne = document.createElement("div");
  const auteur = document.createElement("span");
  auteur.className = "auteur";
  auteur.textContent = message.nom + " : ";
  ligne.append(auteur, document.createTextNode(message.texte));
  zone.append(ligne);
  zone.scrollTop = zone.scrollHeight;
}

function journal(texte) {
  const zone = $("journal");
  const ligne = document.createElement("div");
  ligne.textContent = texte;
  zone.append(ligne);
  zone.scrollTop = zone.scrollHeight;
}

function journalResultat(message) {
  if (message.action) {
    journal(`${nomDuJoueur(message.joueur)} : ${message.action.type}`);
  }
  const rapports = (message.resultat && message.resultat.rapports_ia) || [];
  if (rapports.length) {
    journal(`${rapports.length} tour(s) IA joué(s).`);
  }
}

$("bouton-retour-lobby").addEventListener("click", () => {
  client.fermetureVoulue = true;
  if (client.ws) client.ws.close();
  entrerAuLobby();
});

// ---------------------------------------------------------------------------
// Détail d'un territoire sélectionné
// ---------------------------------------------------------------------------

function afficherDetailTerritoire() {
  const zone = $("detail-territoire");
  const etat = client.etat;
  if (!etat || client.selection === null) {
    zone.textContent = "Clique un territoire sur la carte.";
    return;
  }
  const territoire = etat.territories[client.selection];
  const situation = etat.territories_state[client.selection];
  const lignes = [
    `<strong>${territoire.name}</strong>`,
    `Propriétaire : ${situation.owner >= 0 ? nomDuJoueur(situation.owner) : "neutre"}`,
    `Régiments : ${situation.regiments}`,
  ];
  if (situation.reinforcement_bonus > 1) {
    lignes.push(`Bonus de renforts : +${situation.reinforcement_bonus}`);
  }
  const id = client.selection;
  const etiquettes = [];
  const capitales = Object.entries(etat.player_capital_ids)
    .filter(([, tid]) => tid === id).map(([j]) => Number(j));
  for (const joueur of capitales) etiquettes.push(`capitale de ${nomDuJoueur(joueur)}`);
  if (etat.golden_territory_ids.includes(id)) etiquettes.push("territoire doré");
  if (etat.sanctuary_territory_ids.includes(id)) etiquettes.push("sanctuaire ONU");
  if (etat.submitted_territory_ids.includes(id)) etiquettes.push("territoire soumis");
  if (etat.fortress_territory_ids.includes(id)) etiquettes.push("forteresse");
  if (etat.factory_territory_ids.includes(id)) etiquettes.push("usine");
  if (etat.airport_territory_ids.includes(id)) etiquettes.push("aéroport");
  if (etat.port_territory_ids.includes(id)) etiquettes.push("port");
  if (etat.temple_territory_ids.includes(id)) etiquettes.push("temple");
  if (etat.university_territory_ids.includes(id)) etiquettes.push("université");
  if (etat.precious_mineral_mine_ids.includes(id)) etiquettes.push("mine de minerais");
  if ((etat.cultural_center_ages[String(id)] || []).length) {
    etiquettes.push("centre culturel");
  }
  for (const [type, tid] of Object.entries(etat.wonder_territories)) {
    if (tid === id) etiquettes.push(`merveille (${type})`);
  }
  if (etiquettes.length) lignes.push("Particularités : " + etiquettes.join(", "));
  zone.innerHTML = lignes.join("<br>");
}

// ---------------------------------------------------------------------------
// La carte — rendu canvas fidèle à draw_territories/draw_bridges de x45
// ---------------------------------------------------------------------------

function centreTerritoire(etat, territoire) {
  // Miroir de get_territory_center : moyenne simple, circulaire en "custom".
  const cellules = territoire.cells;
  if (!cellules.length) return [0, 0];
  if (etat.map_mode === "custom") {
    let sinR = 0, cosR = 0, sinC = 0, cosC = 0;
    for (const [r, c] of cellules) {
      const angleR = 2 * Math.PI * (r + 0.5) / etat.rows;
      const angleC = 2 * Math.PI * (c + 0.5) / etat.cols;
      sinR += Math.sin(angleR); cosR += Math.cos(angleR);
      sinC += Math.sin(angleC); cosC += Math.cos(angleC);
    }
    let angleMoyenR = Math.atan2(sinR, cosR);
    let angleMoyenC = Math.atan2(sinC, cosC);
    if (angleMoyenR < 0) angleMoyenR += 2 * Math.PI;
    if (angleMoyenC < 0) angleMoyenC += 2 * Math.PI;
    return [
      (angleMoyenR / (2 * Math.PI)) * etat.rows - 0.5,
      (angleMoyenC / (2 * Math.PI)) * etat.cols - 0.5,
    ];
  }
  let sommeR = 0, sommeC = 0;
  for (const [r, c] of cellules) { sommeR += r; sommeC += c; }
  return [sommeR / cellules.length, sommeC / cellules.length];
}

function dessinerCarte() {
  const etat = client.etat;
  if (!etat) return;
  const contexte = $("carte").getContext("2d");
  const largeurCellule = LARGEUR_CARTE / etat.cols;
  const hauteurCellule = HAUTEUR_CARTE / etat.rows;
  const grille = etat.grid_territory;
  const situations = etat.territories_state;
  const enroule = etat.map_mode === "custom";

  // Couleur de remplissage de chaque territoire (mêmes règles que x45).
  const remplissages = situations.map((situation) => {
    const base = couleurJoueur(situation.owner);
    let couleur;
    if (situation.owner === etat.current_player) {
      couleur = base.map((c) => Math.min(255, Math.round(c * 1.12) + 10));
    } else {
      couleur = base.map((c) => Math.round(c * 0.72));
    }
    if (situation.id === client.selection) {
      couleur = couleur.map((c) => Math.min(255, c + 70));
    }
    return rgb(couleur);
  });

  contexte.fillStyle = rgb(COULEUR_EAU);
  contexte.fillRect(0, 0, LARGEUR_CARTE, HAUTEUR_CARTE);
  for (let r = 0; r < etat.rows; r += 1) {
    for (let c = 0; c < etat.cols; c += 1) {
      const tid = grille[r][c];
      if (tid < 0) continue;
      contexte.fillStyle = remplissages[tid];
      contexte.fillRect(
        Math.floor(c * largeurCellule), Math.floor(r * hauteurCellule),
        Math.ceil(largeurCellule) + 1, Math.ceil(hauteurCellule) + 1,
      );
    }
  }

  // Bordures : fines entre territoires, jaunes pour le joueur au trait,
  // violettes (soumis) ou blanches (sanctuaire) épaisses.
  function styleBordure(tid) {
    if (etat.submitted_territory_ids.includes(tid)) return ["rgb(185,90,255)", 4];
    if (etat.sanctuary_territory_ids.includes(tid)) return ["rgb(230,245,255)", 4];
    const proprietaire = situations[tid].owner;
    if (proprietaire === etat.current_player) return ["rgb(255,220,50)", 2];
    return ["rgb(20,20,20)", 1];
  }
  contexte.lineCap = "butt";
  for (let r = 0; r < etat.rows; r += 1) {
    for (let c = 0; c < etat.cols; c += 1) {
      const tid = grille[r][c];
      if (tid < 0) continue;
      const [couleur, epaisseur] = styleBordure(tid);
      const x0 = c * largeurCellule, y0 = r * hauteurCellule;
      const x1 = x0 + largeurCellule, y1 = y0 + hauteurCellule;
      const haut = enroule ? grille[(r - 1 + etat.rows) % etat.rows][c] : (r > 0 ? grille[r - 1][c] : null);
      const bas = enroule ? grille[(r + 1) % etat.rows][c] : (r < etat.rows - 1 ? grille[r + 1][c] : null);
      const gauche = enroule ? grille[r][(c - 1 + etat.cols) % etat.cols] : (c > 0 ? grille[r][c - 1] : null);
      const droite = enroule ? grille[r][(c + 1) % etat.cols] : (c < etat.cols - 1 ? grille[r][c + 1] : null);
      contexte.strokeStyle = couleur;
      contexte.lineWidth = epaisseur;
      contexte.beginPath();
      if (haut !== tid) { contexte.moveTo(x0, y0); contexte.lineTo(x1, y0); }
      if (bas !== tid) { contexte.moveTo(x0, y1); contexte.lineTo(x1, y1); }
      if (gauche !== tid) { contexte.moveTo(x0, y0); contexte.lineTo(x0, y1); }
      if (droite !== tid) { contexte.moveTo(x1, y0); contexte.lineTo(x1, y1); }
      contexte.stroke();
    }
  }

  dessinerLiens(contexte, etat, largeurCellule, hauteurCellule);
  dessinerEtiquettes(contexte, etat, largeurCellule, hauteurCellule);
}

function dessinerLiens(contexte, etat, largeurCellule, hauteurCellule) {
  // Points stockés en (ligne, colonne) de cellule, comme dans x45.
  function enPixels(point) {
    return [
      (point[1] + 0.5) * largeurCellule,
      (point[0] + 0.5) * hauteurCellule,
    ];
  }
  function tracer(depart, arrivee, couleurFond, largeurFond, couleur, largeur, pointille) {
    contexte.setLineDash(pointille ? [8, 6] : []);
    contexte.strokeStyle = couleurFond;
    contexte.lineWidth = largeurFond;
    contexte.beginPath();
    contexte.moveTo(depart[0], depart[1]);
    contexte.lineTo(arrivee[0], arrivee[1]);
    contexte.stroke();
    contexte.strokeStyle = couleur;
    contexte.lineWidth = largeur;
    contexte.beginPath();
    contexte.moveTo(depart[0], depart[1]);
    contexte.lineTo(arrivee[0], arrivee[1]);
    contexte.stroke();
    contexte.setLineDash([]);
  }
  if (etat.map_mode === "terre") {
    for (const lien of etat.terre_link_points) {
      tracer(enPixels(lien.start), enPixels(lien.end),
        rgb(COULEUR_FOND), 8, "rgb(236,240,241)", 3, false);
    }
  }
  const fragiles = new Set(
    (etat.fragile_bridge_links || []).map(([a, b]) => `${a}-${b}`),
  );
  for (const pont of etat.bridge_link_points) {
    const fragile = fragiles.has(`${pont.a}-${pont.b}`) || fragiles.has(`${pont.b}-${pont.a}`);
    const depart = enPixels(pont.start);
    const arrivee = enPixels(pont.end);
    tracer(depart, arrivee, rgb(COULEUR_FOND), 10, "rgb(224,170,72)", 5, fragile);
    contexte.fillStyle = "rgb(255,224,145)";
    for (const [x, y] of [depart, arrivee]) {
      contexte.beginPath();
      contexte.arc(x, y, 5, 0, 2 * Math.PI);
      contexte.fill();
    }
  }
}

function dessinerEtiquettes(contexte, etat, largeurCellule, hauteurCellule) {
  const capitales = new Set(Object.values(etat.player_capital_ids));
  contexte.font = "13px 'Segoe UI', sans-serif";
  contexte.textBaseline = "middle";
  for (const territoire of etat.territories) {
    if (!territoire.cells.length) continue;
    const situation = etat.territories_state[territoire.id];
    const [ligneCentre, colonneCentre] = centreTerritoire(etat, territoire);
    const cx = (colonneCentre + 0.5) * largeurCellule;
    const cy = (ligneCentre + 0.5) * hauteurCellule;
    const base = couleurJoueur(situation.owner);

    const texte = String(situation.regiments);
    const largeurTexte = contexte.measureText(texte).width;
    const largeurBoite = largeurTexte + 16;
    const hauteurBoite = 20;
    let x = Math.max(4, Math.min(LARGEUR_CARTE - largeurBoite - 4, cx - largeurBoite / 2));
    let y = Math.max(2, Math.min(HAUTEUR_CARTE - hauteurBoite - 4, cy - hauteurBoite / 2));

    contexte.fillStyle = rgb(base.map((c) => Math.max(0, Math.round(c * 0.30) + 8)));
    contexte.strokeStyle = rgb(base.map((c) => Math.min(255, Math.round(c * 0.85))));
    contexte.lineWidth = 1;
    contexte.beginPath();
    contexte.roundRect(x, y, largeurBoite, hauteurBoite, 4);
    contexte.fill();
    contexte.stroke();
    contexte.fillStyle = "rgb(235,235,235)";
    contexte.fillText(texte, x + 8, y + hauteurBoite / 2 + 1);

    // Capitale : petite étoile au-dessus de la boîte.
    if (capitales.has(territoire.id)) {
      dessinerEtoile(contexte, cx, y - 8, 7, "rgb(255,220,50)");
    }
    // Territoire doré : disque or à gauche (comme x45, en plus petit).
    if (etat.golden_territory_ids.includes(territoire.id)) {
      contexte.beginPath();
      contexte.arc(x - 11, y + hauteurBoite / 2, 8, 0, 2 * Math.PI);
      contexte.fillStyle = "rgb(255,215,0)";
      contexte.fill();
      contexte.strokeStyle = "rgb(120,90,0)";
      contexte.stroke();
      contexte.beginPath();
      contexte.arc(x - 11, y + hauteurBoite / 2, 4, 0, 2 * Math.PI);
      contexte.fillStyle = "rgb(255,250,210)";
      contexte.fill();
    }
    // Bonus de renforts : pastille "+n" à droite.
    if (situation.reinforcement_bonus > 1) {
      const bx = Math.min(LARGEUR_CARTE - 10, x + largeurBoite + 11);
      const by = y + hauteurBoite / 2;
      contexte.beginPath();
      contexte.arc(bx, by, 9, 0, 2 * Math.PI);
      contexte.fillStyle = "rgb(244,208,63)";
      contexte.fill();
      contexte.fillStyle = "rgb(40,30,0)";
      const bonus = `+${situation.reinforcement_bonus}`;
      contexte.fillText(bonus, bx - contexte.measureText(bonus).width / 2, by + 1);
    }
  }
}

function dessinerEtoile(contexte, cx, cy, rayon, couleur) {
  contexte.beginPath();
  for (let i = 0; i < 10; i += 1) {
    const angle = -Math.PI / 2 + (i * Math.PI) / 5;
    const r = i % 2 === 0 ? rayon : rayon * 0.45;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    if (i === 0) contexte.moveTo(x, y); else contexte.lineTo(x, y);
  }
  contexte.closePath();
  contexte.fillStyle = couleur;
  contexte.fill();
  contexte.strokeStyle = "rgb(60,45,0)";
  contexte.lineWidth = 1;
  contexte.stroke();
}

$("carte").addEventListener("click", (evenement) => {
  const etat = client.etat;
  if (!etat) return;
  const cadre = $("carte").getBoundingClientRect();
  const x = (evenement.clientX - cadre.left) * (LARGEUR_CARTE / cadre.width);
  const y = (evenement.clientY - cadre.top) * (HAUTEUR_CARTE / cadre.height);
  const colonne = Math.floor(x / (LARGEUR_CARTE / etat.cols));
  const ligne = Math.floor(y / (HAUTEUR_CARTE / etat.rows));
  if (ligne < 0 || ligne >= etat.rows || colonne < 0 || colonne >= etat.cols) return;
  const tid = etat.grid_territory[ligne][colonne];
  client.selection = tid >= 0 ? tid : null;
  afficherDetailTerritoire();
  dessinerCarte();
});

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------

function demarrer() {
  if (!client.jeton || !client.nom) {
    montrerEcran("identite");
    return;
  }
  const correspondance = location.hash.match(/^#partie=(.+)$/);
  if (correspondance) {
    entrerEnPartie(correspondance[1]);
  } else {
    entrerAuLobby();
  }
}

demarrer();
