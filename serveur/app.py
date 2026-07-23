"""Application FastAPI du jeu : REST pour le lobby, WebSockets pour jouer.

REST :
- ``POST /api/joueurs``                — ``{"nom": "Alice"}`` cree une
  identite persistante et retourne ``{"jeton": "...", "nom": "Alice"}`` ; le
  client garde le jeton (localStorage) pour rejoindre et se reconnecter.
- ``GET  /api/sauvegardes``            — sauvegardes chargeables.
- ``GET  /api/cartes``                 — cartes pour une partie neuve.
- ``GET  /api/parties``                — parties ouvertes (resume + sieges).
- ``POST /api/parties``                — ouvre une partie :
  ``{"sauvegarde": "partie_001.json"}`` pour recharger une sauvegarde, ou
  ``{"carte": "Alpha.json", "joueurs": 4, "ia": 2, "mode": "normal",
  "tribus": false}`` pour une partie neuve (mise en place du moteur) ;
  ``seed`` optionnel pour des tests reproductibles.
- ``GET  /api/parties/{id}/etat``      — etat complet (sans historique replay).
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
     "etat": {...}}`` — diffuse a tous apres chaque action acceptee (les
  tours IA joues dans la foulee sont dans ``resultat.rapports_ia``).
- ``{"type": "refus", "code": "pas_votre_tour"|...}`` — a l'emetteur seul.
- ``{"type": "question_soumission", "territoire": id, "nom": "...",
     "regiments_vaincus": n}`` — au joueur attaquant seul, pendant une
  attaque de nation ; sans reponse sous ``DELAI_DECISION_S``, annexion.
- ``{"type": "chat", "joueur": n|null, "nom": "...", "texte": "..."}``
- ``{"type": "siege_pris", "joueur": n}`` / ``{"type": "siege_quitte"}`` —
  accuses de reception de ``prendre_siege`` / ``quitter_siege``.
- ``{"type": "victoire", "vainqueur": n, "raison": "..."}``

Le client web (``client/``) est servi en statique a la racine ``/``.

Le traitement d'une action tourne dans un thread (le moteur est synchrone) ;
la boucle de reception continue de lire pendant ce temps, ce qui permet a la
``decision_soumission`` d'arriver au milieu d'une attaque.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .partie import GestionnaireParties, ResultatAction, SessionPartie, to_jsonable

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_PARTIES = RACINE / "parties_en_cours"
DOSSIER_CARTES = RACINE / "cartes_sauvegardees"
DOSSIER_CLIENT = RACINE / "client"

# Temps laisse a un humain pour repondre "soumettre ou annexer ?" avant que
# le serveur tranche (annexion, comme x45 sans Tkinter).
DELAI_DECISION_S = 120.0


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

    def __init__(self, session: SessionPartie) -> None:
        self.session = session
        self.connexions: list[ConnexionClient] = []

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
              fichier_joueurs: Optional[Path] = None) -> FastAPI:
    """Construit l'application (dossiers et registre injectables, tests)."""
    app = FastAPI(title="Jeux Strat - serveur de parties")
    gestionnaire = GestionnaireParties(
        dossier_parties or DOSSIER_PARTIES,
        dossier_cartes if dossier_cartes is not None else DOSSIER_CARTES,
        fichier_joueurs=fichier_joueurs,
    )
    salles: Dict[str, SallePartie] = {}
    app.state.gestionnaire = gestionnaire

    def get_salle(partie_id: str) -> SallePartie:
        session = gestionnaire.parties.get(partie_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Partie inconnue.")
        if partie_id not in salles:
            salles[partie_id] = SallePartie(session)
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

    @app.post("/api/parties/{partie_id}/sauvegarder")
    def sauvegarder_partie(partie_id: str, corps: Optional[Dict[str, Any]] = None):
        salle = get_salle(partie_id)
        fichier = (corps or {}).get("fichier")
        chemin = None
        if fichier is not None:
            chemin = (gestionnaire.dossier_sauvegardes / str(fichier)).resolve()
            if chemin.parent != gestionnaire.dossier_sauvegardes.resolve():
                raise HTTPException(status_code=422, detail="Nom de fichier invalide.")
        try:
            cible = salle.session.sauvegarder(chemin)
        except ValueError:
            raise HTTPException(status_code=422, detail="Aucun fichier cible.")
        return {"fichier": cible.name}

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    @app.websocket("/ws/parties/{partie_id}")
    async def ws_partie(websocket: WebSocket, partie_id: str):
        session = gestionnaire.parties.get(partie_id)
        if session is None:
            await websocket.close(code=4004)
            return
        salle = salles.setdefault(partie_id, SallePartie(session))
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
                    # Si la sauvegarde chargee laissait une IA au trait, le
                    # premier arrivant declenche les tours IA en attente.
                    if len(salle.connexions) == 1:
                        rapport = await asyncio.to_thread(session.jouer_tours_ia_en_attente)
                        if rapport.ok and rapport.rapports_ia:
                            await salle.diffuser_resultat(-1, None, rapport)

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

    if DOSSIER_CLIENT.is_dir():
        app.mount("/", StaticFiles(directory=DOSSIER_CLIENT, html=True), name="client")

    return app


app = creer_app()
