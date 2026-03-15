# Comment fonctionne GitHub : Desktop vs En ligne

## Vue d'ensemble

GitHub repose sur **Git**, un système de contrôle de version qui permet de suivre les modifications apportées à des fichiers au fil du temps. Il existe deux façons principales d'interagir avec GitHub : via le **site web GitHub.com** (en ligne) et via **GitHub Desktop** (application de bureau).

---

## Le dépôt distant vs le dépôt local

| Concept | Description |
|---|---|
| **Dépôt distant (remote)** | Le dépôt hébergé sur GitHub.com, accessible depuis n'importe où |
| **Dépôt local** | La copie du dépôt sur ton ordinateur, dans laquelle tu travailles |

Lorsque tu travailles avec GitHub Desktop, tu as une **copie locale** du projet sur ton ordinateur. Les modifications que tu fais localement ne sont pas automatiquement visibles sur GitHub.com : il faut les **pousser** (push).

---

## Les opérations clés

### 1. Cloner un dépôt (`Clone`)
- **Depuis GitHub.com** : Clique sur le bouton vert "Code" → "Open with GitHub Desktop"
- **Dans GitHub Desktop** : `File > Clone repository` → sélectionne le dépôt
- Cela crée une copie locale du dépôt sur ton ordinateur

### 2. Faire des modifications et les enregistrer (`Commit`)
- Modifie les fichiers dans ton éditeur de code (VS Code, etc.)
- Dans **GitHub Desktop**, les fichiers modifiés apparaissent dans le panneau de gauche
- Écris un **message de commit** qui décrit tes changements
- Clique sur **"Commit to main"** (ou à la branche courante)
- ⚠️ Le commit est **local uniquement** : les changements ne sont pas encore sur GitHub.com

### 3. Envoyer les modifications en ligne (`Push`)
- Après avoir fait un commit, clique sur **"Push origin"** dans GitHub Desktop
- Tes modifications sont maintenant visibles sur **GitHub.com**
- ℹ️ Si tu modifies un fichier **directement sur GitHub.com** (via l'éditeur web), le commit est créé directement sur le dépôt distant — aucune étape de push n'est nécessaire

### 4. Récupérer les modifications de GitHub.com (`Pull` / `Fetch`)
- Si quelqu'un d'autre a modifié le dépôt en ligne, tu dois récupérer ces changements
- Dans **GitHub Desktop** : clique sur **"Fetch origin"** pour vérifier s'il y a des nouveautés, puis **"Pull"** pour les télécharger
- Cela met à jour ta copie locale avec les dernières modifications du dépôt distant

---

## Le flux de travail typique

```
GitHub.com (distant)
       ↑  push (envoyer)
       |
       ↓  pull/fetch (récupérer)
GitHub Desktop + ton ordinateur (local)
```

### Étape par étape :
1. 🔄 **Fetch/Pull** → récupère les dernières modifications depuis GitHub.com
2. ✏️ **Modifie** tes fichiers localement
3. ✅ **Commit** → enregistre un "snapshot" de tes changements (localement)
4. 🚀 **Push** → envoie tes commits vers GitHub.com

---

## GitHub Desktop vs GitHub.com : comparaison

| Fonctionnalité | GitHub Desktop | GitHub.com |
|---|---|---|
| Modifier des fichiers | ✅ (via éditeur externe) | ✅ (éditeur web intégré) |
| Créer un commit | ✅ Interface graphique | ✅ Directement en ligne |
| Push / Pull | ✅ Boutons dédiés | N/A (commits directs sur le distant) |
| Gérer les branches | ✅ | ✅ |
| Résoudre des conflits | ✅ Interface visuelle | ⚠️ Limité |
| Voir l'historique | ✅ | ✅ |
| Créer une Pull Request | ✅ (redirige vers le web) | ✅ |

---

## Les branches

Les **branches** permettent de travailler sur une fonctionnalité sans affecter le code principal (`main`).

- **Créer une branche** dans GitHub Desktop : menu déroulant en haut au centre → "New branch"
- **Changer de branche** : même menu déroulant
- **Fusionner** (merge) une branche : depuis GitHub.com, crée une **Pull Request**, puis fusionne-la

---

## Résumé visuel

```
[Ton ordinateur / GitHub Desktop]         [GitHub.com / En ligne]
         |                                          |
   Clone ←───────────────────────────────────────── |
         |                                          |
   Modifie localement                               |
         |                                          |
   Commit (local)                                   |
         |                                          |
   Push ──────────────────────────────────────────→ |
         |                                          |
   Fetch/Pull ←──────────────────────────────────── |
```

---

## Conseils pratiques

- 🔄 **Toujours faire un Fetch/Pull avant de commencer à travailler** pour éviter les conflits
- 💬 **Écris des messages de commit clairs** : "Ajout de la page d'accueil" plutôt que "modif"
- 🌿 **Utilise des branches** pour chaque nouvelle fonctionnalité
- 🚀 **Push régulièrement** pour sauvegarder ton travail en ligne et le partager
