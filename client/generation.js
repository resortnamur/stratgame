/*
 * Génération de cartes aléatoires pour le lobby — portage du « Compléter le
 * monde » de l'éditeur de Jeux Strat 2.
 *
 * L'utilisateur ne choisit que deux paramètres : le nombre de territoires et
 * le nombre de continents (les « ensembles » de l'éditeur). Tout le reste est
 * tiré au sort en mode « mix », avec les mêmes règles :
 *   - les formes des territoires sont les générateurs du jeu (bloc, étoile) ;
 *   - les noyaux des continents ne sont jamais petits, et sont posés « au
 *     large », loin les uns des autres ;
 *   - autour d'un noyau bloc : des blocs ou étoiles de taille inférieure ;
 *     autour d'un noyau étoile : des blocs de la même taille ;
 *   - les territoires suivants naissent dans les creux des continents
 *     (accrétion compacte), jamais collés aux bords de la carte (côte
 *     bruitée), sauf s'il n'y a plus de place ailleurs ;
 *   - si le nombre demandé ne tient pas, on en place autant que possible.
 *
 * Sortie : un payload de carte x45 (kind "map", map_mode "custom") que le
 * serveur sait charger tel quel — cellules et voisins sont recalculés par le
 * moteur à partir de la grille, avec l'adjacence torique des cartes custom.
 */

"use strict";

const GENERATION = (() => {
  const LIGNES = 144;
  const COLONNES = 180;
  const VIDE = -1;

  const TAILLES = {
    petite:  { cible: 80,  rayonMin: 3,  rayonMax: 5 },
    moyenne: { cible: 160, rayonMin: 4,  rayonMax: 7 },
    grande:  { cible: 250, rayonMin: 6,  rayonMax: 10 },
    immense: { cible: 720, rayonMin: 12, rayonMax: 20 },
  };
  const NOMS_TAILLES = ["petite", "moyenne", "grande", "immense"];

  // ------------------------------------------------------------------
  // Utilitaires de grille (la carte est un tore : elle boucle partout)
  // ------------------------------------------------------------------

  function idx(r, c) { return r * COLONNES + c; }
  function ligneDe(i) { return Math.floor(i / COLONNES); }
  function colonneDe(i) { return i % COLONNES; }
  function moduloPositif(valeur, taille) {
    return ((valeur % taille) + taille) % taille;
  }
  function entierAleatoire(a, b) {
    return a + Math.floor(Math.random() * (b - a + 1));
  }

  // Voisinage borné (génération des formes, comme x45).
  function voisins4(i) {
    const r = ligneDe(i), c = colonneDe(i);
    const res = [];
    if (r > 0) res.push(i - COLONNES);
    if (r < LIGNES - 1) res.push(i + COLONNES);
    if (c > 0) res.push(i - 1);
    if (c < COLONNES - 1) res.push(i + 1);
    return res;
  }

  // Voisinage torique (distances, frontières d'accrétion).
  function voisins4Toriques(i) {
    const r = ligneDe(i), c = colonneDe(i);
    return [
      idx((r + 1) % LIGNES, c),
      idx((r - 1 + LIGNES) % LIGNES, c),
      idx(r, (c + 1) % COLONNES),
      idx(r, (c - 1 + COLONNES) % COLONNES),
    ];
  }

  function choixDansEnsemble(ensemble) {
    const n = Math.floor(Math.random() * ensemble.size);
    let k = 0;
    for (const v of ensemble) {
      if (k === n) return v;
      k++;
    }
    return null;
  }

  // Pioche : ensemble à tirage aléatoire en O(1).
  function nouvellePioche(valeursInitiales) {
    const pioche = { tableau: [], indices: new Map() };
    if (valeursInitiales) for (const v of valeursInitiales) piocheAjouter(pioche, v);
    return pioche;
  }
  function piocheAjouter(pioche, valeur) {
    if (pioche.indices.has(valeur)) return;
    pioche.indices.set(valeur, pioche.tableau.length);
    pioche.tableau.push(valeur);
  }
  function piocheRetirer(pioche, valeur) {
    const position = pioche.indices.get(valeur);
    if (position === undefined) return;
    const derniere = pioche.tableau.pop();
    pioche.indices.delete(valeur);
    if (derniere !== valeur) {
      pioche.tableau[position] = derniere;
      pioche.indices.set(derniere, position);
    }
  }
  function piocheTirer(pioche) {
    return pioche.tableau[Math.floor(Math.random() * pioche.tableau.length)];
  }

  // ------------------------------------------------------------------
  // Générateurs de formes (portage fidèle de x45)
  // ------------------------------------------------------------------

  function composanteConnexe(cellules, depart) {
    const res = new Set();
    const pile = [depart];
    while (pile.length > 0) {
      const i = pile.pop();
      if (res.has(i) || !cellules.has(i)) continue;
      res.add(i);
      for (const v of voisins4(i)) {
        if (cellules.has(v) && !res.has(v)) pile.push(v);
      }
    }
    return res;
  }

  function lisserCellules(cellules, celluleCentre, disponibles) {
    for (let passe = 0; passe < 2; passe++) {
      const ajouts = new Set();
      const retraits = new Set();
      let minR = LIGNES, maxR = 0, minC = COLONNES, maxC = 0;
      for (const i of cellules) {
        const r = ligneDe(i), c = colonneDe(i);
        if (r < minR) minR = r;
        if (r > maxR) maxR = r;
        if (c < minC) minC = c;
        if (c > maxC) maxC = c;
      }
      minR = Math.max(0, minR - 1); maxR = Math.min(LIGNES - 1, maxR + 1);
      minC = Math.max(0, minC - 1); maxC = Math.min(COLONNES - 1, maxC + 1);
      for (let r = minR; r <= maxR; r++) {
        for (let c = minC; c <= maxC; c++) {
          const i = idx(r, c);
          const dedans = cellules.has(i);
          if (!dedans && !disponibles.has(i)) continue;
          let nVoisins = 0;
          for (const v of voisins4(i)) if (cellules.has(v)) nVoisins++;
          if (dedans && nVoisins <= 1 && i !== celluleCentre) {
            retraits.add(i);
          } else if (!dedans && nVoisins >= 3 && Math.random() < 0.40) {
            ajouts.add(i);
          }
        }
      }
      for (const i of retraits) cellules.delete(i);
      for (const i of ajouts) cellules.add(i);
    }
    return cellules;
  }

  function genererBloc(centre, config, disponibles) {
    const { cible, rayonMin, rayonMax } = config;
    const centreR = ligneDe(centre), centreC = colonneDe(centre);
    const cellules = new Set([centre]);
    const frontiere = nouvellePioche([centre]);
    let essais = 0;
    while (frontiere.tableau.length > 0 && cellules.size < cible && essais < cible * 30) {
      essais++;
      const base = piocheTirer(frontiere);
      const options = [];
      for (const v of voisins4(base)) {
        if (cellules.has(v) || !disponibles.has(v)) continue;
        const dist = Math.abs(ligneDe(v) - centreR) + Math.abs(colonneDe(v) - centreC);
        if (dist > rayonMax * 3 + entierAleatoire(0, rayonMax * 2)) continue;
        let memesVoisins = 0;
        for (const w of voisins4(v)) if (cellules.has(w)) memesVoisins++;
        options.push({ memesVoisins, dist, hasard: Math.random(), cellule: v });
      }
      if (options.length === 0) {
        piocheRetirer(frontiere, base);
        continue;
      }
      options.sort((a, b) =>
        b.memesVoisins - a.memesVoisins || a.dist - b.dist || b.hasard - a.hasard);
      const choisi = options[0];
      cellules.add(choisi.cellule);
      if (choisi.dist <= rayonMin || Math.random() < 0.86) piocheAjouter(frontiere, choisi.cellule);
      if (Math.random() < 0.12) piocheAjouter(frontiere, base);
    }
    if (cellules.size < Math.max(24, Math.floor(cible / 3))) return null;
    return lisserCellules(cellules, centre, disponibles);
  }

  function genererEtoile(centre, config, disponibles) {
    const { cible, rayonMin, rayonMax } = config;
    const centreR = ligneDe(centre), centreC = colonneDe(centre);
    const cellules = new Set([centre]);

    // Noyau compact.
    const cibleNoyau = Math.max(20, Math.floor(cible / 3));
    const rayonNoyau = Math.max(2, rayonMin);
    const frontiere = nouvellePioche([centre]);
    let essais = 0;
    while (frontiere.tableau.length > 0 && cellules.size < cibleNoyau && essais < cibleNoyau * 25) {
      essais++;
      const base = piocheTirer(frontiere);
      const options = [];
      for (const v of voisins4(base)) {
        if (cellules.has(v) || !disponibles.has(v)) continue;
        const dist = Math.abs(ligneDe(v) - centreR) + Math.abs(colonneDe(v) - centreC);
        if (dist > rayonNoyau * 3) continue;
        let nVoisins = 0;
        for (const w of voisins4(v)) if (cellules.has(w)) nVoisins++;
        options.push({ nVoisins, dist, hasard: Math.random(), cellule: v });
      }
      if (options.length === 0) {
        piocheRetirer(frontiere, base);
        continue;
      }
      options.sort((a, b) => b.nVoisins - a.nVoisins || a.dist - b.dist || b.hasard - a.hasard);
      const cellule = options[0].cellule;
      cellules.add(cellule);
      piocheAjouter(frontiere, cellule);
      if (Math.random() < 0.25) piocheAjouter(frontiere, base);
    }

    // Bras rayonnants : le tracé s'arrête net sur un obstacle, jamais de
    // fragments de l'autre côté ; épaississement probabiliste, effilé.
    const nbBras = entierAleatoire(5, 8);
    const pinceau = Math.max(1, Math.floor(rayonMin / 2));
    for (let b = 0; b < nbBras; b++) {
      const longueur = entierAleatoire(rayonMax * 2, rayonMax * 4);
      let direction = (2 * Math.PI * b) / nbBras + (Math.random() - 0.5) * 0.44;
      let posR = centreR, posC = centreC;
      for (let pas = 0; pas < longueur; pas++) {
        posR += Math.sin(direction) * (0.8 + Math.random() * 0.6);
        posC += Math.cos(direction) * (0.8 + Math.random() * 0.8);
        direction += (Math.random() - 0.5) * 0.28;
        const rr = Math.round(posR), cc = Math.round(posC);
        if (rr < 0 || rr >= LIGNES || cc < 0 || cc >= COLONNES) break;
        const casesBras = new Set([idx(rr, cc)]);
        if (pas < longueur * 0.18 || Math.random() < 0.35) {
          for (const v of voisins4(idx(rr, cc))) {
            if (Math.random() < 0.55) casesBras.add(v);
          }
        }
        if (pinceau > 1) {
          for (const i of [...casesBras]) {
            if (Math.random() < 0.35) {
              for (const v of voisins4(i)) {
                if (Math.random() < 0.30) casesBras.add(v);
              }
            }
          }
        }
        const casesValides = [...casesBras].filter((i) => disponibles.has(i));
        if (casesValides.length === 0) break;
        for (const i of casesValides) cellules.add(i);
        if (cellules.size >= cible) break;
      }
      if (cellules.size >= cible) break;
    }

    if (cellules.size < Math.max(26, Math.floor(cible / 3))) return null;
    return composanteConnexe(cellules, centre);
  }

  function genererForme(centre, nomTaille, nomForme, disponibles) {
    const config = TAILLES[nomTaille];
    const generateur = nomForme === "etoile" ? genererEtoile : genererBloc;
    if (!disponibles.has(centre)) return null;
    for (let essai = 0; essai < 8; essai++) {
      let cellules = generateur(centre, config, disponibles);
      if (!cellules) continue;
      cellules = new Set([...cellules].filter((i) => disponibles.has(i)));
      cellules.add(centre);
      cellules = composanteConnexe(cellules, centre);
      if (cellules.size >= Math.max(24, Math.floor(config.cible / 4))) return cellules;
    }
    return null;
  }

  // ------------------------------------------------------------------
  // Côte bruitée le long des bords (évite les côtés rectilignes)
  // ------------------------------------------------------------------

  function creerMasqueBords() {
    function profil(longueur) {
      const profondeurs = new Int8Array(longueur);
      let valeur = entierAleatoire(2, 5);
      for (let k = 0; k < longueur; k++) {
        valeur += entierAleatoire(-1, 1);
        if (valeur < 2) valeur = 2;
        if (valeur > 6) valeur = 6;
        profondeurs[k] = valeur;
      }
      return profondeurs;
    }
    const haut = profil(COLONNES), bas = profil(COLONNES);
    const gauche = profil(LIGNES), droite = profil(LIGNES);
    return function masque(i) {
      const r = ligneDe(i), c = colonneDe(i);
      return r < haut[c] || r >= LIGNES - bas[c]
          || c < gauche[r] || c >= COLONNES - droite[r];
    };
  }

  // ------------------------------------------------------------------
  // Le générateur : noyaux au large + accrétion dans les creux (mode mix)
  // ------------------------------------------------------------------

  function tailleInferieure(taille) {
    const position = NOMS_TAILLES.indexOf(taille);
    if (position <= 0) return "petite";
    return NOMS_TAILLES[entierAleatoire(0, position - 1)];
  }

  function genererCarteAleatoire(nombreTerritoires, nombreContinents) {
    nombreTerritoires = Math.max(2, Math.min(300, Math.floor(nombreTerritoires) || 0));
    nombreContinents = Math.max(1, Math.min(nombreTerritoires,
      Math.min(50, Math.floor(nombreContinents) || 1)));

    const grille = new Int16Array(LIGNES * COLONNES).fill(VIDE);
    let prochainId = 0;
    let ajoutes = 0;

    const masqueBords = creerMasqueBords();
    const libres = new Set();
    for (let i = 0; i < grille.length; i++) {
      if (!masqueBords(i)) libres.add(i);
    }

    const frontiere = nouvellePioche();
    function etendreFrontiere(cellules) {
      for (const i of cellules) {
        for (const v of voisins4Toriques(i)) {
          if (grille[v] === VIDE) piocheAjouter(frontiere, v);
        }
      }
    }

    const poseesCettePasse = [];
    const ensembleParTerritoire = new Map(); // tid -> { forme, taille } du noyau

    function poserTerritoire(centre, nomTaille, nomForme) {
      const forme = genererForme(centre, nomTaille, nomForme, libres);
      if (!forme || forme.size < 0.6 * TAILLES[nomTaille].cible) return null;
      const tid = prochainId++;
      for (const i of forme) {
        grille[i] = tid;
        libres.delete(i);
        piocheRetirer(frontiere, i);
        poseesCettePasse.push(i);
      }
      etendreFrontiere(forme);
      ajoutes++;
      return tid;
    }

    // Champ de distances à la terre (BFS multi-sources, torique) : sert à
    // poser les noyaux « au large », loin de toutes les terres.
    function champDistances() {
      const distances = new Int32Array(grille.length).fill(-1);
      const file = [];
      for (let i = 0; i < grille.length; i++) {
        if (grille[i] >= 0) {
          distances[i] = 0;
          file.push(i);
        }
      }
      if (file.length === 0) return null;
      let tete = 0;
      while (tete < file.length) {
        const i = file[tete++];
        for (const v of voisins4Toriques(i)) {
          if (distances[v] === -1) {
            distances[v] = distances[i] + 1;
            file.push(v);
          }
        }
      }
      return distances;
    }

    function celluleAuLarge() {
      const distances = champDistances();
      if (!distances) return choixDansEnsemble(libres);
      let maximum = 0;
      for (const i of libres) if (distances[i] > maximum) maximum = distances[i];
      if (maximum <= 1) return choixDansEnsemble(libres);
      const seuil = Math.max(1, Math.floor(maximum * 0.8));
      const candidates = [];
      for (const i of libres) if (distances[i] >= seuil) candidates.push(i);
      return candidates[Math.floor(Math.random() * candidates.length)];
    }

    // Règle « mix » : un noyau n'est jamais petit ; autour d'un noyau bloc,
    // des blocs ou étoiles de taille inférieure ; autour d'un noyau étoile,
    // des blocs de la même taille.
    function parametresSatellite(ensemble) {
      if (!ensemble) {
        return {
          nomTaille: NOMS_TAILLES[entierAleatoire(0, NOMS_TAILLES.length - 1)],
          nomForme: Math.random() < 0.5 ? "bloc" : "etoile",
        };
      }
      if (ensemble.forme === "etoile") {
        return { nomTaille: ensemble.taille, nomForme: "bloc" };
      }
      return {
        nomTaille: tailleInferieure(ensemble.taille),
        nomForme: Math.random() < 0.5 ? "bloc" : "etoile",
      };
    }

    function ensemblePour(centre) {
      for (const v of voisins4Toriques(centre)) {
        const tid = grille[v];
        if (tid >= 0 && ensembleParTerritoire.has(tid)) {
          return ensembleParTerritoire.get(tid);
        }
      }
      return null;
    }

    function poserNoyaux() {
      let echecs = 0;
      while (ajoutes < Math.min(nombreContinents, nombreTerritoires) && echecs < 50) {
        if (libres.size < TAILLES.petite.cible) break;
        const nomTaille = NOMS_TAILLES[entierAleatoire(1, NOMS_TAILLES.length - 1)];
        const nomForme = Math.random() < 0.5 ? "bloc" : "etoile";
        const tid = poserTerritoire(celluleAuLarge(), nomTaille, nomForme);
        if (tid !== null) {
          ensembleParTerritoire.set(tid, { forme: nomForme, taille: nomTaille });
          echecs = 0;
        } else {
          echecs++;
        }
      }
    }

    // Score d'encaissement : nombre de cases occupées autour (fenêtre 9×9,
    // torique). Semer dans les creux garde les continents compacts.
    const RAYON_CREUX = 4;
    function scoreCreux(i) {
      const r = ligneDe(i), c = colonneDe(i);
      let score = 0;
      for (let dr = -RAYON_CREUX; dr <= RAYON_CREUX; dr++) {
        for (let dc = -RAYON_CREUX; dc <= RAYON_CREUX; dc++) {
          const nr = moduloPositif(r + dr, LIGNES);
          const nc = moduloPositif(c + dc, COLONNES);
          if (grille[idx(nr, nc)] >= 0) score++;
        }
      }
      return score;
    }

    function croissance() {
      let echecs = 0;
      while (ajoutes < nombreTerritoires && echecs < 80) {
        const candidats = [];
        let tirages = 0;
        while (candidats.length < 15 && tirages < 45 && frontiere.tableau.length > 0) {
          tirages++;
          const candidat = piocheTirer(frontiere);
          if (!libres.has(candidat)) {
            piocheRetirer(frontiere, candidat);
            continue;
          }
          if (!candidats.includes(candidat)) candidats.push(candidat);
        }
        if (candidats.length === 0) break;
        let centre = candidats[0];
        let meilleurScore = -1;
        for (const candidat of candidats) {
          const score = scoreCreux(candidat) + Math.random();
          if (score > meilleurScore) {
            meilleurScore = score;
            centre = candidat;
          }
        }
        const ensemble = ensemblePour(centre);
        const { nomTaille, nomForme } = parametresSatellite(ensemble);
        const tid = poserTerritoire(centre, nomTaille, nomForme);
        if (tid !== null) {
          if (ensemble) ensembleParTerritoire.set(tid, ensemble);
          echecs = 0;
        } else {
          piocheRetirer(frontiere, centre);
          echecs++;
        }
      }
    }

    poserNoyaux();
    croissance();

    // Repli « plus le choix » : on autorise les abords des bords.
    if (ajoutes < nombreTerritoires) {
      for (let i = 0; i < grille.length; i++) {
        if (grille[i] === VIDE && masqueBords(i)) libres.add(i);
      }
      etendreFrontiere(poseesCettePasse);
      poserNoyaux();
      croissance();
    }

    if (ajoutes === 0) return null;

    // Payload x45 : cellules et voisins seront recalculés par le moteur
    // depuis la grille (adjacence torique des cartes "custom").
    const grid_territory = [];
    for (let r = 0; r < LIGNES; r++) {
      const ligne = new Array(COLONNES);
      for (let c = 0; c < COLONNES; c++) ligne[c] = grille[idx(r, c)];
      grid_territory.push(ligne);
    }
    const territories = [];
    for (let tid = 0; tid < prochainId; tid++) {
      territories.push({
        id: tid,
        name: `T${tid + 1}`,
        cells: [],
        neighbors: [],
        continent: null,
        reinforcement_bonus: 1,
      });
    }
    return {
      schema_version: 13,
      kind: "map",
      map_mode: "custom",
      rows: LIGNES,
      cols: COLONNES,
      grid_territory,
      territories,
      terre_links: [],
      terre_link_points: {},
      bridge_links: [],
      fragile_bridge_links: [],
      bridge_link_points: {},
    };
  }

  return { genererCarteAleatoire };
})();
