# Migration vers la version en ligne — plan et suivi

Objectif final : jouer au jeu dans le navigateur, chacun depuis son ordinateur,
en voyant en direct les actions du joueur actif. Architecture cible :

- **moteur/** — règles et état du jeu en Python pur (aucun pygame). C'est lui
  que le serveur fera tourner. *(en cours)*
- **serveur** — FastAPI + WebSockets : lobby, parties, diffusion des actions. *(à faire)*
- **client web** — carte en canvas + panneaux, dans le navigateur. *(à faire)*
- **x45.py** — le jeu pygame actuel, qui reste intact et jouable pendant toute
  la migration.

## Décisions prises

- Le **format JSON des sauvegardes** (`parties_en_cours/*.json`, schéma v13)
  est le format canonique de l'état : le moteur lit et écrit exactement ce
  format. Une partie sauvegardée par x45 est chargeable par le moteur et
  inversement.
- Identifiants de code en anglais (comme x45), commentaires et documents en
  français.
- Tests avec `unittest` (pytest n'est pas installé sur la machine).

## État d'avancement

### Étape 1a — État sérialisable ✅ (2026-07-22)

`moteur/etat.py` : `GameState` + `Territory`, dataclasses pures.
- `from_payload` reflète `apply_saved_map` + `apply_saved_game_state` (x45),
  partie chargement uniquement ; comme x45, les mécaniques abandonnées
  (vassaux, guerre froide, colonisation, diplomatie nationale spéciale) sont
  ignorées au chargement et émises vides à la sauvegarde.
- `to_payload` reflète `build_map_payload` + `build_game_payload`, y compris
  les clés héritées (`industry_*`).
- Géométrie recalculée depuis la grille comme dans x45
  (`rebuild_cells_from_grid`, `recompute_neighbors_from_grid`, liens terre et
  ponts).

Tests : `tests/test_etat.py` — 5 tests verts sur les 23 vraies sauvegardes
(chargement, point fixe de la sérialisation, complétude des clés,
conservation de l'état, cohérence géométrique).

Lancement : `python -m unittest discover -s tests -v` depuis `Jeux Strat`.

**Parité vérifiée contre x45** : totale depuis l'étape 1b.1 — voir
`tests/test_parite_x45.py`.

### Étape 1b — Règles dans le moteur 🔶 (en cours)

Migrer les règles pures de x45 vers `moteur/regles.py`, x45 déléguant au
moteur au fur et à mesure (approche strangler).

#### 1b.1 — Sanitisations de chargement ✅ (2026-07-22)

`moteur/regles.py` : toutes les sanitisations que x45 exécute au chargement
d'une sauvegarde, portées fidèlement en fonctions opérant sur `GameState` :
`sanitize_economy_state` (et sa fermeture : capitales, territoires soumis,
religion, centres culturels des CC, exclusivité du Palais du Pacte d'Or,
villes commerciales détruites → spawn en attente + événement majeur),
`sanitize_player_capitals`, `enforce_golden_territory_onu_immunity` (rng
injectable), `refresh_last_stand_bonus_state`,
`snapshot_tax_haven_turn_start_territory_counts`, `record_replay_snapshot`
(+ `build_replay_snapshot`/signature), `record_major_event`.

Point d'entrée : `sanitize_after_load(state, rng, phase_before_load)` —
miroir exact de la fin de `apply_saved_game_state` (x45:1506-1518), y compris
la mise de côté du statut paradis fiscal pendant `sanitize_economy_state`
puis sa restauration. À noter : `moteur/regles.get_commercial_city_capital_id`
reprend la version *avec cache* de x45 (celle de `etat.py` reste en lecture
seule pour la sérialisation).

**Parité totale vérifiée** : `tests/test_parite_x45.py` charge chaque
sauvegarde des deux côtés (x45 headless SDL dummy + moteur, même germe
aléatoire) et compare les payloads clé par clé — identiques sur les 23
sauvegardes. Les clés que x45 émet comme `list(set)` sans ordre (et que le
moteur trie) sont comparées après tri, idem pour les listes d'alliances.

#### 1b.2 — Règles de jeu ✅ (2026-07-22)

Toutes les cibles de l'étape sont dans `moteur/regles.py`, et x45 leur
délègue (strangler, par duck typing : les fonctions du moteur opèrent aussi
sur `GraphicalGame`) :

- **Revenus** : `calculate_player_income` (+ territoire, tribut des
  territoires soumis, bonus religieux, mines, nations), `collect_income_for_player`.
- **Renforts** : `grant_reinforcements` → `ReinforcementReport(kind, message)` ;
  x45 choisit la durée d'affichage selon `kind`. Plafonds, bonus +3/+5,
  bonus religieux, progression IA, priorité forteresse, conversion
  universitaire.
- **Déplacements** : `can_move_between`, `get_end_turn_move_limit`,
  `move_one_regiment` → `(ok, code)` ; messages et fin de tour automatique
  restent dans x45 (règles d'interface).
- **Victoire** : `evaluate_winner` → `(vainqueur, raison)` ; lieux saints,
  conquête totale, 3/4, territoires dorés, duel final. Le corps de
  `maybe_start_final_duel` n'est pas porté (inatteignable, unions abandonnées).
- **Combat** : `resolve_attack_once` → `AttackResult` (dés, conquête,
  messages spéciaux, rupture d'alliance, élimination) et toute sa fermeture :
  alliances (`is_attack_blocked_by_alliance`, `cleanup_expired_alliances`,
  `break_alliance_due_to_human_attack`), nations (qualification, perte de
  statut, `refresh_nation_states`), soumissions ONU, captures spéciales,
  culture/science, paradis fiscaux (mutations), éliminations, événements
  punitifs (annexion de sanctuaire, chaos mondial).

Points d'architecture :
- l'aléatoire est injectable partout (`rng=random` par défaut) ;
- la décision humaine « soumettre ou annexer ? » est un callback
  `submit_decider` : boîte Tkinter dans x45, question au client dans la
  future version web ;
- x45 garde encore en propre quelques assistants à usage UI (aperçus,
  boutique) qui dupliquent des règles du moteur — à déléguer au fil de l'eau.

**Parité vérifiée contre le x45 d'origine** (avant délégation) :
`tests/test_parite_regles.py` (revenus par joueur, limites de déplacement,
connectivité, vainqueur+raison, renforts avec même germe, état complet) et
`tests/test_parite_combat.py` (cibles d'attaque valides sur toutes les paires
voisines, assaut complet passe par passe avec dés/messages/état identiques).
Les 8 tests restent verts après délégation.

### Étape 1c — Boucle de tour pilotée par actions 🔶 (en cours)

#### 1c.1 — Cœur de la boucle et vocabulaire d'actions ✅ (2026-07-22)

**`moteur/actions.py`** (nouveau) :
- `begin_player_turn` / `advance_turn` — miroirs purs de
  `begin_player_turn` / `complete_turn` de x45, qui retournent des rapports
  structurés (`BeginTurnReport`, `TurnAdvanceReport`) ; l'affichage reste à
  l'appelant (x45 aujourd'hui, le serveur demain).
- `apply_action(state, action, ...)` — le point d'entrée que le serveur
  exposera : actions `attaquer`, `assaut_total`, `deplacer`,
  `terminer_attaque` (humain → phase d'achats, IA → déplacements),
  `terminer_achats`, `fin_de_tour` ; validation de phase et refus typés
  (`phase_invalide`, `territoire_invalide`, `attaque_invalide`, codes de
  refus de déplacement).

**`moteur/regles.py`** s'est enrichi de toute la fermeture du tour :
événements ONU (apparition/libération/intégration/instabilité), sédition,
chaos, événements d'empire (trahison/révolte/révolution), marché, ressources
programmées, ponts (géométrie en cellules, dimensions de cellule en pixels
injectées — héritage de l'affichage x45), expansion religieuse, science et
vieillissement, expansion culturelle, apparition des cités commerçantes, et
**l'IA économique complète** (achats nations et CC, merveilles, changement de
capitale, corruption CC). Découverte notable : le comportement des IA
« variable » est retiré au sort à chaque début de tour dans
`reset_ai_turn_state` (code d'interface) — c'est une règle, elle est
maintenant dans `regles.prepare_ai_behavior_for_turn`.

x45 délègue : `complete_turn`, `begin_player_turn`, tous les événements de
tour, les constructeurs (`add_temple`, `add_university`,
`add_cultural_center`, `add_industrial_structure`, `build_wonder`…) et l'IA
économique. Écarts cosmétiques assumés (état du jeu identique) : durées
d'affichage des messages d'événements d'empire, sélection UI non mise sur la
cible d'une mobilisation IA.

**Parité vérifiée** : `tests/test_parite_tour.py` simule 6 fins de tour
complètes par sauvegarde (même germe) — joueur courant, tour, phase et état
sérialisé identiques entre le chemin x45 et le chemin pur ; le vocabulaire
d'actions est exercé (transitions, refus, attaque, déplacement).

**Référence d'origine** : `x45-original.py` est la copie du jeu d'avant
toute délégation (aucune référence à `moteur/`). `tests/test_parite_original.py`
compare le moteur pur à cette copie — chargement, assauts complets et six
fins de tour par sauvegarde — et confirme la fidélité de la transcription.
Le projet est désormais **sous git local** : un commit par étape validée.

#### 1c.2 — Actions d'achat ✅ (2026-07-22)

**`moteur/achats.py`** (nouveau) : toute la boutique en fonctions pures
`(state, …) -> AchatResult(ok, message)`, mêmes validations, coûts et textes
que x45 : mercenaires, vente/don de territoire, don d'argent, forteresse
(+destruction), usine/aéroport/port, temple, centre culturel, université
(+destruction), merveille, changement de capitale, corruption, révolte,
ponts (+destruction), alliance défensive et offensive, figement/libération
ONU, association paradis fiscal (avec ses variantes intégration scientifique
et intégration PF). Les flux « en deux clics » de x45 deviennent des
paramètres explicites (source + bénéficiaire, deux extrémités du pont…).

`apply_action` accepte `{"type": "acheter", "achat": "...", ...}` en phase
d'achats (liste `ACHATS` dans `moteur/actions.py`), avec codes de refus
typés et le message boutique dans le résultat.

x45 délègue les 24 `execute_shop_*` (les clics, sélections en attente et
durées d'affichage restent côté interface).

**Parité vérifiée contre x45-original** : `tests/test_parite_achats.py`
rejoue sur chaque sauvegarde une séquence d'achats déterministe (trésor et
science boostés à l'identique des deux côtés) et compare message par message
et état par état — succès comme refus. Vert sur les 23 sauvegardes avant et
après délégation.

#### 1c.3 — IA de combat ✅ (2026-07-22)

**`moteur/ia.py`** (nouveau) : décisions des IA — `find_ai_attack` +
`ai_attack_score` (profils very_aggressive/aggressive/defensive/standard,
attaque totale ou duel, règle des 40 régiments contre les sanctuaires),
`compute_ai_move_target`/`compute_ai_move_sources`/`execute_ai_move_phase`
(concentration de fin de tour vers la frontière), `get_ai_behavior`,
`get_offensive_alliance_target_for_ai`, `shortest_owned_path`.

**`moteur/actions.py`** : `play_ai_turn(state, …) -> AiTurnReport` joue le
tour IA complet (attaques, déplacement, fin de tour) — c'est l'appel que
fera le serveur pour chaque tour IA. x45 garde sa machine à états
`process_ai_turn` (rythme d'affichage) mais délègue toutes les décisions.

**Parité vérifiée contre x45-original** : `tests/test_parite_ia.py` force le
même joueur IA des deux côtés et joue le tour entier avec le même germe —
états identiques sur les 23 sauvegardes. Et la preuve d'autonomie :
`test_le_moteur_joue_seul` enchaîne 60 tours complets (IA via
`play_ai_turn`, humains via le vocabulaire d'actions) sans x45 ni pygame.

**L'étape 1 est terminée : le moteur est complet et autonome.**

### Étape 2 — Serveur (FastAPI + WebSockets, lobby, persistance) ✅ (2026-07-23)

#### 2a — Cœur du serveur ✅ (2026-07-22)

**`serveur/partie.py`** (pur, sans FastAPI) : `SessionPartie` enveloppe un
`GameState` — chargement d'une sauvegarde (+ `sanitize_after_load`),
arbitrage des droits (tour du joueur, siège humain), application des actions
via `apply_action`, enchaînement automatique des tours IA jusqu'au prochain
humain (`play_ai_turn`), état réseau allégé (sans `replay_history`, ~1 Mo
dans les sauvegardes ; clé `phase` ajoutée, absente du format canonique),
sauvegarde au format v13. `GestionnaireParties` : catalogue des sauvegardes
+ parties ouvertes. Dimensions logiques : `1200/cols × 620/rows` (repère
pixel de x45, cohérent avec la géométrie des ponts sauvegardée).

**`serveur/app.py`** : application FastAPI (`creer_app(dossier)` injectable
pour les tests). REST : `GET /api/sauvegardes`, `GET|POST /api/parties`,
`GET /api/parties/{id}/etat`, `POST /api/parties/{id}/sauvegarder`.
WebSocket `/ws/parties/{id}` : `rejoindre` (siège ou spectateur, présence
diffusée), `action` (vocabulaire du moteur, résultat + état diffusés à tous,
refus à l'émetteur seul), `decision_soumission`. La question « soumettre ou
annexer ? » (`submit_decider`) traverse le pont thread→asyncio : l'action
tourne dans un thread, la question part au client attaquant, sans réponse
sous 120 s → annexion (comme x45 sans Tkinter). Protocole détaillé dans la
docstring de `serveur/app.py`.

Tests : `tests/test_serveur.py` — 10 tests (session pure : arbitrage,
tour complet + tours IA, aller-retour de sauvegarde ; couche web via
TestClient : REST, WebSocket jouer/spectateur/sièges, sauvegarde API).
Lancement manuel : `python -m uvicorn serveur.app:app --app-dir "Jeux Strat"`.

#### 2b — Nouvelle partie côté serveur ✅ (2026-07-23)

**`moteur/mise_en_place.py`** (nouveau) : la mise en place de
`start_game_session` (x45) portée en fonctions pures — configuration des
joueurs (miroir de `setup_players`, sans les questions), profils IA, cité
commerçante initiale, distribution des territoires et armées (modes
aléatoire **et Tribus**, BFS contigu), capitales initiales, territoires
bonus +3 (avec le double appel de x45, fidélité RNG oblige), territoires
dorés (essais à distance décroissante), sanctuaires ONU, remise à zéro de
l'économie (champs du moteur uniquement — les mécaniques abandonnées
n'existent plus dans `GameState`), structures initiales pondérées.
Point d'entrée : `nouvelle_partie(carte_payload, num_players,
ai_player_count, difficulty_level, tribes_mode, rng)` ; l'appelant enchaîne
sur `actions.begin_player_turn`. `GameState.from_map_payload` charge une
carte seule. La **génération aléatoire de cartes** (`generate_grid_map`,
masques de terre) n'est pas portée : le serveur crée depuis les 42 cartes
de `cartes_sauvegardees/`.

**Serveur** : `GET /api/cartes`, et `POST /api/parties` accepte
`{"carte": "Alpha.json", "joueurs": 4, "ia": 2, "mode": "normal",
"tribus": false}` (`SessionPartie.nouvelle`, `GestionnaireParties.creer`).

**Parité vérifiée contre x45-original** :
`tests/test_parite_mise_en_place.py` rejoue la séquence complète des deux
côtés (6 cartes représentatives × 3 configurations, même germe) — états
sérialisés identiques, y compris mode Tribus et premier début de tour ;
plus un test d'autonomie (la partie neuve se joue seule au moteur pur).
`tests/test_serveur.py` couvre le parcours serveur (12 tests).

#### 2c — Lobby complet ✅ (2026-07-23)

**`serveur/joueurs.py`** (nouveau) : `RegistreJoueurs` — identités
persistantes. `POST /api/joueurs {"nom"}` crée une identité et retourne un
**jeton secret** que le client conserve (localStorage) ; nom public unique
(insensible à la casse, 24 caractères max), persistance dans un fichier JSON
(`joueurs.json`, injectable pour les tests) relu au démarrage.

**Sièges réservés par identité** (`SessionPartie.reserver_siege` /
`liberer_siege` / `siege_de`) : le siège appartient au jeton, pas à la
connexion — il **survit à la déconnexion**. `rejoindre` avec le seul jeton
retrouve le siège (reconnexion) ; une identité = un siège et une connexion
(la connexion fantôme du même jeton est fermée, code 4000). `sieges()`
expose le nom du réservataire, le lobby l'affiche via `resume()`.

**Protocole WS enrichi** : `rejoindre {jeton, joueur?}` (sans jeton :
spectateur anonyme, sans droit de siège ni de chat), `quitter_siege`,
`chat {texte}` (diffusé avec nom + siège, 500 caractères max) ; message
`presence` détaillé : sièges avec `nom`/`connecte`, liste des spectateurs.

Tests : `tests/test_serveur.py` passe à 18 tests — registre (unicité,
persistance), réservations (reconnexion, refus typés), et côté WS :
reconnexion après coupure, remplacement de connexion, chat, quitter le
siège, refus `identite_requise`/`jeton_inconnu`.
**L'étape 2 est terminée : le serveur couvre lobby, parties, jeu en direct
et identités.**

### Étape 3 — Client web (canvas, écran par écran) 🔶 (en cours)

#### 3a — Lobby et vue de partie en direct ✅ (2026-07-23)

**`client/`** (nouveau : `index.html`, `style.css`, `app.js`) — vanilla JS
sans build, servi en statique par FastAPI à la racine `/` (monté après les
routes API). Trois écrans :
- **Identité** : nom → `POST /api/joueurs`, jeton conservé en localStorage.
- **Lobby** : parties ouvertes (avec occupants), nouvelle partie (42 cartes,
  joueurs/IA/mode/tribus), reprise d'une des sauvegardes.
- **Partie** : carte canvas 1200×620 **fidèle à x45** (mêmes couleurs et
  règles de rendu que `draw_territories`/`draw_bridges` : eau, boost du
  joueur au trait, bordures jaunes/violettes/blanches, boîtes de régiments,
  étoiles capitales, disques dorés, pastilles bonus, ponts (fragiles en
  pointillés), liens terre, centre circulaire en carte "custom") ; panneau
  sièges (s'asseoir/quitter), spectateurs, chat, journal, détail du
  territoire cliqué ; bandeau victoire ; question soumission via confirm().
  L'id de partie vit dans `location.hash` → un rechargement se reconnecte
  et retrouve le siège (jeton). Reconnexion auto après coupure (2 s).

**Serveur** : montage `StaticFiles`, et nouveau message WS
`prendre_siege {joueur}` (s'asseoir après avoir rejoint, sans se
reconnecter) avec accusé `siege_pris`.

Tests : `tests/test_serveur.py` → 20 tests (statique servi, prendre_siege).
Parcours complet vérifié dans le navigateur (inscription → création →
carte rendue → siège → chat → rechargement/reconnexion), console et
logs serveur sans erreur. Lancement : préviseur `serveur-jeu`
(`.claude/launch.json`) ou
`python -m uvicorn serveur.app:app --app-dir "Jeux Strat"`.

#### 3b — Jouer dans le navigateur ⬜ (attaque, déplacements, fins de
phase — sélection source/cible sur la carte)
#### 3c — Boutique et panneaux détaillés ⬜ (achats, aperçus revenus,
événements majeurs, religions/science/culture)
### Étape 4 — Déploiement gratuit (Render/Fly.io ; réveil ~30 s, état en base) ⬜
