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

#### 1c.2 — Actions d'achat ⬜

Migrer la boutique (mercenaires, bâtiments, corruption, alliances, dons,
ventes, ponts, manipulation ONU, changement de capitale…) vers des actions
`acheter` validées par le moteur. L'IA de combat (choix de cibles) suivra
pour que le serveur puisse jouer les tours IA complets.

### Étape 2 — Serveur (FastAPI + WebSockets, lobby, persistance) ⬜
### Étape 3 — Client web (canvas, écran par écran) ⬜
### Étape 4 — Déploiement gratuit (Render/Fly.io ; réveil ~30 s, état en base) ⬜
