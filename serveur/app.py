"""Application FastAPI du jeu : REST pour le lobby, WebSockets pour jouer.

REST :
- ``POST /api/joueurs``                — ``{"nom": "Alice"}`` cree une
  identite persistante et retourne ``{"jeton": "...", "nom": "Alice"}`` ; le
  client garde le jeton (localStorage) pour rejoindre et se reconnecter.
- ``GET  /api/sauvegardes``            — sauvegardes chargeables.
- ``GET  /api/cartes``                 — cartes pour une partie neuve.
- ``POST /api/cartes``                 — importe une carte : ``{"nom":
  "MaCarte.json", "carte": {...}, "remplacer": false}`` ; 409 si le nom
  existe deja et que ``remplacer`` est faux.
- ``GET  /api/parties``                — parties ouvertes (resume + sieges).
- ``POST /api/parties``                — ouvre une partie :
  ``{"sauvegarde": "partie_001.json"}`` pour recharger une sauvegarde, ou
  ``{"carte": "Alpha.json", "joueurs": 4, "ia": 2, "mode": "normal",
  "tribus": false}`` pour une partie neuve (mise en place du moteur) ;
  ``seed`` optionnel pour des tests reproductibles.
- ``GET  /api/parties/{id}/etat``      — etat complet (sans historique replay).
- ``GET  /api/parties/{id}/replay``    — l'historique replay (a la demande).
- ``GET  /api/parties/{id}/bilans``    — etat des lieux par joueur actif
  (amenagements, bonus, conditions de nation, progression de victoire).
- ``POST /api/parties/{id}/sauvegarder`` — ``{"fichier": "..."}`` optionnel
  (par defaut : le fichier d'origine).

WebSocket ``/ws/parties/{id}`` — messages JSON :

Client vers serveur :
- ``{"type": "rejoindre", "jeton": "...", "joueur": 2}`` — reserve le siege
  du joueur 2 pour cette identite. Le siege reste reserve apres une
  deconnexion : ``{"type": "rejoindre", "jeton": "..."}`` suffit ensuite pour
  le retrouver (reconnexion). Sans jeton du tout : spectateur anonyme. Si la
  meme identite etait deja connectee, l'ancienne connexion est fermee (4000).
- ``{"type": "prendre_siege", "joueur": 2}`` — prend un siege apres avoir
  rejoint (spectateur identifie qui s'assoit).
- ``{"type": "quitter_siege"}`` — libere son siege (on reste spectateur).
- ``{"type": "mode_auto", "actif": true}`` — confie son siege a l'IA (pause,
  abandon temporaire...) ; ``false`` pour reprendre la main, y compris au
  milieu d'un tour que l'IA etait en train de jouer. Le siege reste reserve :
  personne d'autre ne peut le prendre, et on ne peut pas basculer un autre
  siege (IA de base ou humain).
- ``{"type": "action", "action": {...}}`` — vocabulaire de
  ``moteur.actions.apply_action`` (attaquer, deplacer, acheter...).
- ``{"type": "decision_soumission", "reponse": true}`` — reponse a une
  ``question_soumission``.
- ``{"type": "chat", "texte": "..."}`` — message aux presents (identite
  requise ; tronque a 500 caracteres).

Serveur vers client :
- ``{"type": "bienvenue", "joueur": 2|null, "nom": "...", "etat": {...},
     "sieges": [...]}``
- ``{"type": "presence", "sieges": [{"joueur", "ia", "actif", "nom",
     "connecte"}...], "spectateurs": [noms]}`` — a chaque arrivee/depart.
- ``{"type": "resultat", "joueur": n, "action": {...}, "resultat": {...},
     "etat": {...}}`` — diffuse a tous apres chaque action acceptee. Les
  tours IA sont diffuses de la meme facon mais **un par un** (cadence
  ``DELAI_TOUR_IA_S``), avec ``action: null`` et le rapport du tour dans
  ``resultat.rapports_ia`` : tout le monde voit la partie avancer IA par IA.
- ``{"type": "pas_ia", "joueur": n, "pas": {"src_id", "dst_id", "result":
     {att_text, def_text, conquered, ...}, "territoires": [...]}}`` — chaque
  passe d'attaque d'un tour IA, a la cadence ``DELAI_PAS_IA_S`` (la vitesse
  « IA rapide » de x45) ; ``territoires`` porte l'etat a jour des deux
  territoires touches, l'etat complet arrivant avec le ``resultat`` final.
- ``{"type": "refus", "code": "pas_votre_tour"|...}`` — a l'emetteur seul.
- ``{"type": "question_soumission", "territoire": id, "nom": "...",
     "regiments_vaincus": n}`` — au joueur attaquant seul, pendant une
  attaque de nation ; sans reponse sous ``DELAI_DECISION_S``, annexion.
- ``{"type": "chat", "joueur": n|null, "nom": "...", "texte": "..."}``
- ``{"type": "siege_pris", "joueur": n}`` / ``{"type": "siege_quitte"}`` —
  accuses de reception de ``prendre_siege`` / ``quitter_siege``.
- ``{"type": "mode_auto", "joueur": n, "actif": bool, "nom": "..."}`` — a
  tous : le siege ``n`` vient de passer a l'IA (ou de revenir a son humain).
- ``{"type": "victoire", "vainqueur": n, "raison": "..."}``

Le client web (``client/``) est servi en statique a la racine ``/``.

Le traitement d'une action tourne dans un thread (le moteur est synchrone) ;
la boucle de reception continue de lire pendant ce temps, ce qui permet a la
``decision_soumission`` d'arriver au milieu d'une attaque.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .partie import (
    GestionnaireParties, MAX_CONSECUTIVE_AI_TURNS, PREFIXE_SAUVEGARDE_AUTO,
    ResultatAction, SessionPartie, to_jsonable,
)
from .stockage import nom_est_valide

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_PARTIES = RACINE / "parties_en_cours"
DOSSIER_CARTES = RACINE / "cartes_sauvegardees"
DOSSIER_CLIENT = RACINE / "client"

# Temps laisse a un humain pour repondre "soumettre ou annexer ?" avant que
# le serveur tranche (annexion, comme x45 sans Tkinter).
DELAI_DECISION_S = 120.0

# Pause entre deux tours IA diffuses : les joueurs voient la partie avancer
# IA par IA sur la carte au lieu de recevoir tout le bloc d'un coup.
DELAI_TOUR_IA_S = 1.0

# Pause entre deux passes d'attaque d'un meme tour IA — la vitesse
# « IA rapide » de x45 (AI_FAST_ACTION_DELAY_MS = 260 ms).
DELAI_PAS_IA_S = 0.26


class ConnexionClient:
    """Un client WebSocket relie a une partie (siege humain ou spectateur)."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.jeton: Optional[str] = None
        self.nom: Optional[str] = None
        self.joueur: Optional[int] = None
        self.action_en_cours = False
        self.decision_future: Optional[asyncio.Future] = None

    async def envoyer(self, message: Dict[str, Any]) -> None:
        await self.websocket.send_json(message)


class SallePartie:
    """Les clients connectes a une meme partie + la diffusion."""

    def __init__(self, session: SessionPartie, delai_tour_ia: float = DELAI_TOUR_IA_S,
                 delai_pas_ia: float = DELAI_PAS_IA_S) -> None:
        self.session = session
        self.connexions: list[ConnexionClient] = []
        self.delai_tour_ia = delai_tour_ia
        self.delai_pas_ia = delai_pas_ia
        self._tache_ia: Optional[asyncio.Task] = None

    async def sauvegarder_auto(self) -> None:
        """Sauvegarde de securite apres chaque coup joue (jamais bloquante)."""
        try:
            await asyncio.to_thread(self.session.sauvegarder_auto)
        except Exception:
            logging.exception(
                "Sauvegarde automatique impossible (partie %s)", self.session.id,
            )

    def lancer_tours_ia(self) -> None:
        """Demarre (au besoin) la boucle qui joue et diffuse les tours IA.

        Idempotent : si la boucle tourne deja, ne fait rien. Elle s'arrete
        d'elle-meme quand c'est a un humain de jouer, a la victoire, ou
        quand plus personne n'est connecte (elle repartira a la prochaine
        connexion ou action).
        """
        if self._tache_ia is not None and not self._tache_ia.done():
            return
        if not self.session.tour_ia_en_attente():
            return
        self._tache_ia = asyncio.create_task(self._boucle_ia())

    async def _boucle_ia(self) -> None:
        for _ in range(MAX_CONSECUTIVE_AI_TURNS):
            if not self.connexions:
                break
            joueur_ia = await asyncio.to_thread(self.session.demarrer_tour_ia)
            if joueur_ia is None:
                break
            # Le tour se deroule passe d'attaque par passe d'attaque, chaque
            # passe diffusee avec ses des et les territoires touches ; le
            # rapport final (deplacements, fin de tour) porte l'etat complet.
            resultat = None
            while resultat is None:
                pas, resultat = await asyncio.to_thread(self.session.pas_tour_ia)
                if pas is not None:
                    await self.diffuser({"type": "pas_ia", "joueur": joueur_ia, "pas": pas})
                    if self.delai_pas_ia > 0:
                        await asyncio.sleep(self.delai_pas_ia)
            await self.diffuser_resultat(joueur_ia, None, resultat)
            await self.sauvegarder_auto()
            if resultat.winner is not None:
                break
            if self.delai_tour_ia > 0:
                await asyncio.sleep(self.delai_tour_ia)

    def message_presence(self) -> Dict[str, Any]:
        """Les sieges (reservataire, connecte ou non) et les spectateurs."""
        connectes = {c.joueur for c in self.connexions if c.joueur is not None}
        return {
            "type": "presence",
            "sieges": [
                {**siege, "connecte": siege["joueur"] in connectes}
                for siege in self.session.sieges()
            ],
            "spectateurs": [c.nom for c in self.connexions if c.joueur is None],
        }

    async def diffuser(self, message: Dict[str, Any]) -> None:
        for connexion in list(self.connexions):
            try:
                await connexion.envoyer(message)
            except Exception:
                # Le client parti sera retire par sa propre boucle.
                pass

    async def diffuser_presence(self) -> None:
        await self.diffuser(self.message_presence())

    async def diffuser_resultat(
        self, joueur: int, action: Optional[Dict[str, Any]], resultat: ResultatAction,
    ) -> None:
        await self.diffuser({
            "type": "resultat",
            "joueur": joueur,
            "action": action,
            "resultat": to_jsonable(resultat),
            "etat": self.session.etat_reseau(),
        })
        if resultat.winner is not None:
            await self.diffuser({
                "type": "victoire",
                "vainqueur": resultat.winner,
                "raison": resultat.winner_reason,
            })


def creer_app(dossier_parties: Optional[Path] = None,
              dossier_cartes: Optional[Path] = None,
              fichier_joueurs: Optional[Path] = None,
              delai_tour_ia: float = DELAI_TOUR_IA_S,
              delai_pas_ia: float = DELAI_PAS_IA_S,
              database_url: Optional[str] = None,
              sauvegarde_auto: bool = True) -> FastAPI:
    """Construit l'application (dossiers, registre, cadence et base injectables).

    ``database_url`` (en production : la variable d'environnement
    ``DATABASE_URL``) branche les ecritures — sauvegardes, cartes importees,
    registre des joueurs — sur un Postgres qui survit aux redemarrages ;
    les fichiers du depot restent lisibles. Sans elle : tout en fichiers.
    """
    app = FastAPI(title="Jeux Strat - serveur de parties")
    gestionnaire = GestionnaireParties(
        dossier_parties or DOSSIER_PARTIES,
        dossier_cartes if dossier_cartes is not None else DOSSIER_CARTES,
        fichier_joueurs=fichier_joueurs,
        database_url=database_url,
        sauvegarde_auto=sauvegarde_auto,
    )
    salles: Dict[str, SallePartie] = {}
    app.state.gestionnaire = gestionnaire

    def get_salle(partie_id: str) -> SallePartie:
        session = gestionnaire.parties.get(partie_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Partie inconnue.")
        if partie_id not in salles:
            salles[partie_id] = SallePartie(
                session, delai_tour_ia=delai_tour_ia, delai_pas_ia=delai_pas_ia,
            )
        return salles[partie_id]

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------

    @app.post("/api/joueurs")
    def inscrire_joueur(corps: Dict[str, Any]):
        try:
            return gestionnaire.registre.inscrire(corps.get("nom"))
        except ValueError as erreur:
            code = 409 if str(erreur) == "nom_pris" else 422
            raise HTTPException(status_code=code, detail=str(erreur))

    @app.get("/api/sauvegardes")
    def lister_sauvegardes():
        return {"sauvegardes": gestionnaire.lister_sauvegardes()}

    @app.get("/api/cartes")
    def lister_cartes():
        return {"cartes": gestionnaire.lister_cartes()}

    @app.post("/api/cartes")
    def importer_carte(corps: Dict[str, Any]):
        """Importe une carte : ``{"nom": "x.json", "carte": {...},
        "remplacer": false}``. 409 si le nom existe deja sans remplacer."""
        try:
            return gestionnaire.importer_carte(
                corps.get("nom"), corps.get("carte"),
                remplacer=bool(corps.get("remplacer")),
            )
        except ValueError as erreur:
            code = 409 if str(erreur) == "carte_existante" else 422
            raise HTTPException(status_code=code, detail=str(erreur))

    @app.get("/api/parties")
    def lister_parties():
        return {"parties": [session.resume() for session in gestionnaire.parties.values()]}

    @app.post("/api/parties")
    def ouvrir_partie(corps: Dict[str, Any]):
        sauvegarde = corps.get("sauvegarde")
        carte = corps.get("carte")
        seed = corps.get("seed")
        if isinstance(sauvegarde, str):
            try:
                session = gestionnaire.ouvrir(sauvegarde, seed=seed)
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail="Sauvegarde inconnue.")
            except (ValueError, KeyError, TypeError):
                raise HTTPException(status_code=422, detail="Sauvegarde illisible.")
        elif isinstance(carte, str):
            try:
                session = gestionnaire.creer(
                    carte,
                    num_players=int(corps.get("joueurs")),
                    ai_player_count=int(corps.get("ia", 0)),
                    difficulty_level=str(corps.get("mode", "normal")),
                    tribes_mode=bool(corps.get("tribus", False)),
                    seed=seed,
                )
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail="Carte inconnue.")
            except (ValueError, KeyError, TypeError):
                raise HTTPException(
                    status_code=422,
                    detail="Parametres invalides (joueurs 2-10, ia 0-joueurs, carte lisible).",
                )
        else:
            raise HTTPException(status_code=422, detail="Champ 'sauvegarde' ou 'carte' requis.")
        return session.resume()

    @app.get("/api/parties/{partie_id}/etat")
    def etat_partie(partie_id: str):
        salle = get_salle(partie_id)
        return salle.session.etat_reseau()

    @app.get("/api/parties/{partie_id}/replay")
    def replay_partie(partie_id: str):
        salle = get_salle(partie_id)
        return {"replay_history": salle.session.replay()}

    @app.get("/api/parties/{partie_id}/bilans")
    def bilans_partie(partie_id: str):
        salle = get_salle(partie_id)
        return salle.session.bilans()

    @app.post("/api/parties/{partie_id}/sauvegarder")
    def sauvegarder_partie(partie_id: str, corps: Optional[Dict[str, Any]] = None):
        salle = get_salle(partie_id)
        fichier = (corps or {}).get("fichier")
        if fichier is not None and not nom_est_valide(fichier):
            raise HTTPException(status_code=422, detail="Nom de fichier invalide.")
        if fichier is not None and fichier.startswith(PREFIXE_SAUVEGARDE_AUTO):
            # Le prefixe des sauvegardes de securite est reserve : une
            # sauvegarde manuelle qui le porterait serait supprimee par la
            # rotation automatique.
            raise HTTPException(
                status_code=422,
                detail="Le prefixe 'auto_' est reserve aux sauvegardes automatiques.",
            )
        try:
            cible = salle.session.sauvegarder(fichier)
        except ValueError:
            raise HTTPException(status_code=422, detail="Aucun fichier cible.")
        return {"fichier": cible}

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    @app.websocket("/ws/parties/{partie_id}")
    async def ws_partie(websocket: WebSocket, partie_id: str):
        session = gestionnaire.parties.get(partie_id)
        if session is None:
            # Accepter avant de fermer : sans handshake, le navigateur ne
            # recoit jamais le code 4004 (il voit un 403 et retente en
            # boucle — le cas d'un onglet reste sur une partie disparue
            # apres un redemarrage du serveur).
            await websocket.accept()
            await websocket.close(code=4004)
            return
        salle = salles.setdefault(partie_id, SallePartie(
            session, delai_tour_ia=delai_tour_ia, delai_pas_ia=delai_pas_ia,
        ))
        await websocket.accept()
        connexion = ConnexionClient(websocket)
        boucle = asyncio.get_running_loop()

        def submit_decider(attaquant: int, territoire, regiments_vaincus: int) -> bool:
            """Pont moteur -> client : pose la question dans la boucle asyncio.

            Appele depuis le thread qui applique l'action ; bloque jusqu'a la
            reponse du client (ou le delai, ou sa deconnexion) puis retourne
            la decision. Par defaut : annexion (False), comme x45 sans Tkinter.
            """
            async def poser_question() -> asyncio.Future:
                connexion.decision_future = boucle.create_future()
                await connexion.envoyer({
                    "type": "question_soumission",
                    "territoire": territoire.id,
                    "nom": territoire.name,
                    "regiments_vaincus": regiments_vaincus,
                })
                return connexion.decision_future

            try:
                future = asyncio.run_coroutine_threadsafe(poser_question(), boucle).result(10.0)
                attente = asyncio.run_coroutine_threadsafe(
                    asyncio.wait_for(asyncio.shield(future), DELAI_DECISION_S), boucle,
                )
                return bool(attente.result(DELAI_DECISION_S + 10.0))
            except Exception:
                # Delai depasse, client deconnecte... : annexion par defaut.
                return False
            finally:
                connexion.decision_future = None

        async def traiter_action(action: Dict[str, Any]) -> None:
            joueur = connexion.joueur
            try:
                resultat = await asyncio.to_thread(
                    session.appliquer_action, joueur, action, submit_decider,
                )
            except Exception:
                # Le client ne doit jamais rester sans reponse : une erreur
                # imprevue du moteur devient un refus (et va dans le log).
                logging.exception("Erreur pendant l'action %r (partie %s)", action, partie_id)
                try:
                    await connexion.envoyer({"type": "refus", "code": "erreur_serveur"})
                except Exception:
                    pass
                return
            finally:
                connexion.action_en_cours = False
            if not resultat.ok and resultat.outcome is None:
                # Refus d'arbitrage serveur : seul l'emetteur est prevenu.
                await connexion.envoyer({"type": "refus", "code": resultat.code})
                return
            if not resultat.ok:
                # Refus du moteur (phase, cible...) : idem, avec le detail.
                await connexion.envoyer({
                    "type": "refus", "code": resultat.code,
                    "resultat": to_jsonable(resultat),
                })
                return
            await salle.diffuser_resultat(joueur, action, resultat)
            await salle.sauvegarder_auto()
            # Si l'action a passe la main a une IA, on deroule ses tours
            # en tache de fond, diffuses un par un.
            salle.lancer_tours_ia()

        try:
            while True:
                message = await websocket.receive_json()
                type_message = message.get("type")

                if type_message == "rejoindre":
                    if connexion in salle.connexions:
                        await connexion.envoyer({"type": "refus", "code": "deja_rejoint"})
                        continue
                    # Chaque tentative repart de l'identite du message (une
                    # tentative refusee ne doit pas laisser la precedente).
                    jeton = message.get("jeton")
                    connexion.jeton = connexion.nom = None
                    if jeton is not None:
                        nom = gestionnaire.registre.nom_par_jeton(jeton)
                        if nom is None:
                            await connexion.envoyer({"type": "refus", "code": "jeton_inconnu"})
                            continue
                        connexion.jeton, connexion.nom = jeton, nom
                    joueur = message.get("joueur")
                    if joueur is None and connexion.jeton is not None:
                        # Reconnexion : l'identite retrouve son siege reserve.
                        joueur = session.siege_de(connexion.jeton)
                    if joueur is not None:
                        if connexion.jeton is None:
                            await connexion.envoyer({"type": "refus", "code": "identite_requise"})
                            continue
                        try:
                            joueur = int(joueur)
                        except (TypeError, ValueError):
                            await connexion.envoyer({"type": "refus", "code": "siege_indisponible"})
                            continue
                        ok, code = session.reserver_siege(joueur, connexion.jeton, connexion.nom)
                        if not ok:
                            await connexion.envoyer({"type": "refus", "code": code})
                            continue
                        connexion.joueur = joueur
                    # Une meme identite n'a qu'une connexion : l'ancienne
                    # (onglet oublie, coupure pas encore detectee) est fermee.
                    if connexion.jeton is not None:
                        for autre in list(salle.connexions):
                            if autre is not connexion and autre.jeton == connexion.jeton:
                                salle.connexions.remove(autre)
                                try:
                                    await autre.websocket.close(code=4000)
                                except Exception:
                                    pass
                    salle.connexions.append(connexion)
                    await connexion.envoyer({
                        "type": "bienvenue",
                        "joueur": connexion.joueur,
                        "nom": connexion.nom,
                        "etat": session.etat_reseau(),
                        "sieges": session.sieges(),
                    })
                    await salle.diffuser_presence()
                    # Si une IA est au trait (sauvegarde chargee, partie
                    # neuve, ou boucle arretee faute de spectateurs), la
                    # nouvelle connexion relance le deroule des tours IA.
                    salle.lancer_tours_ia()

                elif type_message == "action":
                    if connexion.joueur is None:
                        await connexion.envoyer({"type": "refus", "code": "spectateur"})
                        continue
                    if connexion.action_en_cours:
                        await connexion.envoyer({"type": "refus", "code": "action_en_cours"})
                        continue
                    action = message.get("action")
                    if not isinstance(action, dict):
                        await connexion.envoyer({"type": "refus", "code": "action_invalide"})
                        continue
                    connexion.action_en_cours = True
                    asyncio.create_task(traiter_action(action))

                elif type_message == "prendre_siege":
                    if connexion not in salle.connexions or connexion.jeton is None:
                        await connexion.envoyer({"type": "refus", "code": "identite_requise"})
                        continue
                    try:
                        joueur = int(message.get("joueur"))
                    except (TypeError, ValueError):
                        await connexion.envoyer({"type": "refus", "code": "siege_indisponible"})
                        continue
                    ok, code = session.reserver_siege(joueur, connexion.jeton, connexion.nom)
                    if not ok:
                        await connexion.envoyer({"type": "refus", "code": code})
                        continue
                    connexion.joueur = joueur
                    await connexion.envoyer({"type": "siege_pris", "joueur": joueur})
                    await salle.diffuser_presence()

                elif type_message == "quitter_siege":
                    if connexion.joueur is None:
                        await connexion.envoyer({"type": "refus", "code": "aucun_siege"})
                        continue
                    session.liberer_siege(connexion.jeton)
                    connexion.joueur = None
                    await connexion.envoyer({"type": "siege_quitte"})
                    await salle.diffuser_presence()

                elif type_message == "mode_auto":
                    if connexion.joueur is None:
                        await connexion.envoyer({"type": "refus", "code": "aucun_siege"})
                        continue
                    actif = bool(message.get("actif"))
                    ok, code = session.definir_mode_auto(connexion.joueur, actif)
                    if not ok:
                        await connexion.envoyer({"type": "refus", "code": code})
                        continue
                    await salle.diffuser({
                        "type": "mode_auto",
                        "joueur": connexion.joueur,
                        "actif": actif,
                        "nom": connexion.nom,
                    })
                    await salle.diffuser_presence()
                    # Siege confie a l'IA pendant son propre tour : la boucle
                    # IA prend le relais (elle s'arretera d'elle-meme au
                    # prochain humain). La reprise en main au milieu d'un
                    # tour IA est vue par la boucle entre deux passes.
                    salle.lancer_tours_ia()

                elif type_message == "chat":
                    if connexion not in salle.connexions or connexion.nom is None:
                        await connexion.envoyer({"type": "refus", "code": "identite_requise"})
                        continue
                    texte = str(message.get("texte", "")).strip()[:500]
                    if texte:
                        await salle.diffuser({
                            "type": "chat",
                            "joueur": connexion.joueur,
                            "nom": connexion.nom,
                            "texte": texte,
                        })

                elif type_message == "decision_soumission":
                    future = connexion.decision_future
                    if future is not None and not future.done():
                        future.set_result(bool(message.get("reponse")))
                    else:
                        await connexion.envoyer({"type": "refus", "code": "aucune_question"})

                else:
                    await connexion.envoyer({"type": "refus", "code": "message_inconnu"})

        except WebSocketDisconnect:
            pass
        finally:
            future = connexion.decision_future
            if future is not None and not future.done():
                future.set_result(False)
            if connexion in salle.connexions:
                salle.connexions.remove(connexion)
                await salle.diffuser_presence()

    # ------------------------------------------------------------------
    # Client web statique (enregistre apres les routes API : elles priment)
    # ------------------------------------------------------------------

    @app.middleware("http")
    async def revalider_la_page(request, call_next):
        """La page d'accueil n'est jamais servie depuis le cache navigateur.

        Sans cela, apres une mise a jour, le navigateur peut garder l'ancien
        index.html (et donc les anciens ?v=) : les joueurs jouent avec le
        vieux client sans le savoir. ``no-cache`` = revalidation a chaque
        visite (304 si rien n'a change) ; les autres fichiers sont proteges
        par leurs parametres ``?v=``.
        """
        response = await call_next(request)
        if request.url.path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    if DOSSIER_CLIENT.is_dir():
        app.mount("/", StaticFiles(directory=DOSSIER_CLIENT, html=True), name="client")

    return app


# En production (Render...), DATABASE_URL branche les ecritures sur Postgres.
app = creer_app(database_url=os.environ.get("DATABASE_URL"))
