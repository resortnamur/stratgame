# Mettre le jeu en ligne (gratuit) — Render + Neon

Objectif : une adresse publique (`https://stratgame.onrender.com` ou
similaire) où chacun joue depuis son navigateur. Deux services gratuits :

- **Render** héberge le serveur (FastAPI + WebSockets). Offre gratuite :
  le service s'endort après ~15 minutes sans visite et se réveille en
  ~30-60 s à la visite suivante — le premier arrivé patiente un peu.
- **Neon** héberge le Postgres. Le disque de Render est **effacé à chaque
  redémarrage** : tout ce que les joueurs écrivent (sauvegardes, cartes
  importées, registre des joueurs) va donc en base, qui, elle, survit.
  Les 23 sauvegardes et 42 cartes du dépôt restent disponibles en lecture.

Le code est prêt : `DATABASE_URL` définie → écritures en base ;
absente → tout en fichiers (le jeu local et `Lancer le serveur.bat`
fonctionnent exactement comme avant).

## 1. Pousser le dépôt sur GitHub

Sur github.com (compte `resortnamur`) : **New repository**, nom
`stratgame` (privé ou public, les deux marchent avec Render), **sans**
README ni .gitignore initial. Puis, depuis le dossier `Jeux Strat` :

```bash
git remote add origin https://github.com/resortnamur/stratgame.git
```

```bash
git push -u origin master
```

(~40 Mo : les sauvegardes et cartes font partie du dépôt, c'est voulu.)

## 2. Créer la base Neon

1. https://neon.tech → **Sign up** (le compte GitHub fait l'affaire).
2. Créer un projet (nom libre, région `eu-central` par exemple).
3. Copier la **chaîne de connexion** affichée (bouton *Connect*), du type
   `postgresql://...@...neon.tech/neondb?sslmode=require` — c'est la
   future `DATABASE_URL`. Elle est secrète : ne la mettre nulle part
   dans le dépôt.

Rien d'autre à préparer : le serveur crée sa table `documents` tout seul
au premier démarrage.

## 3. Créer le service Render

1. https://render.com → **Sign up** (là aussi, le compte GitHub simplifie
   la suite) → autoriser Render à voir le dépôt `stratgame`.
2. **New → Blueprint** → choisir le dépôt : Render lit `render.yaml` et
   propose le service `stratgame` (plan Free).
3. À l'étape des variables d'environnement, renseigner `DATABASE_URL`
   avec la chaîne Neon copiée plus haut.
4. Déployer. Le premier build prend quelques minutes ; l'adresse publique
   apparaît en haut de la page du service.

Variante sans blueprint : **New → Web Service**, runtime Python,
build `pip install -r requirements.txt`, start
`uvicorn serveur.app:app --host 0.0.0.0 --port $PORT`, plan Free,
variables `PYTHON_VERSION=3.12.10` et `DATABASE_URL=...`.

## 4. Vérifier

- Ouvrir l'adresse publique : écran d'identité, lobby, cartes listées.
- Créer une partie, jouer un tour, **Sauvegarder** via
  `POST /api/parties/{id}/sauvegarder` (ou simplement jouer) ;
- Dans Render : **Manual Deploy → Restart** ; revenir sur le site :
  les identités et sauvegardes doivent avoir survécu (elles sont dans
  Neon, pas sur le disque).

## Mises à jour

Chaque `git push` sur la branche suivie redéclenche un déploiement
automatique. Les parties **en cours** vivent en mémoire : un déploiement
les interrompt (les joueurs sauvegardent avant, ou reprennent depuis la
dernière sauvegarde en base).

## À savoir

- **Une seule instance, un seul worker** : l'état des parties est en
  mémoire. Ne pas augmenter le nombre de workers/instances sur Render.
- **Pas de mot de passe** : quiconque a l'adresse peut entrer au lobby.
  Entre amis c'est voulu ; un code d'accès pourra s'ajouter plus tard si
  l'adresse circule trop.
- **Limites gratuites** : Neon ~0,5 Go (des centaines de sauvegardes),
  Render 750 h/mois d'instance — largement assez pour un serveur qui dort
  quand personne ne joue.
