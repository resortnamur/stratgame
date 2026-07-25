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

// Les religions de x45 (noms, symboles et couleurs identiques).
const RELIGIONS = [
  { nom: "Auralis", symbole: "A*", couleur: [244, 208, 63] },
  { nom: "Noctyra", symbole: "N)", couleur: [165, 105, 189] },
  { nom: "Veridia", symbole: "V^", couleur: [88, 214, 141] },
  { nom: "Pyronis", symbole: "P!", couleur: [236, 112, 99] },
  { nom: "Mareon", symbole: "M~", couleur: [84, 153, 199] },
  { nom: "Elyrion", symbole: "E+", couleur: [174, 235, 255] },
];
// Elyrion (fondée par la merveille) n'a pas de badge de lieu saint dédié.
const RELIGION_MERVEILLE = 5;

// Les trois vues de carte de x45, dans l'ordre du bouton.
const VUES_CARTE = ["fortress", "all", "religion"];
const LIBELLES_VUES = {
  fortress: "Icônes : fort.",
  all: "Icônes : tout",
  religion: "Vue : religion",
};

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
  actionDepuis: null,  // horodatage de l'action en attente de réponse
  achat: null,          // article de boutique sélectionné (entrée du catalogue)
  territoiresAchat: [],  // territoires déjà cliqués pour l'achat en cours
  vueCarte: localStorage.getItem("jeux_strat_vue") || "fortress",
  replay: null,  // {histoire, index, enPause, minuterie} pendant un replay
  bilans: null,  // dernier état des lieux par joueur (GET /bilans)
  victoire: null,  // {vainqueur, raison} une fois la partie gagnée
  fermetureVoulue: false,
};

// Cadence du replay : la vitesse « REPLAY RAPIDE » de x45 (150 ms/étape).
const DELAI_REPLAY_MS = 150;

// Le serveur garde son propre verrou par connexion : ce délai n'est qu'un
// filet si une réponse se perd, pour ne jamais laisser l'interface sourde.
const DELAI_ACTION_MS = 5000;

// ---------------------------------------------------------------------------
// Catalogue de la boutique — mêmes articles, prix et flux que x45.
// ``cibles`` décrit les clics de carte attendus ("mien"/"ennemi"/"tout") ;
// ``joueur``/``allie``/``cible``/``quantite``/``montant``/``merveille``
// ajoutent des champs au panneau. ``science`` masque l'article sous le seuil.
// ---------------------------------------------------------------------------

const MERVEILLES = {
  elyrion_sanctuary: "Sanctuaire d'Elyrion",
  thousand_voices_theatre: "Théâtre des Mille Voix",
  atlas_observatory: "Observatoire d'Atlas",
  golden_pact_palace: "Palais du Pacte d'Or",
  ivory_rampart: "Rempart d'Ivoire",
  croesus_fountain: "Fontaine de Crésus",
  aurelia_capitol: "Capitole d'Aurelia",
  daedalus_forge: "Forge de Dédale",
};

// Merveilles débloquées par la culture (100 points) plutôt que la science.
const MERVEILLES_CULTURELLES = new Set([
  "ivory_rampart", "croesus_fountain", "aurelia_capitol", "daedalus_forge",
]);

const EFFETS_MERVEILLES = {
  elyrion_sanctuary: "Fonde Elyrion, religion conquérante liée au territoire",
  thousand_voices_theatre: "Double la culture de son contrôleur",
  atlas_observatory: "Double la science effective de son contrôleur",
  golden_pact_palace: "Fait de son contrôleur l'unique allié de la Cité commerçante",
  ivory_rampart: "Protège ce territoire de toute attaque des joueurs IA",
  croesus_fountain: "Multiplie par 5 l'argent produit par ce territoire",
  aurelia_capitol: "Ouvre le statut de nation si la capitale de son propriétaire s'y trouve",
  daedalus_forge: "Ponts construits ou détruits gratuitement depuis ce territoire",
};

const CATALOGUE_ACHATS = [
  { id: "mercenaires", libelle: "Mercenaires — 50/rég.", cibles: ["mien"], quantite: true },
  { id: "vendre_territoire", libelle: "Vendre terr. +10/rég.", cibles: ["mien"], style: "special" },
  // Le bénéficiaire du don se désigne sur la carte : 2e clic sur un de ses
  // territoires (c'est son propriétaire qui reçoit, pas le territoire).
  { id: "donner_territoire", libelle: "Donner territoire", cibles: ["mien", "benef"], style: "special" },
  { id: "donner_argent", libelle: "Donner argent", joueur: true, montant: true, style: "special" },
  { id: "forteresse", libelle: "Forteresse — 100", cibles: ["mien"], cout: 100 },
  { id: "detruire_forteresse", libelle: "Détruire forteresse — 100", cibles: ["tout"], cout: 100 },
  { id: "corruption", libelle: "Corrompre — 40-200/rég.", cibles: ["ennemi"] },
  { id: "revolte", libelle: "Révolte — 200-600", cibles: ["ennemi"], cout: 200 },
  { id: "usine", libelle: "Usine — 100", cibles: ["mien"], cout: 100 },
  { id: "aeroport", libelle: "Aéroport — 100", cibles: ["mien"], cout: 100 },
  { id: "port", libelle: "Port — 100", cibles: ["mien"], cout: 100 },
  { id: "temple", libelle: "Temple — 300", cibles: ["mien"], cout: 300 },
  { id: "centre_culturel", libelle: "Centre culturel — 200", cibles: ["mien"], cout: 200 },
  { id: "universite", libelle: "Université — 200", cibles: ["mien"], cout: 200 },
  { id: "detruire_universite", libelle: "Détruire université — 200", cibles: ["tout"], cout: 200 },
  { id: "merveille", libelle: "Merveille — 300", cibles: ["mien"], merveille: true, cout: 300 },
  // Les merveilles culturelles passent par le même achat serveur ("merveille"),
  // mais l'article n'apparaît qu'à partir de 100 points de culture.
  { id: "merveille_culturelle", achat: "merveille", libelle: "Merveille culturelle — 300",
    cibles: ["mien"], merveille: true, culturelle: true, cout: 300, culture: 100 },
  { id: "capitale", libelle: "Changer capitale — 300", cibles: ["mien"], cout: 300 },
  { id: "alliance", libelle: "Alliance déf. — 20/terr.", cibles: ["ennemi"] },
  { id: "alliance_offensive", libelle: "Alliance off. — 25/terr.", allie: true, cible: true },
  { id: "association_pf", libelle: "Association / intégr. PF", cibles: ["ennemi"] },
  { id: "figer_onu", libelle: "Figer ONU — 50/rég.", cibles: ["tout"], style: "onu" },
  { id: "liberer_onu", libelle: "Libérer ONU — 50/rég.", cibles: ["tout"], style: "onu" },
  { id: "pont", libelle: "Créer pont — 300", cibles: ["tout", "tout"], cout: 300, science: 150 },
  { id: "detruire_pont", libelle: "Détruire pont — 150", cibles: ["tout", "tout"], cout: 150, science: 150 },
];

// Consignes de clic sur la carte par type de cible.
const CONSIGNES_CIBLE = {
  mien: "clique un de tes territoires",
  ennemi: "clique un territoire adverse",
  tout: "clique un territoire",
  benef: "clique un territoire du joueur bénéficiaire",
};

// Libellés français des codes de refus du serveur et du moteur.
const LIBELLES_REFUS = {
  pas_votre_tour: "Ce n'est pas ton tour.",
  siege_ia: "Ce siège est joué par l'IA.",
  partie_terminee: "La partie est terminée.",
  spectateur: "Prends un siège pour jouer.",
  action_en_cours: "Action déjà en cours…",
  phase_invalide: "Pas pendant cette phase.",
  territoire_invalide: "Territoire invalide.",
  attaque_invalide: "Attaque impossible (voisinage, alliance ou garnison).",
  action_inconnue: "Action inconnue.",
  limite: "Limite de déplacements atteinte.",
  proprietaire: "Les deux territoires doivent être à toi.",
  meme_territoire: "Choisis un territoire différent.",
  garnison: "Il faut laisser au moins 1 régiment.",
  continuite: "Pas de chemin par tes territoires.",
  erreur_serveur: "Erreur inattendue du serveur (voir ses logs) — l'action est annulée.",
  identite_requise: "Identité requise : passe par l'écran d'accueil pour choisir ton nom.",
  siege_indisponible: "Ce siège n'est pas disponible.",
  deja_un_siege: "Tu occupes déjà un siège (quitte-le d'abord).",
  aucun_siege: "Tu n'occupes aucun siège.",
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
  // Pas de création tant que le catalogue n'est pas là (évite d'envoyer
  // une carte vide si on soumet très vite après l'ouverture du lobby).
  $("bouton-creer").disabled = cartes.length === 0;
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

// Import d'une carte : lecture locale du .json, envoi au serveur (qui la
// valide en la chargeant dans le moteur), puis sélection dans la liste.
const MESSAGES_IMPORT = {
  carte_invalide: "Ce fichier n'est pas une carte lisible par le jeu.",
  carte_trop_grosse: "Carte trop volumineuse.",
  nom_fichier_invalide: "Nom de fichier invalide (un nom simple en .json).",
};

$("bouton-importer-carte").addEventListener("click", () => {
  $("champ-import-carte").click();
});

$("champ-import-carte").addEventListener("change", async () => {
  const fichier = $("champ-import-carte").files[0];
  $("champ-import-carte").value = "";
  if (!fichier) return;
  $("erreur-lobby").textContent = "";
  let carte;
  try {
    carte = JSON.parse(await fichier.text());
  } catch (erreur) {
    $("erreur-lobby").textContent = "Ce fichier n'est pas un JSON lisible.";
    return;
  }
  const nom = fichier.name.endsWith(".json") ? fichier.name : fichier.name + ".json";
  await importerCarte(nom, carte, false);
});

async function importerCarte(nom, carte, remplacer) {
  try {
    const fiche = await api("/api/cartes", { nom, carte, remplacer });
    await rafraichirLobby();
    $("champ-carte").value = fiche.fichier;
  } catch (erreur) {
    if (erreur.message === "carte_existante") {
      if (confirm(`La carte « ${nom} » existe déjà. La remplacer ?`)) {
        return importerCarte(nom, carte, true);
      }
      return;
    }
    $("erreur-lobby").textContent = MESSAGES_IMPORT[erreur.message] || erreur.message;
  }
}

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
  quitterReplay();
  client.partieId = partieId;
  client.etat = null;
  client.monSiege = null;
  client.selection = null;
  client.victoire = null;
  location.hash = "partie=" + partieId;
  $("messages-chat").textContent = "";
  $("journal").textContent = "";
  $("bandeau-victoire").hidden = true;
  montrerEcran("partie");
  connecterAuServeur();
}

// La version du client en cours d'exécution : le ?v= de son propre script.
const VERSION_CLIENT = (document.querySelector("script[src*='app.js']") || { src: "" })
  .src.match(/app\.js\?v=\d+/);

async function clientPerime() {
  // Le serveur sert-il une version plus récente du client ? La page
  // d'accueil est en no-cache : on y lit le ?v= attendu. Sans cela, un
  // onglet resté ouvert pendant une mise à jour (le serveur redémarre,
  // la connexion coupe) continuerait de jouer avec l'ancien client —
  // anciens boutons, anciennes règles d'affichage.
  try {
    const html = await (await fetch("/", { cache: "no-cache" })).text();
    const attendu = html.match(/app\.js\?v=\d+/);
    return Boolean(VERSION_CLIENT && attendu && VERSION_CLIENT[0] !== attendu[0]);
  } catch (erreur) {
    return false;  // serveur injoignable : la reconnexion réessaiera
  }
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
    client.actionDepuis = null;
    majConnexion("connecté");
    // Avec le jeton, le serveur nous rend notre siège réservé s'il existe.
    ws.send(JSON.stringify({ type: "rejoindre", jeton: client.jeton }));
  });

  ws.addEventListener("message", (evenement) => {
    if (client.ws !== ws) return;  // socket remplacé : messages ignorés
    traiterMessage(JSON.parse(evenement.data));
  });

  ws.addEventListener("close", (evenement) => {
    // Un socket remplacé par une nouvelle connexion n'a plus voix au
    // chapitre : sans ce garde-fou, son "close" (asynchrone) était pris
    // pour une coupure involontaire et relançait une reconnexion en
    // boucle par-dessus la connexion vivante.
    if (client.ws !== ws) return;
    if (client.fermetureVoulue) return;
    if (evenement.code === 4000) {
      // La partie a été ouverte ailleurs (autre onglet, autre appareil).
      majConnexion("partie ouverte ailleurs — clique ici pour reprendre");
      journal("Connexion remplacée : la partie est ouverte ailleurs. " +
              "Clique le badge en haut à droite pour reprendre ici.");
      return;
    }
    if (evenement.code === 4004) {
      // Partie disparue (le serveur a redémarré) : retour au lobby, où
      // la partie se reprend depuis sa sauvegarde. Un redémarrage est
      // souvent une mise à jour : si le client a vieilli, on recharge.
      entrerAuLobby();
      $("erreur-lobby").textContent =
        "Cette partie n'existe plus (le serveur a redémarré). " +
        "Reprends-la depuis sa sauvegarde.";
      clientPerime().then((perime) => { if (perime) location.reload(); });
      return;
    }
    // Coupure involontaire : on retente, le siège nous attend.
    majConnexion("déconnecté");
    journal("Connexion perdue, nouvelle tentative dans 2 s…");
    setTimeout(async () => {
      if (client.ws !== ws) return;  // une autre connexion a déjà repris
      if (client.partieId === null || client.fermetureVoulue) return;
      if (await clientPerime()) {
        // Le jeu a été mis à jour pendant qu'on jouait : on recharge la
        // page — l'identité (localStorage), la partie (hash d'URL) et le
        // siège (jeton) sont retrouvés automatiquement.
        journal("Mise à jour du jeu : rechargement de la page…");
        location.reload();
        return;
      }
      connecterAuServeur();
    }, 2000);
  });
}

function majConnexion(texte) {
  const badge = $("info-connexion");
  badge.textContent = texte;
  badge.classList.toggle("coupe", texte !== "connecté");
}

// Reprendre la main quand la connexion a été remplacée par un autre onglet.
$("info-connexion").addEventListener("click", () => {
  if (client.partieId !== null
      && (!client.ws || client.ws.readyState !== WebSocket.OPEN)) {
    connecterAuServeur();
  }
});

function envoyer(message) {
  if (client.ws && client.ws.readyState === WebSocket.OPEN) {
    client.ws.send(JSON.stringify(message));
  }
}

function enModeAuto(joueur) {
  // Siège humain confié à l'IA (bouton « Laisser l'IA jouer »).
  return client.etat !== null && joueur !== null
    && (client.etat.auto_controlled_players || []).includes(joueur);
}

function aMonTour() {
  return client.etat !== null
    && client.monSiege !== null
    && client.monSiege === client.etat.current_player
    && !enModeAuto(client.monSiege)
    && (client.etat.phase === "playing" || client.etat.phase === "shopping");
}

function actionEnAttente() {
  return client.actionDepuis !== null
    && Date.now() - client.actionDepuis < DELAI_ACTION_MS;
}

function envoyerAction(action) {
  if (!aMonTour() || actionEnAttente()) return;
  if (!client.ws || client.ws.readyState !== WebSocket.OPEN) {
    journal("Déconnecté du serveur : action impossible.");
    return;
  }
  client.actionDepuis = Date.now();
  envoyer({ type: "action", action });
}

function traiterMessage(message) {
  switch (message.type) {
    case "bienvenue":
      client.monSiege = message.joueur;
      client.etat = message.etat;
      client.actionDepuis = null;
      // La présence détaillée suit immédiatement ; en attendant on connaît
      // au moins les réservations.
      client.sieges = (message.sieges || []).map((s) => ({ connecte: false, ...s }));
      if (message.joueur !== null) {
        journal(`Assis au siège ${message.joueur}.`);
      }
      toutRafraichir();
      chargerBilans();
      break;
    case "presence":
      client.sieges = message.sieges;
      client.spectateurs = message.spectateurs;
      afficherSieges();
      afficherBarreActions();
      afficherEnTete();
      break;
    case "pas_ia": {
      // Une passe d'attaque IA en direct : on met à jour les territoires
      // touchés et on raconte les dés, sans attendre l'état complet.
      const etat = client.etat;
      if (!etat) break;
      for (const territoire of message.pas.territoires) {
        etat.territories_state[territoire.id] = territoire;
      }
      const resultat = message.pas.result;
      const nomCible = etat.territories[message.pas.dst_id].name;
      journal(`${nomDuJoueur(message.joueur)} attaque ${nomCible} : ` +
              `${resultat.att_text} / ${resultat.def_text}` +
              (resultat.conquered ? " — conquis !" : ""));
      for (const texte of [resultat.special_conquest_message,
                           resultat.alliance_break_message,
                           resultat.elimination_message]) {
        if (texte) journal(texte);
      }
      dessinerCarte();
      break;
    }
    case "resultat":
      // Mon tour vient de passer à quelqu'un d'autre : la surbrillance du
      // dernier territoire sélectionné n'a plus de raison d'être.
      if (client.etat && client.etat.current_player === client.monSiege
          && message.etat.current_player !== client.monSiege) {
        client.selection = null;
      }
      client.etat = message.etat;
      if (message.joueur === client.monSiege) client.actionDepuis = null;
      journalResultat(message);
      toutRafraichir();
      planifierBilans();
      // Comme x45 : après le dernier déplacement autorisé, le tour se
      // termine tout seul (le joueur ne peut de toute façon plus rien faire).
      if (message.joueur === client.monSiege
          && message.action && message.action.type === "deplacer"
          && aMonTour() && client.etat.phase === "playing"
          && client.etat.turn_phase === "move"
          && client.etat.turn_move_count >= limiteDeplacements(client.etat)) {
        journal(`${limiteDeplacements(client.etat)} déplacements effectués : ` +
                "fin de tour automatique.");
        envoyerAction({ type: "fin_de_tour" });
      }
      break;
    case "refus":
      client.actionDepuis = null;
      if (message.code === "jeton_inconnu") {
        // Le serveur ne connaît plus notre identité (registre remis à
        // zéro…) : on repart de l'écran d'inscription.
        localStorage.removeItem("jeux_strat_jeton");
        localStorage.removeItem("jeux_strat_nom");
        client.jeton = client.nom = null;
        client.fermetureVoulue = true;
        if (client.ws) client.ws.close();
        montrerEcran("identite");
        break;
      }
      // Le refus d'un achat porte le texte de la boutique : on le préfère
      // au libellé générique du code. Flash sur la carte + trace au journal.
      const detail = message.resultat && message.resultat.outcome
        && message.resultat.outcome.message;
      const texteRefus = detail || LIBELLES_REFUS[message.code] || `Refus : ${message.code}`;
      flash(texteRefus);
      journal(texteRefus);
      break;
    case "chat":
      afficherMessageChat(message);
      break;
    case "siege_pris":
      client.monSiege = message.joueur;
      journal(`Assis au siège ${message.joueur}.`);
      toutRafraichir();
      chargerBilans();
      break;
    case "siege_quitte":
      client.monSiege = null;
      journal("Siège libéré : tu es spectateur.");
      toutRafraichir();
      break;
    case "mode_auto": {
      // Un siège humain vient d'être confié à l'IA (ou repris). L'état
      // complet n'est pas rediffusé pour ça : on met la liste à jour ici,
      // la présence (drapeaux « ia » des sièges) suit dans la foulée.
      const etat = client.etat;
      if (etat) {
        const autos = new Set(etat.auto_controlled_players || []);
        if (message.actif) autos.add(message.joueur);
        else autos.delete(message.joueur);
        etat.auto_controlled_players = [...autos];
        // Miroir du serveur : reprendre la main pendant son tour ramène en
        // phase d'attaque ; confier sa boutique à l'IA rend la main au jeu.
        if (!message.actif && message.joueur === etat.current_player
            && etat.phase === "playing") {
          etat.turn_phase = "attack";
        }
        if (message.actif && message.joueur === etat.current_player
            && etat.phase === "shopping") {
          etat.phase = "playing";
        }
      }
      // Mon siège passe à l'IA : ma sélection ne doit plus rester en
      // surbrillance pendant qu'elle joue.
      if (message.actif && message.joueur === client.monSiege) {
        client.selection = null;
      }
      const nom = message.nom || nomDuJoueur(message.joueur);
      journal(message.actif
        ? `${nom} laisse l'IA jouer à sa place.`
        : `${nom} reprend la main.`);
      toutRafraichir();
      break;
    }
    case "question_soumission": {
      // OK = annexer (le choix par défaut) ; Annuler = soumettre (tribut).
      const annexer = confirm(
        `${message.nom} est conquis (${message.regiments_vaincus} régiments vaincus).\n` +
        "OK = annexer, Annuler = soumettre (tribut).",
      );
      envoyer({ type: "decision_soumission", reponse: !annexer });
      break;
    }
    case "victoire":
      client.victoire = { vainqueur: message.vainqueur, raison: message.raison };
      afficherVictoire();
      break;
    default:
      break;
  }
}

// ---------------------------------------------------------------------------
// Panneaux (tour, sièges, chat, journal, territoire)
// ---------------------------------------------------------------------------

// Libellés français des profils IA (personnalité fixe + comportement tiré
// au sort à chaque tour pour les « variables »).
const LIBELLES_PROFILS_IA = {
  standard: "standard",
  aggressive: "agressive",
  very_aggressive: "très agressive",
  defensive: "défensive",
  variable: "variable",
};

function personnaliteIA(etat, joueur) {
  if (!etat) return "";
  const profil = (etat.ai_personalities || {})[String(joueur)];
  if (!profil) return "";
  let libelle = LIBELLES_PROFILS_IA[profil] || profil;
  if (profil === "variable") {
    const humeur = (etat.ai_current_behavior || {})[String(joueur)];
    if (humeur) {
      libelle += `, ce tour : ${LIBELLES_PROFILS_IA[humeur] || humeur}`;
    }
  }
  return ` (${libelle})`;
}

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
  afficherBarreActions();
  afficherBoutique();
  afficherEvenements();
  afficherEmpire();
  afficherSituation();
  afficherDetailTerritoire();
  dessinerCarte();
}

// ---------------------------------------------------------------------------
// Bilans (état des lieux) — chargés du serveur, throttlés pendant les IA
// ---------------------------------------------------------------------------

let minuterieBilans = null;

async function chargerBilans() {
  if (client.partieId === null) return;
  try {
    client.bilans = await api(`/api/parties/${client.partieId}/bilans`);
    afficherEmpire();
    afficherSituation();
  } catch (erreur) {
    // Silencieux : les panneaux garderont le dernier bilan connu.
  }
}

function planifierBilans() {
  if (minuterieBilans) return;
  minuterieBilans = setTimeout(() => {
    minuterieBilans = null;
    chargerBilans();
  }, 1200);
}

function afficherEmpire() {
  const zone = $("detail-empire");
  if (client.monSiege === null) {
    zone.textContent = "Prends un siège pour voir ton bilan.";
    return;
  }
  const donnees = client.bilans;
  const bilan = donnees && donnees.bilans[String(client.monSiege)];
  if (!bilan) {
    zone.textContent = "Bilan en cours de chargement…";
    return;
  }
  const amenagements = bilan.amenagements;
  const lignes = [
    `<strong>${bilan.territoires}</strong> territoires ` +
      `(victoire aux ¾ : ${donnees.seuil_trois_quarts}) — ` +
      `<strong>${bilan.regiments}</strong> régiments`,
    `Territoires dorés : ${bilan.dores}/${donnees.nb_dores}` +
      (bilan.mines ? ` — mines de minerais : ${bilan.mines}` : ""),
    `Aménagements (${amenagements.total}) : ` +
      `${amenagements.forteresses} forteresse(s), ${amenagements.usines} usine(s), ` +
      `${amenagements.aeroports} aéroport(s), ${amenagements.ports} port(s), ` +
      `${amenagements.temples} temple(s), ${amenagements.centres_culturels} centre(s) culturel(s), ` +
      `${amenagements.universites} université(s)`,
  ];
  if (Object.keys(bilan.bonus).length) {
    lignes.push("Bonus de renforts : " + Object.entries(bilan.bonus)
      .map(([valeur, nombre]) => `${nombre} territoire(s) ${valeur}`).join(", "));
  }
  lignes.push(bilan.nation.est_nation
    ? "<strong>Statut de nation : acquis ✓</strong>"
    : "<strong>Vers le statut de nation :</strong>");
  const conditions = bilan.nation.conditions.map((condition) =>
    `<span class="${condition.ok ? "ok" : "manque"}">${condition.ok ? "✓" : "✗"}</span> ` +
    condition.libelle + (condition.detail ? ` — ${condition.detail}` : ""));
  zone.innerHTML = lignes.join("<br>")
    + "<div class='conditions'>" + conditions.join("<br>") + "</div>";
}

function afficherSituation() {
  const zone = $("tableau-situation");
  const etat = client.etat;
  const donnees = client.bilans;
  if (!etat || !donnees) {
    zone.textContent = "Chargement…";
    return;
  }
  const colonnes = ["Joueur", "Terr.", "Rég.", "Écus", "+Rev", "Sci", "Cult", "Amén.", "Nation"];
  const lignes = [];
  for (const [cle, bilan] of Object.entries(donnees.bilans)) {
    const joueur = Number(cle);
    const apercu = (etat.apercus || {})[cle] || {};
    lignes.push({
      joueur,
      cellules: [
        `<span class="pion" style="background:${rgb(couleurJoueur(joueur))}"></span>${nomDuJoueur(joueur)}`,
        bilan.territoires,
        bilan.regiments,
        etat.player_money[cle] || 0,
        `+${apercu.revenu ?? "?"}`,
        etat.player_science[cle] || 0,
        apercu.culture ?? "?",
        bilan.amenagements.total,
        bilan.nation.est_nation ? "✓" : "",
      ],
    });
  }
  lignes.sort((a, b) => b.cellules[1] - a.cellules[1]);  // par territoires
  zone.innerHTML =
    "<table><tr>" + colonnes.map((c) => `<th>${c}</th>`).join("") + "</tr>" +
    lignes.map((ligne) =>
      "<tr>" + ligne.cellules.map((c) => `<td>${c}</td>`).join("") + "</tr>",
    ).join("") + "</table>";
}

function afficherEvenements() {
  const etat = client.etat;
  const zone = $("liste-evenements");
  const evenements = (etat && etat.recent_major_events) || [];
  if (!evenements.length) {
    zone.textContent = "Rien à signaler pour l'instant.";
    return;
  }
  zone.textContent = "";
  // Les plus récents en premier.
  for (const evenement of [...evenements].reverse()) {
    const ligne = document.createElement("div");
    ligne.textContent = evenement;
    zone.append(ligne);
  }
}

function limiteDeplacements(etat) {
  // Miroir de get_end_turn_move_limit : 5, ou 10 dès 10 territoires.
  const possessions = etat.territories_state
    .filter((s) => s.owner === etat.current_player).length;
  return possessions >= 10 ? 10 : 5;
}

function joueurAutomatique(etat, joueur) {
  // IA de base, joueur repris par l'IA ou cité commerçante.
  return (etat.base_ai_players || []).includes(joueur)
    || (etat.auto_controlled_players || []).includes(joueur)
    || (etat.commercial_city_players || []).includes(joueur);
}

function afficherBarreActions() {
  const etat = client.etat;
  const barre = $("barre-actions");
  if (!etat || etat.phase === "victory" || client.replay) {
    barre.hidden = true;
    return;
  }
  barre.hidden = false;
  $("bouton-vue").textContent = LIBELLES_VUES[client.vueCarte];
  const enAttaque = etat.phase === "playing" && etat.turn_phase === "attack";
  const enAchats = etat.phase === "shopping";
  const enDeplacement = etat.phase === "playing" && etat.turn_phase === "move";
  const monTour = aMonTour();
  const monAuto = client.monSiege !== null && enModeAuto(client.monSiege);
  $("bouton-fin-attaque").hidden = !(monTour && enAttaque);
  $("bouton-fin-achats").hidden = !(monTour && enAchats);
  $("bouton-fin-tour").hidden = !(monTour && enDeplacement);
  $("bouton-jouer-siege").hidden = true;
  // La bascule humain ↔ IA de son propre siège, toujours à portée de main.
  $("bouton-mode-ia").hidden = client.monSiege === null;
  $("bouton-mode-ia").textContent = monAuto ? "Reprendre la main" : "Laisser l'IA jouer";

  if (monAuto) {
    $("indication-phase").textContent = etat.current_player === client.monSiege
      ? "L'IA joue ton tour — « Reprendre la main » pour continuer toi-même."
      : "Ton siège est en mode IA — reprends la main quand tu veux.";
    return;
  }

  if (monTour) {
    if (enAttaque) {
      $("indication-phase").textContent =
        "À toi ! Clique un de tes territoires puis une cible : " +
        "clic gauche = une passe, clic droit = assaut total.";
    } else if (enAchats) {
      $("indication-phase").textContent =
        "Phase d'achats — choisis un article dans la boutique (à droite), " +
        "Échap pour terminer.";
    } else if (enDeplacement) {
      $("indication-phase").textContent =
        `Déplacements : ${etat.turn_move_count}/${limiteDeplacements(etat)} — ` +
        "clic gauche = source, clic droit = destination (1 régiment par clic).";
    }
    return;
  }

  // Pas mon tour : dire clairement ce qu'on attend, et proposer de jouer
  // le siège au trait s'il est humain et sans personne (mode « chacun son
  // tour sur le même écran », comme x45).
  const courant = etat.current_player;
  const siege = client.sieges.find((s) => s.joueur === courant);
  if (joueurAutomatique(etat, courant)) {
    $("indication-phase").textContent = `Tour de ${nomDuJoueur(courant)} (IA)…`;
  } else if (siege && siege.nom && siege.connecte) {
    $("indication-phase").textContent = `Tour de ${siege.nom}…`;
  } else if (siege && siege.nom) {
    $("indication-phase").textContent =
      `En attente de ${siege.nom} (déconnecté) — son siège lui reste réservé.`;
  } else {
    $("indication-phase").textContent =
      `En attente du siège ${courant} (libre).`;
    $("bouton-jouer-siege").hidden = false;
  }
}

// ---------------------------------------------------------------------------
// Boutique (phase d'achats)
// ---------------------------------------------------------------------------

function enPhaseAchats() {
  return aMonTour() && client.etat.phase === "shopping";
}

function afficherBoutique() {
  const panneau = $("panneau-boutique");
  if (!enPhaseAchats()) {
    panneau.hidden = true;
    client.achat = null;
    client.territoiresAchat = [];
    return;
  }
  panneau.hidden = false;
  const etat = client.etat;
  const argent = etat.player_money[String(client.monSiege)] || 0;
  const science = etat.player_science[String(client.monSiege)] || 0;
  const culture = ((etat.apercus || {})[String(client.monSiege)] || {}).culture || 0;
  // La Forge de Dédale débloque les ponts (gratuits depuis son territoire)
  // même sans les 150 points de science.
  const forgeTid = (etat.wonder_territories || {}).daedalus_forge;
  const controleForge = forgeTid !== undefined
    && etat.territories_state[forgeTid]
    && etat.territories_state[forgeTid].owner === client.monSiege;

  const zone = $("boutons-boutique");
  zone.textContent = "";
  for (const article of CATALOGUE_ACHATS) {
    const pontDeLaForge = controleForge && (article.id === "pont" || article.id === "detruire_pont");
    if (article.science && science < article.science && !pontDeLaForge) continue;
    if (article.culture && culture < article.culture) continue;
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.textContent = article.libelle;
    if (article.style) bouton.classList.add(article.style);
    if (client.achat && client.achat.id === article.id) bouton.classList.add("choisi");
    if (article.cout && argent < article.cout && !pontDeLaForge) bouton.disabled = true;
    bouton.addEventListener("click", () => {
      client.achat = (client.achat && client.achat.id === article.id) ? null : article;
      client.territoiresAchat = [];
      afficherBoutique();
    });
    zone.append(bouton);
  }
  afficherParamsBoutique();
  afficherConsigneBoutique();
}

function afficherParamsBoutique() {
  const zone = $("params-boutique");
  zone.textContent = "";
  const article = client.achat;
  if (!article) return;

  function ajouterChampNombre(id, libelle, valeur, minimum) {
    const label = document.createElement("label");
    label.textContent = libelle;
    const champ = document.createElement("input");
    champ.type = "number";
    champ.id = id;
    champ.min = minimum;
    champ.value = valeur;
    label.append(champ);
    zone.append(label);
  }
  function ajouterChoixJoueur(id, libelle) {
    const label = document.createElement("label");
    label.textContent = libelle;
    const champ = document.createElement("select");
    champ.id = id;
    for (const siege of client.sieges) {
      if (siege.joueur === client.monSiege || !siege.actif) continue;
      const option = document.createElement("option");
      option.value = siege.joueur;
      option.textContent = nomDuJoueur(siege.joueur);
      champ.append(option);
    }
    label.append(champ);
    zone.append(label);
  }

  if (article.quantite) ajouterChampNombre("achat-quantite", "Quantité", 1, 1);
  if (article.montant) ajouterChampNombre("achat-montant", "Montant", 100, 1);
  if (article.joueur) ajouterChoixJoueur("achat-joueur", "Bénéficiaire");
  if (article.allie) ajouterChoixJoueur("achat-allie", "Allié (IA)");
  if (article.cible) ajouterChoixJoueur("achat-cible", "Contre");
  if (article.merveille) {
    const label = document.createElement("label");
    label.textContent = article.culturelle ? "Merveille culturelle" : "Merveille";
    const champ = document.createElement("select");
    champ.id = "achat-merveille";
    for (const [type, nom] of Object.entries(MERVEILLES)) {
      if (MERVEILLES_CULTURELLES.has(type) !== Boolean(article.culturelle)) continue;
      if (Object.keys(client.etat.wonder_territories).includes(type)) continue;
      const option = document.createElement("option");
      option.value = type;
      option.textContent = nom;
      option.title = EFFETS_MERVEILLES[type] || "";
      champ.append(option);
    }
    label.append(champ);
    zone.append(label);
  }
  if (!article.cibles) {
    // Aucun clic de carte requis : un bouton d'envoi direct.
    const valider = document.createElement("button");
    valider.type = "button";
    valider.textContent = "Valider l'achat";
    valider.addEventListener("click", envoyerAchat);
    zone.append(valider);
  }
}

function afficherConsigneBoutique() {
  const zone = $("consigne-boutique");
  const article = client.achat;
  if (!article) {
    zone.textContent = "Choisis un article.";
    return;
  }
  if (article.cibles) {
    const etape = client.territoiresAchat.length;
    const consigne = CONSIGNES_CIBLE[article.cibles[etape]] || "clique un territoire";
    const suffixe = article.cibles.length > 1
      ? ` (${etape + 1}/${article.cibles.length})` : "";
    zone.textContent = `${article.libelle} : ${consigne}${suffixe}.`;
  } else {
    zone.textContent = `${article.libelle} : complète puis valide.`;
  }
}

function envoyerAchat() {
  const article = client.achat;
  if (!article) return;
  const action = { type: "acheter", achat: article.achat || article.id };
  if (article.cibles) {
    action.territoire = client.territoiresAchat[0];
    if (article.cibles.length > 1) {
      const second = client.territoiresAchat[1];
      if (article.cibles[1] === "benef") {
        // Le 2e clic désigne le bénéficiaire : le propriétaire du territoire.
        action.joueur = client.etat.territories_state[second].owner;
      } else {
        action.territoire_b = second;
      }
    }
  }
  if (article.quantite) action.quantite = Number($("achat-quantite").value);
  if (article.montant) action.montant = Number($("achat-montant").value);
  if (article.joueur) action.joueur = Number($("achat-joueur").value);
  if (article.allie) action.allie = Number($("achat-allie").value);
  if (article.cible) action.cible = Number($("achat-cible").value);
  if (article.merveille) action.merveille = $("achat-merveille").value;
  client.territoiresAchat = [];  // l'article reste choisi pour enchaîner
  envoyerAction(action);
  afficherConsigneBoutique();
}

function clicCarteBoutique(tid) {
  const article = client.achat;
  if (!article || !article.cibles || tid === null) return false;
  const attendu = article.cibles[client.territoiresAchat.length];
  const proprietaire = client.etat.territories_state[tid].owner;
  const cibleRefusee = () => {
    flash(`${article.libelle} : ${CONSIGNES_CIBLE[attendu] || "cible invalide"}.`);
    return false;
  };
  if (attendu === "mien" && proprietaire !== client.monSiege) return cibleRefusee();
  if (attendu === "ennemi" && proprietaire === client.monSiege) return cibleRefusee();
  // "benef" désigne un joueur par l'un de ses territoires : ni soi-même,
  // ni un territoire neutre (personne à qui donner).
  if (attendu === "benef" && (proprietaire < 0 || proprietaire === client.monSiege)) {
    return cibleRefusee();
  }
  client.territoiresAchat.push(tid);
  if (client.territoiresAchat.length >= article.cibles.length) {
    envoyerAchat();
  } else {
    afficherConsigneBoutique();
  }
  return true;
}

$("bouton-jouer-siege").addEventListener("click", () => {
  const etat = client.etat;
  if (!etat) return;
  // Basculer de siège : on libère le sien puis on prend celui au trait.
  if (client.monSiege !== null) envoyer({ type: "quitter_siege" });
  envoyer({ type: "prendre_siege", joueur: etat.current_player });
});

// ---------------------------------------------------------------------------
// Mode replay — relit les instantanés enregistrés par le moteur (x45)
// ---------------------------------------------------------------------------

function etatDepuisInstantane(instantane) {
  // Reconstruit un pseudo-état affichable par dessinerCarte : la géométrie
  // (cellules, grille, liens terre) vient de l'état courant — elle ne
  // change jamais — tout le reste vient de l'instantané.
  const etat = client.etat;
  return {
    ...etat,
    current_player: instantane.player,
    turn: instantane.turn,
    territories_state: instantane.owners.map((owner, tid) => ({
      id: tid,
      owner,
      regiments: instantane.regiments[tid],
      reinforcement_bonus: instantane.reinforcement_bonuses[tid],
    })),
    fortress_territory_ids: instantane.fortresses,
    factory_territory_ids: instantane.factories,
    airport_territory_ids: instantane.airports,
    port_territory_ids: instantane.ports,
    temple_territory_ids: instantane.temples,
    university_territory_ids: instantane.universities,
    cultural_center_ages: Object.fromEntries(
      instantane.cultural_centers.map((tid) => [String(tid), [1]])),
    precious_mineral_mine_ids: instantane.precious_mines,
    sanctuary_territory_ids: instantane.sanctuaries,
    submitted_territory_ids: instantane.submitted,
    wonder_territories: instantane.wonders,
    player_capital_ids: instantane.capitals,
    commercial_city_players: instantane.commercial_players,
    nation_players: instantane.nation_players,
    religious_influence: instantane.religious_influence,
    religion_holy_sites: instantane.religion_holy_sites,
    religion_founders: Object.fromEntries(
      Object.keys(instantane.religion_foundation_turns || {})
        .map((religion) => [religion, Number(religion)])),
    player_money: instantane.money,
    player_science: instantane.science,
    bridge_link_points: instantane.bridges,
    fragile_bridge_links: instantane.bridges
      .filter((pont) => pont.fragile).map((pont) => [pont.a, pont.b]),
    last_stand_bonus_territory: {},  // absent des instantanés
  };
}

async function demarrerReplay() {
  if (client.replay || client.partieId === null) return;
  let histoire;
  try {
    histoire = (await api(`/api/parties/${client.partieId}/replay`)).replay_history;
  } catch (erreur) {
    journal("Replay impossible : " + erreur.message);
    return;
  }
  if (!histoire || histoire.length < 2) {
    journal("Replay indisponible : pas assez d'instantanés enregistrés.");
    return;
  }
  client.replay = { histoire, index: 0, enPause: false };
  $("barre-replay").hidden = false;
  $("barre-actions").hidden = true;
  $("bandeau-victoire").hidden = true;  // rien ne doit gâcher le replay
  $("replay-position").max = histoire.length - 1;
  client.replay.minuterie = setInterval(() => {
    const replay = client.replay;
    if (!replay || replay.enPause) return;
    if (replay.index >= replay.histoire.length - 1) {
      replay.enPause = true;
      majReplay();
      return;
    }
    replay.index += 1;
    majReplay();
  }, DELAI_REPLAY_MS);
  majReplay();
}

function majReplay() {
  const replay = client.replay;
  if (!replay) return;
  const instantane = replay.histoire[replay.index];
  $("replay-position").value = replay.index;
  $("replay-pause").textContent = replay.enPause ? "▶ Lecture" : "⏸ Pause";
  $("replay-info").textContent =
    `Étape ${replay.index + 1}/${replay.histoire.length} — tour ${instantane.turn}` +
    (instantane.label ? ` — ${instantane.label}` : "");
  dessinerCarte();
}

function quitterReplay() {
  if (!client.replay) return;
  clearInterval(client.replay.minuterie);
  client.replay = null;
  $("barre-replay").hidden = true;
  afficherBarreActions();
  afficherVictoire();  // l'écran de victoire revient une fois le replay fini
  dessinerCarte();
}

$("bouton-replay").addEventListener("click", demarrerReplay);

// ---------------------------------------------------------------------------
// Sauvegarde manuelle : un nom choisi par le joueur, conservée durablement
// (contrairement aux sauvegardes automatiques auto_*, qui tournent).
// ---------------------------------------------------------------------------

$("bouton-sauvegarder").addEventListener("click", async () => {
  if (client.partieId === null) return;
  const source = client.etat && client.etat.source;
  const suggestion = source && !source.startsWith("auto_")
    ? source.replace(/\.json$/, "")
    : "ma_partie";
  let nom = prompt("Nom de la sauvegarde :", suggestion);
  if (nom === null) return;
  nom = nom.trim().replace(/\.json$/i, "");
  if (!nom) return;
  if (nom.toLowerCase().startsWith("auto_")) {
    flash("Le préfixe « auto_ » est réservé aux sauvegardes automatiques.");
    return;
  }
  try {
    const reponse = await api(
      `/api/parties/${client.partieId}/sauvegarder`, { fichier: `${nom}.json` },
    );
    flash(`Partie sauvegardée : ${reponse.fichier}`);
    journal(`Partie sauvegardée durablement sous « ${reponse.fichier} ».`);
  } catch (erreur) {
    flash("Sauvegarde impossible : " + erreur.message);
  }
});
$("replay-quitter").addEventListener("click", quitterReplay);
$("replay-pause").addEventListener("click", () => {
  const replay = client.replay;
  if (!replay) return;
  if (replay.enPause && replay.index >= replay.histoire.length - 1) {
    replay.index = 0;  // relecture depuis le début, comme x45
  }
  replay.enPause = !replay.enPause;
  majReplay();
});
$("replay-position").addEventListener("input", () => {
  const replay = client.replay;
  if (!replay) return;
  replay.index = Number($("replay-position").value);
  replay.enPause = true;
  majReplay();
});

// Le bouton de vue cycle forteresses → toutes les icônes → religion (x45).
$("bouton-vue").addEventListener("click", () => {
  const suivante = VUES_CARTE[(VUES_CARTE.indexOf(client.vueCarte) + 1) % VUES_CARTE.length];
  client.vueCarte = suivante;
  localStorage.setItem("jeux_strat_vue", suivante);
  $("bouton-vue").textContent = LIBELLES_VUES[suivante];
  dessinerCarte();
});

$("bouton-fin-attaque").addEventListener("click", () =>
  envoyerAction({ type: "terminer_attaque" }));
$("bouton-fin-achats").addEventListener("click", () =>
  envoyerAction({ type: "terminer_achats" }));
$("bouton-fin-tour").addEventListener("click", () =>
  envoyerAction({ type: "fin_de_tour" }));
$("bouton-mode-ia").addEventListener("click", () => {
  if (client.monSiege === null) return;
  envoyer({ type: "mode_auto", actif: !enModeAuto(client.monSiege) });
});

function passerPhaseSuivante() {
  // Miroir de x45 : Échap/Entrée terminent la phase en cours.
  const etat = client.etat;
  if (etat.phase === "shopping") {
    envoyerAction({ type: "terminer_achats" });
  } else if (etat.turn_phase === "attack") {
    envoyerAction({ type: "terminer_attaque" });
  } else if (etat.turn_phase === "move") {
    envoyerAction({ type: "fin_de_tour" });
  }
}

document.addEventListener("keydown", (evenement) => {
  if ($("ecran-partie").hidden) return;
  // En replay : Échap quitte, Espace met en pause (comme x45).
  if (client.replay) {
    if (evenement.key === "Escape") {
      evenement.preventDefault();
      quitterReplay();
    } else if (evenement.key === " ") {
      evenement.preventDefault();
      $("replay-pause").click();
    }
    return;
  }
  if (evenement.key !== "Escape" && evenement.key !== "Enter") return;
  if (!aMonTour()) return;
  const focus = document.activeElement;
  if (focus && ["INPUT", "TEXTAREA", "SELECT"].includes(focus.tagName)) {
    // Dans un champ (chat...) : Entrée y reste, Échap en sort seulement.
    if (evenement.key === "Escape") focus.blur();
    return;
  }
  if (focus && focus.tagName === "BUTTON") {
    if (evenement.key === "Enter") return;  // Entrée = le clic natif du bouton
    focus.blur();
  }
  evenement.preventDefault();
  passerPhaseSuivante();
});

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
    const cle = String(client.monSiege);
    const or = etat.player_money[cle] || 0;
    const science = etat.player_science[cle] || 0;
    const apercu = (etat.apercus || {})[cle];
    $("info-tresor").textContent = apercu
      ? `Or : ${or} (+${apercu.revenu}/tour) — Science : ${science} ` +
        `(+${apercu.science_gain}) — Culture : ${apercu.culture}`
      : `Or : ${or} — Science : ${science}`;
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
    if (siege.ia && siege.nom) {
      // Siège humain confié à l'IA : le réservataire garde son nom.
      texte.textContent = `${siege.nom}${siege.joueur === client.monSiege ? " (toi)" : ""}` +
        ` — IA aux commandes${personnaliteIA(etat, siege.joueur)}`;
    } else if (siege.ia) {
      texte.textContent = `IA ${siege.joueur}${personnaliteIA(etat, siege.joueur)}`;
    } else if (siege.nom) {
      texte.textContent = siege.nom + (siege.joueur === client.monSiege ? " (toi)" : "");
      if (!siege.connecte) {
        texte.classList.add("deconnecte");
        texte.textContent += " — absent";
      }
    } else {
      texte.textContent = `Siège ${siege.joueur} libre`;
    }
    // La ligne géopolitique du joueur (équivalent du panneau de x45).
    if (etat && siege.actif) {
      const cle = String(siege.joueur);
      const possessions = etat.territories_state.filter((s) => s.owner === siege.joueur);
      const regiments = possessions.reduce((somme, s) => somme + s.regiments, 0);
      const apercu = (etat.apercus || {})[cle];
      const stats = document.createElement("span");
      stats.className = "statistiques";
      stats.textContent =
        `${possessions.length} terr. · ${regiments} rég. · ` +
        `${etat.player_money[cle] || 0} écus` +
        (apercu ? ` (+${apercu.revenu}) · sci ${etat.player_science[cle] || 0}` +
                  ` (+${apercu.science_gain}) · cult ${apercu.culture}` : "");
      texte.append(stats);
    }
    element.append(pion, texte);

    if (siege.actif && siege.joueur === client.monSiege) {
      // Mon siège : bascule humain ↔ IA, et départ (une fois la main reprise).
      const basculer = document.createElement("button");
      basculer.textContent = siege.ia ? "Reprendre la main" : "Laisser l'IA jouer";
      basculer.className = "secondaire";
      basculer.addEventListener("click", () =>
        envoyer({ type: "mode_auto", actif: !siege.ia }));
      element.append(basculer);
      if (!siege.ia) {
        const bouton = document.createElement("button");
        bouton.textContent = "Quitter";
        bouton.className = "danger";
        bouton.addEventListener("click", () => envoyer({ type: "quitter_siege" }));
        element.append(bouton);
      }
    } else if (!siege.ia && siege.actif && !siege.nom && client.monSiege === null) {
      const bouton = document.createElement("button");
      bouton.textContent = "S'asseoir";
      bouton.addEventListener("click", () =>
        envoyer({ type: "prendre_siege", joueur: siege.joueur }));
      element.append(bouton);
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

// Message flash au-dessus de la carte : impossible à rater, disparaît seul.
// Pour tout ce qui est refusé (serveur ou clic invalide) — le journal garde
// la trace, le flash prévient sur le moment.
let minuterieFlash = null;

function flash(texte) {
  const zone = $("message-flash");
  zone.textContent = texte;
  zone.hidden = false;
  zone.classList.remove("apparition");
  void zone.offsetWidth;  // relance l'animation si un flash était en cours
  zone.classList.add("apparition");
  clearTimeout(minuterieFlash);
  minuterieFlash = setTimeout(() => { zone.hidden = true; }, 3500);
}

// ---------------------------------------------------------------------------
// Écran de victoire — spectaculaire, expliqué, et effacé pendant le replay
// ---------------------------------------------------------------------------

function lancerConfettis(conteneur) {
  const confettis = document.createElement("div");
  confettis.id = "confettis";
  for (let i = 0; i < 90; i += 1) {
    const piece = document.createElement("span");
    const taille = 6 + Math.random() * 7;
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.width = `${taille}px`;
    piece.style.height = `${taille * 0.45}px`;
    piece.style.background = rgb(COULEURS_JOUEURS[i % COULEURS_JOUEURS.length]);
    piece.style.animationDelay = `${Math.random() * 4}s`;
    piece.style.animationDuration = `${2.5 + Math.random() * 2.5}s`;
    confettis.append(piece);
  }
  conteneur.append(confettis);
}

function afficherVictoire() {
  const bandeau = $("bandeau-victoire");
  const info = client.victoire;
  if (!info || client.replay) {
    bandeau.hidden = true;
    return;
  }
  const nom = nomDuJoueur(info.vainqueur);
  const cEstMoi = info.vainqueur === client.monSiege;
  bandeau.textContent = "";
  lancerConfettis(bandeau);

  const carte = document.createElement("div");
  carte.className = "carte-victoire";
  const feux = document.createElement("div");
  feux.className = "feux";
  feux.textContent = "🎆 🏆 🎆";
  const titre = document.createElement("div");
  titre.className = "titre-victoire";
  titre.textContent = cEstMoi ? "TU AS GAGNÉ !" : "VICTOIRE !";
  const vainqueur = document.createElement("div");
  vainqueur.className = "vainqueur";
  vainqueur.style.color = rgb(couleurJoueur(info.vainqueur));
  vainqueur.textContent = cEstMoi
    ? `${nom}, l'histoire retiendra ton nom 🎉`
    : `${nom} remporte la partie 🎉`;
  const raison = document.createElement("div");
  raison.className = "raison";
  raison.textContent = (info.raison || "") +
    (client.etat ? ` (tour ${client.etat.turn})` : "");

  const boutons = document.createElement("div");
  boutons.className = "boutons-victoire";
  const versReplay = document.createElement("button");
  versReplay.type = "button";
  versReplay.textContent = "🎬 Revoir la partie";
  versReplay.addEventListener("click", demarrerReplay);
  const voirCarte = document.createElement("button");
  voirCarte.type = "button";
  voirCarte.className = "secondaire";
  voirCarte.textContent = "Voir la carte";
  voirCarte.addEventListener("click", () => { bandeau.hidden = true; });
  const versLobby = document.createElement("button");
  versLobby.type = "button";
  versLobby.className = "secondaire";
  versLobby.textContent = "← Retour au lobby";
  versLobby.addEventListener("click", () => $("bouton-retour-lobby").click());
  boutons.append(versReplay, voirCarte, versLobby);

  carte.append(feux, titre, vainqueur, raison, boutons);
  bandeau.append(carte);
  bandeau.hidden = false;
}

function journalRapportTour(rapport) {
  // Les événements d'une fin de tour (miroir de TurnAdvanceReport).
  if (!rapport) return;
  const textes = [];
  if (rapport.reinforcement_report && rapport.reinforcement_report.message) {
    textes.push(rapport.reinforcement_report.message);
  }
  textes.push(rapport.sedition_message, rapport.market_message);
  textes.push(...(rapport.resource_messages || []));
  textes.push(...(rapport.religion_messages || []));
  textes.push(...(rapport.empire_messages || []));
  if (rapport.begin_turn) textes.push(...(rapport.begin_turn.turn_notes || []));
  for (const texte of textes) {
    if (texte) journal(texte);
  }
}

function journalResultat(message) {
  const action = message.action;
  const outcome = message.resultat && message.resultat.outcome;
  if (action && outcome) {
    const passes = outcome.attack_passes || [];
    if (passes.length) {
      // Dés de la dernière passe + messages notables de toutes les passes.
      const derniere = passes[passes.length - 1];
      journal(`${nomDuJoueur(message.joueur)} attaque : ${derniere.att_text} / ${derniere.def_text}`);
      if (passes.some((p) => p.conquered)) journal("Territoire conquis !");
      for (const passe of passes) {
        for (const texte of [passe.special_conquest_message,
                             passe.alliance_break_message,
                             passe.elimination_message]) {
          if (texte) journal(texte);
        }
      }
    } else if (action.type === "deplacer") {
      journal(`${nomDuJoueur(message.joueur)} déplace un régiment.`);
    } else if (outcome.message) {
      journal(outcome.message);
    } else {
      const libelles = {
        terminer_attaque: "fin de la phase d'attaque",
        terminer_achats: "fin des achats",
        fin_de_tour: "fin de tour",
      };
      journal(`${nomDuJoueur(message.joueur)} : ${libelles[action.type] || action.type}.`);
    }
    journalRapportTour(outcome.turn_report);
  }
  // Fin d'un tour IA (les passes d'attaque ont été racontées en direct).
  const rapports = (message.resultat && message.resultat.rapports_ia) || [];
  for (const rapport of rapports) {
    journal(`${nomDuJoueur(message.joueur)} termine son tour` +
            (rapport.attack_passes ? ` (${rapport.attack_passes} passe(s) d'attaque).` : "."));
    journalRapportTour(rapport.turn_report);
  }
}

$("bouton-retour-lobby").addEventListener("click", () => {
  quitterReplay();
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
    `Voisins : ${territoire.neighbors.length}`,
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
    if (tid === id) etiquettes.push(`merveille (${MERVEILLES[type] || type})`);
  }
  const religionInfluente = (etat.religious_influence || {})[String(id)];
  if (religionInfluente !== undefined) {
    etiquettes.push(`influence de ${RELIGIONS[religionInfluente].nom}`);
  }
  const saint = lieuSaint(etat, id);
  if (saint !== null) etiquettes.push(`lieu saint de ${RELIGIONS[saint].nom}`);
  if (capitalesParadisFiscal(etat).has(id)) etiquettes.push("capitale de paradis fiscal");
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

function ajusterResolutionCarte() {
  // Le canvas est rendu au nombre réel de pixels affichés (netteté sur les
  // écrans mis à l'échelle par Windows) ; le dessin reste en repère logique
  // 1200×620 grâce à la transformation.
  const carte = $("carte");
  const cadre = carte.getBoundingClientRect();
  if (!cadre.width) return;
  const dpr = window.devicePixelRatio || 1;
  const largeur = Math.round(cadre.width * dpr);
  const hauteur = Math.round(cadre.width * dpr * (HAUTEUR_CARTE / LARGEUR_CARTE));
  if (carte.width !== largeur || carte.height !== hauteur) {
    carte.width = largeur;
    carte.height = hauteur;
  }
}

window.addEventListener("resize", () => dessinerCarte());

function dessinerCarte() {
  // En replay, la carte se dessine depuis l'instantané courant.
  const etat = client.replay
    ? etatDepuisInstantane(client.replay.histoire[client.replay.index])
    : client.etat;
  if (!etat) return;
  ajusterResolutionCarte();
  const carte = $("carte");
  const contexte = carte.getContext("2d");
  // Les cellules et bordures se dessinent en pixels ENTIERS de l'écran :
  // avec des cellules de ~7 px, l'anti-aliasing des coordonnées
  // fractionnaires rendait la carte floue (pygame pose des pixels francs).
  contexte.setTransform(1, 0, 0, 1, 0, 0);
  const largeurCellule = LARGEUR_CARTE / etat.cols;
  const hauteurCellule = HAUTEUR_CARTE / etat.rows;
  const grille = etat.grid_territory;
  const situations = etat.territories_state;
  const enroule = etat.map_mode === "custom";
  // Bornes entières de chaque colonne/ligne : aucune couture, aucun flou.
  const bordsX = Array.from({ length: etat.cols + 1 },
    (_, c) => Math.round(c * carte.width / etat.cols));
  const bordsY = Array.from({ length: etat.rows + 1 },
    (_, r) => Math.round(r * carte.height / etat.rows));
  const echelle = carte.width / LARGEUR_CARTE;
  const epaisseur = (logique) => Math.max(1, Math.round(logique * echelle));

  // Cibles attaquables depuis la source sélectionnée (teinte rouge, x45).
  const sourceAttaque = aMonTour() && etat.phase === "playing"
    && etat.turn_phase === "attack" && client.selection !== null
    && situations[client.selection].owner === client.monSiege
    ? client.selection : null;
  const ciblesAttaquables = new Set(
    sourceAttaque !== null
      ? etat.territories[sourceAttaque].neighbors
          .filter((voisin) => situations[voisin].owner !== client.monSiege)
      : [],
  );

  // Couleur de remplissage de chaque territoire (mêmes règles que x45) ;
  // en vue religion, la couleur vient de l'influence religieuse.
  const vueReligion = client.vueCarte === "religion";
  const influence = etat.religious_influence || {};
  const remplissages = situations.map((situation) => {
    let couleur;
    if (vueReligion) {
      const religion = influence[String(situation.id)];
      const base = religion === undefined
        ? [58, 65, 72] : RELIGIONS[religion].couleur;
      couleur = base.map((c) => Math.max(28, Math.round(c * 0.78)));
    } else {
      const base = couleurJoueur(situation.owner);
      couleur = situation.owner === etat.current_player
        ? base.map((c) => Math.min(255, Math.round(c * 1.12) + 10))
        : base.map((c) => Math.round(c * 0.72));
    }
    if (situation.id === client.selection) {
      couleur = couleur.map((c) => Math.min(255, c + 70));
    } else if (ciblesAttaquables.has(situation.id)) {
      couleur = [
        Math.min(255, couleur[0] + 50),
        Math.max(0, couleur[1] - 10),
        Math.max(0, couleur[2] - 10),
      ];
    }
    return rgb(couleur);
  });

  contexte.fillStyle = rgb(COULEUR_EAU);
  contexte.fillRect(0, 0, carte.width, carte.height);
  for (let r = 0; r < etat.rows; r += 1) {
    for (let c = 0; c < etat.cols; c += 1) {
      const tid = grille[r][c];
      if (tid < 0) continue;
      contexte.fillStyle = remplissages[tid];
      contexte.fillRect(
        bordsX[c], bordsY[r],
        bordsX[c + 1] - bordsX[c], bordsY[r + 1] - bordsY[r],
      );
    }
  }

  // Bordures : fines entre territoires, jaunes pour le joueur au trait,
  // violettes (soumis) ou blanches (sanctuaire) épaisses — dessinées en
  // rectangles pleins à l'intérieur de la cellule (pixels nets).
  function styleBordure(tid) {
    if (etat.submitted_territory_ids.includes(tid)) return ["rgb(185,90,255)", epaisseur(4)];
    if (etat.sanctuary_territory_ids.includes(tid)) return ["rgb(230,245,255)", epaisseur(4)];
    const proprietaire = situations[tid].owner;
    if (proprietaire === etat.current_player) return ["rgb(255,220,50)", epaisseur(2)];
    return ["rgb(20,20,20)", 1];
  }
  for (let r = 0; r < etat.rows; r += 1) {
    for (let c = 0; c < etat.cols; c += 1) {
      const tid = grille[r][c];
      if (tid < 0) continue;
      const [couleur, ep] = styleBordure(tid);
      const x0 = bordsX[c], y0 = bordsY[r];
      const largeur = bordsX[c + 1] - x0, hauteur = bordsY[r + 1] - y0;
      const haut = enroule ? grille[(r - 1 + etat.rows) % etat.rows][c] : (r > 0 ? grille[r - 1][c] : null);
      const bas = enroule ? grille[(r + 1) % etat.rows][c] : (r < etat.rows - 1 ? grille[r + 1][c] : null);
      const gauche = enroule ? grille[r][(c - 1 + etat.cols) % etat.cols] : (c > 0 ? grille[r][c - 1] : null);
      const droite = enroule ? grille[r][(c + 1) % etat.cols] : (c < etat.cols - 1 ? grille[r][c + 1] : null);
      contexte.fillStyle = couleur;
      if (haut !== tid) contexte.fillRect(x0, y0, largeur, ep);
      if (bas !== tid) contexte.fillRect(x0, y0 + hauteur - ep, largeur, ep);
      if (gauche !== tid) contexte.fillRect(x0, y0, ep, hauteur);
      if (droite !== tid) contexte.fillRect(x0 + largeur - ep, y0, ep, hauteur);
    }
  }

  // Le reste (liens, étiquettes, badges) se dessine en repère logique
  // 1200×620 : formes lisses, l'anti-aliasing y est bienvenu.
  contexte.setTransform(
    carte.width / LARGEUR_CARTE, 0, 0, carte.height / HAUTEUR_CARTE, 0, 0,
  );
  dessinerLiens(contexte, etat, largeurCellule, hauteurCellule);
  if (vueReligion) {
    dessinerVueReligion(contexte, etat, largeurCellule, hauteurCellule);
  } else {
    dessinerEtiquettes(contexte, etat, largeurCellule, hauteurCellule);
  }
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

// ---------------------------------------------------------------------------
// Statuts calculés côté client (miroir des assistants de x45)
// ---------------------------------------------------------------------------

function comptesAmenagements(etat, tid) {
  // Miroir de get_territory_amenagement_count : forteresse + industrie
  // (usine/aéroport/port, exclusifs) + temple + centre culturel + université.
  let compte = 0;
  if (etat.fortress_territory_ids.includes(tid)) compte += 1;
  if (etat.factory_territory_ids.includes(tid)
      || etat.airport_territory_ids.includes(tid)
      || etat.port_territory_ids.includes(tid)) compte += 1;
  if (etat.temple_territory_ids.includes(tid)) compte += 1;
  if ((etat.cultural_center_ages[String(tid)] || []).length) compte += 1;
  if (etat.university_territory_ids.includes(tid)) compte += 1;
  return compte;
}

function capitaleActive(etat, tid) {
  // Miroir d'is_active_regular_capital : le badge disparaît si la capitale
  // est occupée par un autre joueur (ou si son joueur est ONU/CC).
  for (const [joueur, capitale] of Object.entries(etat.player_capital_ids)) {
    if (capitale !== tid) continue;
    const proprietaire = Number(joueur);
    return etat.territories_state[tid].owner === proprietaire
      && proprietaire !== etat.onu_player_id
      && !etat.commercial_city_players.includes(proprietaire)
      ? { nation: etat.nation_players.includes(proprietaire) }
      : null;
  }
  return null;
}

function lieuSaint(etat, tid) {
  for (const [religion, siege] of Object.entries(etat.religion_holy_sites)) {
    if (siege === tid && Number(religion) !== RELIGION_MERVEILLE) {
      return Number(religion);
    }
  }
  return null;
}

function capitalesParadisFiscal(etat) {
  const ids = new Set();
  for (const liste of Object.values(etat.last_stand_bonus_territory || {})) {
    for (const tid of liste) ids.add(tid);
  }
  return ids;
}

// ---------------------------------------------------------------------------
// Badges (pictogrammes x45 transposés en canvas, mêmes couleurs)
// ---------------------------------------------------------------------------

function fondBadge(ctx, x, y, largeur, hauteur, fond, bord, arrondi = 6) {
  ctx.beginPath();
  ctx.roundRect(x - largeur / 2, y - hauteur / 2, largeur, hauteur, arrondi);
  ctx.fillStyle = fond;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = bord;
  ctx.stroke();
}

function glypheBadge(ctx, x, y, texte, couleur, taille = 10) {
  ctx.font = `bold ${taille}px 'Segoe UI', sans-serif`;
  ctx.textBaseline = "middle";
  ctx.fillStyle = couleur;
  ctx.fillText(texte, x - ctx.measureText(texte).width / 2, y + 1);
}

function dessinerBadge(ctx, type, x, y, etat, tid) {
  const g = (gauche) => x - 14 + gauche;   // repère local du badge 28x24
  const h = (haut) => y - 12 + haut;
  if (type === "fortress") {
    fondBadge(ctx, x, y, 28, 24, "rgb(196,198,201)", "rgb(44,62,80)");
    ctx.fillStyle = "rgb(52,73,94)";
    ctx.fillRect(g(4), h(10), 20, 9);
    for (const tourX of [4, 12, 20]) ctx.fillRect(g(tourX), h(5), 4, 13);
    ctx.fillStyle = "rgb(236,240,241)";
    ctx.fillRect(g(12), h(13), 4, 6);
  } else if (type === "precious_mine") {
    fondBadge(ctx, x, y, 28, 24, "rgb(72,62,92)", "rgb(225,215,245)");
    ctx.beginPath();
    ctx.moveTo(g(14), h(3));
    ctx.lineTo(g(21), h(10));
    ctx.lineTo(g(17), h(21));
    ctx.lineTo(g(10), h(21));
    ctx.lineTo(g(6), h(10));
    ctx.closePath();
    ctx.fillStyle = "rgb(174,235,255)";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgb(48,95,125)";
    ctx.stroke();
  } else if (type.startsWith("wonder:")) {
    const couleurs = {
      elyrion_sanctuary: ["rgb(52,88,116)", "rgb(174,235,255)", "E"],
      thousand_voices_theatre: ["rgb(92,50,112)", "rgb(235,188,255)", "T"],
      atlas_observatory: ["rgb(32,68,108)", "rgb(150,215,255)", "O"],
      golden_pact_palace: ["rgb(105,77,20)", "rgb(255,220,92)", "P"],
      ivory_rampart: ["rgb(60,72,88)", "rgb(240,234,214)", "R"],
      croesus_fountain: ["rgb(24,96,58)", "rgb(150,245,185)", "F"],
      aurelia_capitol: ["rgb(98,36,84)", "rgb(245,190,235)", "C"],
      daedalus_forge: ["rgb(122,68,24)", "rgb(255,196,128)", "D"],
    };
    const [fond, symbole, lettre] = couleurs[type.split(":")[1]]
      || ["rgb(70,70,70)", "rgb(235,235,235)", "?"];
    fondBadge(ctx, x, y, 30, 26, fond, symbole, 7);
    glypheBadge(ctx, x, y, lettre, symbole, 13);
  } else if (type === "factory") {
    fondBadge(ctx, x, y, 28, 24, "rgb(133,193,233)", "rgb(44,62,80)");
    ctx.fillStyle = "rgb(28,42,56)";
    ctx.beginPath();
    ctx.moveTo(g(5), h(18));
    ctx.lineTo(g(5), h(12));
    ctx.lineTo(g(11), h(8));
    ctx.lineTo(g(11), h(12));
    ctx.lineTo(g(17), h(8));
    ctx.lineTo(g(17), h(12));
    ctx.lineTo(g(23), h(12));
    ctx.lineTo(g(23), h(18));
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(g(18), h(4), 3, 8);
  } else if (type === "airport") {
    fondBadge(ctx, x, y, 28, 24, "rgb(174,214,241)", "rgb(44,62,80)");
    ctx.fillStyle = "rgb(28,42,56)";
    ctx.beginPath();  // fuselage vertical + ailes
    ctx.moveTo(g(14), h(4));
    ctx.lineTo(g(17), h(15));
    ctx.lineTo(g(14), h(20));
    ctx.lineTo(g(11), h(15));
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(g(4), h(12));
    ctx.lineTo(g(24), h(12));
    ctx.lineTo(g(18), h(15));
    ctx.lineTo(g(10), h(15));
    ctx.closePath();
    ctx.fill();
  } else if (type === "port") {
    fondBadge(ctx, x, y, 28, 24, "rgb(118,215,196)", "rgb(44,62,80)");
    ctx.fillStyle = "rgb(28,42,56)";
    ctx.beginPath();  // coque
    ctx.moveTo(g(5), h(14));
    ctx.lineTo(g(23), h(14));
    ctx.lineTo(g(19), h(19));
    ctx.lineTo(g(8), h(19));
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(g(10), h(8), 8, 6);
  } else if (type === "temple" || type === "university") {
    const [fond, trait] = type === "temple"
      ? ["rgb(245,203,167)", "rgb(112,66,20)"]
      : ["rgb(214,234,248)", "rgb(36,76,112)"];
    fondBadge(ctx, x, y, 28, 24, fond, trait);
    ctx.fillStyle = trait;
    ctx.beginPath();  // fronton
    ctx.moveTo(g(4), h(10));
    ctx.lineTo(g(14), h(4));
    ctx.lineTo(g(24), h(10));
    ctx.closePath();
    ctx.fill();
    for (const px of [7, 12, 17]) ctx.fillRect(g(px), h(11), 3, 7);
    ctx.fillRect(g(5), h(18), 18, 2);
  } else if (type === "culture") {
    fondBadge(ctx, x, y, 28, 24, "rgb(215,189,226)", "rgb(84,52,94)");
    ctx.strokeStyle = "rgb(84,52,94)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(g(6), h(18));
    ctx.lineTo(g(14), h(6));
    ctx.lineTo(g(22), h(18));
    ctx.moveTo(g(8), h(18));
    ctx.lineTo(g(20), h(18));
    ctx.stroke();
    const nombre = (etat.cultural_center_ages[String(tid)] || []).length;
    if (nombre > 1) glypheBadge(ctx, g(23), h(7), String(nombre), "rgb(84,52,94)");
  } else if (type === "capital" || type === "capital_nation") {
    if (type === "capital_nation") {
      ctx.beginPath();
      ctx.arc(x, y, 15, 0, 2 * Math.PI);
      ctx.fillStyle = "rgb(255,255,210)";
      ctx.fill();
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgb(255,210,40)";
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(x, y, 11, 0, 2 * Math.PI);
    ctx.fillStyle = type === "capital_nation" ? "rgb(255,245,90)" : "rgb(255,245,170)";
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = type === "capital_nation" ? "rgb(120,70,0)" : "rgb(90,55,10)";
    ctx.stroke();
    glypheBadge(ctx, x, y, "C", "rgb(20,20,20)", 12);
  } else if (type === "money" || type === "commercial_money") {
    const cc = type === "commercial_money";
    fondBadge(ctx, x, y, 28, 24,
      cc ? "rgb(42,197,210)" : "rgb(248,218,92)",
      cc ? "rgb(12,73,84)" : "rgb(99,73,18)");
    glypheBadge(ctx, x, y, cc ? "CC" : "x10", cc ? "rgb(6,48,55)" : "rgb(71,48,11)");
  } else if (type.startsWith("holy_site:")) {
    dessinerBadgeReligion(ctx, x, y, Number(type.split(":")[1]), true);
  }
}

function dessinerBadgeReligion(ctx, x, y, religion, saint) {
  const definition = RELIGIONS[religion] || { symbole: "?", couleur: [200, 200, 200] };
  ctx.beginPath();
  ctx.arc(x, y, saint ? 14 : 10, 0, 2 * Math.PI);
  ctx.fillStyle = rgb(definition.couleur);
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = saint ? "rgb(255,255,255)" : "rgb(35,35,35)";
  ctx.stroke();
  glypheBadge(ctx, x, y, definition.symbole, "rgb(18,24,30)");
}

function dessinerCercleAmenagements(ctx, x, y, compte, maximum, couleur) {
  // Miroir de draw_amenagement_progress_circle : camembert de progression.
  const rayon = 8;
  ctx.beginPath();
  ctx.arc(x, y, rayon, 0, 2 * Math.PI);
  ctx.fillStyle = rgb(COULEUR_FOND);
  ctx.fill();
  if (compte > 0) {
    ctx.beginPath();
    if (compte >= maximum) {
      ctx.arc(x, y, rayon - 2, 0, 2 * Math.PI);
    } else {
      ctx.moveTo(x, y);
      ctx.arc(x, y, rayon - 2, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * (compte / maximum));
      ctx.closePath();
    }
    ctx.fillStyle = couleur;
    ctx.fill();
  }
  ctx.beginPath();
  ctx.arc(x, y, rayon, 0, 2 * Math.PI);
  ctx.lineWidth = 2;
  ctx.strokeStyle = "rgb(235,235,235)";
  ctx.stroke();
}

function dessinerEtiquettes(contexte, etat, largeurCellule, hauteurCellule) {
  const vueComplete = client.vueCarte === "all";
  const capitalesPF = capitalesParadisFiscal(etat);
  contexte.textBaseline = "middle";
  for (const territoire of etat.territories) {
    if (!territoire.cells.length) continue;
    const situation = etat.territories_state[territoire.id];
    const tid = territoire.id;
    const [ligneCentre, colonneCentre] = centreTerritoire(etat, territoire);
    const cx = (colonneCentre + 0.5) * largeurCellule;
    const cy = (ligneCentre + 0.5) * hauteurCellule;
    const base = couleurJoueur(situation.owner);

    // Boîte : cercle d'aménagements + nombre de régiments (comme x45).
    contexte.font = "13px 'Segoe UI', sans-serif";
    const texte = String(situation.regiments);
    const largeurTexte = contexte.measureText(texte).width;
    const largeurBoite = 22 + largeurTexte + 10;
    const hauteurBoite = 20;
    let x = Math.max(4, Math.min(LARGEUR_CARTE - largeurBoite - 4, cx - largeurBoite / 2));
    if (situation.reinforcement_bonus > 1) x -= 10;
    let y = Math.max(2, Math.min(HAUTEUR_CARTE - hauteurBoite - 4, cy - hauteurBoite / 2));

    contexte.fillStyle = rgb(base.map((c) => Math.max(0, Math.round(c * 0.30) + 8)));
    contexte.strokeStyle = rgb(base.map((c) => Math.min(255, Math.round(c * 0.85))));
    contexte.lineWidth = 1;
    contexte.beginPath();
    contexte.roundRect(x, y, largeurBoite, hauteurBoite, 4);
    contexte.fill();
    contexte.stroke();
    const couleurIcone = rgb(base.map((c) => Math.min(255, Math.round(c * 1.6) + 40)));
    dessinerCercleAmenagements(
      contexte, x + 12, y + hauteurBoite / 2,
      comptesAmenagements(etat, tid), 5, couleurIcone,
    );
    contexte.font = "13px 'Segoe UI', sans-serif";
    contexte.fillStyle = "rgb(235,235,235)";
    contexte.fillText(texte, x + 26, y + hauteurBoite / 2 + 1);

    // Territoire doré : disque or à gauche de la boîte.
    if (etat.golden_territory_ids.includes(tid)) {
      const gx = Math.max(16, Math.min(LARGEUR_CARTE - 16, x - 16));
      const gy = Math.max(16, y + hauteurBoite / 2);
      contexte.beginPath();
      contexte.arc(gx, gy, 12, 0, 2 * Math.PI);
      contexte.fillStyle = "rgb(255,215,0)";
      contexte.fill();
      contexte.lineWidth = 2;
      contexte.strokeStyle = "rgb(120,90,0)";
      contexte.stroke();
      contexte.beginPath();
      contexte.arc(gx, gy, 7, 0, 2 * Math.PI);
      contexte.fillStyle = "rgb(255,235,120)";
      contexte.fill();
      contexte.beginPath();
      contexte.arc(gx, gy, 4, 0, 2 * Math.PI);
      contexte.fillStyle = "rgb(255,250,210)";
      contexte.fill();
    }
    // Bonus de renforts : pastille +n à droite (couleurs x45).
    if (situation.reinforcement_bonus > 1) {
      const bx = Math.min(LARGEUR_CARTE - 14, x + largeurBoite + 12);
      const by = Math.max(12, y + hauteurBoite / 2);
      const rayon = situation.reinforcement_bonus === 2 ? 9 : 11;
      contexte.beginPath();
      contexte.arc(bx, by, rayon, 0, 2 * Math.PI);
      contexte.fillStyle = situation.reinforcement_bonus === 2
        ? "rgb(241,196,15)" : "rgb(230,126,34)";
      contexte.fill();
      contexte.lineWidth = 2;
      contexte.strokeStyle = "rgb(44,62,80)";
      contexte.stroke();
      glypheBadge(contexte, bx, by, `+${situation.reinforcement_bonus}`, "rgb(20,20,20)");
    }

    // Rangée de badges au-dessus de la boîte (ordre et règles de x45) :
    // les statuts restent visibles dans toutes les vues, les aménagements
    // secondaires seulement en vue « toutes les icônes ».
    const badges = [];
    if (etat.fortress_territory_ids.includes(tid)) badges.push("fortress");
    if (etat.precious_mineral_mine_ids.includes(tid)) badges.push("precious_mine");
    for (const [typeMerveille, siege] of Object.entries(etat.wonder_territories)) {
      if (siege === tid) badges.push(`wonder:${typeMerveille}`);
    }
    const religionSainte = lieuSaint(etat, tid);
    if (religionSainte !== null) badges.push(`holy_site:${religionSainte}`);
    if (vueComplete) {
      if (etat.factory_territory_ids.includes(tid)) badges.push("factory");
      if (etat.airport_territory_ids.includes(tid)) badges.push("airport");
      if (etat.port_territory_ids.includes(tid)) badges.push("port");
      if (etat.temple_territory_ids.includes(tid)) badges.push("temple");
      if ((etat.cultural_center_ages[String(tid)] || []).length) badges.push("culture");
      if (etat.university_territory_ids.includes(tid)) badges.push("university");
    }
    const capitale = capitaleActive(etat, tid);
    if (capitale) badges.push(capitale.nation ? "capital_nation" : "capital");
    if (capitalesPF.has(tid)) {
      badges.push(etat.commercial_city_players.includes(situation.owner)
        ? "commercial_money" : "money");
    }
    if (badges.length) {
      const espacement = 32;
      const debut = x + largeurBoite / 2 - (badges.length - 1) * (espacement / 2);
      const badgeY = Math.max(14, y - 14);
      badges.forEach((type, index) => {
        const badgeX = Math.max(16, Math.min(LARGEUR_CARTE - 16, debut + index * espacement));
        dessinerBadge(contexte, type, badgeX, badgeY, etat, tid);
      });
    }
  }
}

function dessinerVueReligion(contexte, etat, largeurCellule, hauteurCellule) {
  // Miroir de draw_religion_view_symbols : noms des territoires, lieux
  // saints en grand, et légende des religions fondées.
  contexte.textBaseline = "middle";
  contexte.font = "12px 'Segoe UI', sans-serif";
  for (const territoire of etat.territories) {
    if (!territoire.cells.length) continue;
    const [ligneCentre, colonneCentre] = centreTerritoire(etat, territoire);
    const cx = (colonneCentre + 0.5) * largeurCellule;
    const cy = (ligneCentre + 0.5) * hauteurCellule + 22;
    const largeurTexte = contexte.measureText(territoire.name).width;
    const x = Math.max(3, Math.min(LARGEUR_CARTE - largeurTexte - 3, cx - largeurTexte / 2));
    const y = Math.max(10, Math.min(HAUTEUR_CARTE - 10, cy));
    contexte.fillStyle = "rgb(22,28,34)";
    contexte.strokeStyle = "rgb(210,216,222)";
    contexte.lineWidth = 1;
    contexte.beginPath();
    contexte.roundRect(x - 4, y - 9, largeurTexte + 8, 18, 4);
    contexte.fill();
    contexte.stroke();
    contexte.fillStyle = "rgb(245,247,250)";
    contexte.fillText(territoire.name, x, y + 1);
  }
  for (const [religion, tid] of Object.entries(etat.religion_holy_sites)) {
    const territoire = etat.territories[tid];
    if (!territoire || !territoire.cells.length) continue;
    const [ligneCentre, colonneCentre] = centreTerritoire(etat, territoire);
    dessinerBadgeReligion(
      contexte,
      (colonneCentre + 0.5) * largeurCellule,
      (ligneCentre + 0.5) * hauteurCellule,
      Number(religion), true,
    );
  }
  // Légende des religions fondées, en haut à gauche (comme x45).
  const fondees = [...new Set(Object.values(etat.religion_founders))].sort();
  let legendeY = 22;
  contexte.font = "12px 'Segoe UI', sans-serif";
  for (const religion of fondees) {
    dessinerBadgeReligion(contexte, 30, legendeY, religion, false);
    contexte.fillStyle = "rgb(236,240,241)";
    contexte.fillText(RELIGIONS[religion].nom, 46, legendeY + 1);
    legendeY += 24;
  }
}

function territoireSousLaSouris(evenement) {
  const etat = client.etat;
  const cadre = $("carte").getBoundingClientRect();
  const x = (evenement.clientX - cadre.left) * (LARGEUR_CARTE / cadre.width);
  const y = (evenement.clientY - cadre.top) * (HAUTEUR_CARTE / cadre.height);
  const colonne = Math.floor(x / (LARGEUR_CARTE / etat.cols));
  const ligne = Math.floor(y / (HAUTEUR_CARTE / etat.rows));
  if (ligne < 0 || ligne >= etat.rows || colonne < 0 || colonne >= etat.cols) return null;
  const tid = etat.grid_territory[ligne][colonne];
  return tid >= 0 ? tid : null;
}

// Clic gauche : sélection / attaque simple / déplacement.
$("carte").addEventListener("click", (evenement) => {
  if (!client.etat || client.replay) return;
  traiterClicTerritoire(territoireSousLaSouris(evenement), false);
});

// Clic droit : assaut total, comme dans x45.
$("carte").addEventListener("contextmenu", (evenement) => {
  evenement.preventDefault();
  if (!client.etat || client.replay) return;
  traiterClicTerritoire(territoireSousLaSouris(evenement), true);
});

function traiterClicTerritoire(tid, boutonDroit) {
  const etat = client.etat;
  const source = client.selection;
  const situation = tid !== null ? etat.territories_state[tid] : null;
  const aMoi = situation !== null && situation.owner === client.monSiege;

  // Phase d'achats : le clic gauche sert d'abord la boutique.
  if (enPhaseAchats() && !boutonDroit && clicCarteBoutique(tid)) {
    return;
  }

  if (aMonTour() && etat.phase === "playing" && tid !== null) {
    if (!boutonDroit && tid === source) {
      // Recliquer la source (clic gauche) la libère.
      client.selection = null;
      afficherDetailTerritoire();
      dessinerCarte();
      return;
    }
    if (etat.turn_phase === "attack") {
      // Source déjà choisie + clic sur un voisin ennemi : on attaque
      // (clic gauche = une passe, clic droit = assaut total, comme x45).
      if (source !== null && !aMoi
          && etat.territories[source].neighbors.includes(tid)
          && etat.territories_state[source].owner === client.monSiege) {
        envoyerAction({
          type: boutonDroit ? "assaut_total" : "attaquer",
          source, cible: tid,
        });
        return;  // la sélection reste : on peut enchaîner les passes
      }
      if (aMoi) {
        client.selection = tid;  // nouvelle source
        afficherDetailTerritoire();
        dessinerCarte();
        return;
      }
    } else if (etat.turn_phase === "move") {
      // Comme x45 : clic gauche = choisir la source, clic droit sur un
      // autre territoire à soi = y envoyer un régiment (répétable).
      if (boutonDroit) {
        if (source !== null && aMoi && source !== tid
            && etat.territories_state[source].owner === client.monSiege) {
          envoyerAction({ type: "deplacer", source, cible: tid });
        }
        return;  // le clic droit ne change jamais la sélection
      }
      if (aMoi) {
        client.selection = tid;
        afficherDetailTerritoire();
        dessinerCarte();
        return;
      }
    }
  }
  // Hors jeu (spectateur, pas mon tour, eau…) : simple sélection d'info.
  client.selection = tid;
  afficherDetailTerritoire();
  dessinerCarte();
}

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------

function initialiserPanneauxRepliables() {
  // Chaque panneau de la colonne de droite se replie d'un clic sur son
  // titre ; le choix est retenu d'une session à l'autre.
  for (const panneau of document.querySelectorAll(".zone-panneaux .panneau")) {
    const titre = panneau.querySelector("h2");
    if (!titre || !panneau.id) continue;
    const cle = "jeux_strat_" + panneau.id;
    if (localStorage.getItem(cle) === "replie") panneau.classList.add("replie");
    titre.addEventListener("click", () => {
      panneau.classList.toggle("replie");
      localStorage.setItem(
        cle, panneau.classList.contains("replie") ? "replie" : "ouvert",
      );
    });
  }
}

function demarrer() {
  initialiserPanneauxRepliables();
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
