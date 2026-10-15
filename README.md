# Agenda de Wezembeek-Oppem — automatique

Chaque jour, un petit robot gratuit (GitHub Actions) lit la liste officielle
des activités de la commune (FR : `/fr/activites`, NL : `/activiteiten`) et publie :

| Fichier publié | À quoi ça sert |
|---|---|
| `index.html` / `nl.html` | Page publique FR / NL avec la liste et les boutons « S'abonner » |
| `agenda-fr.ics` / `agenda-nl.ics` | Calendriers à ajouter dans Google Agenda, Outlook, iPhone… (mise à jour automatique) |
| `whatsapp.html` | **Ta page** : les deux messages de la semaine, avec un bouton « Copier » |
| `whatsapp-fr.txt` / `whatsapp-nl.txt` | Les mêmes messages en texte brut |

Le message couvre **du jeudi au samedi de la semaine suivante** (10 jours).
Il est régénéré chaque matin : si la commune ajoute une activité le mardi, le
message du jeudi en tiendra compte.

---

## Installation (≈ 15 minutes, une seule fois)

### 1. Créer le dépôt
1. Crée un compte gratuit sur <https://github.com> (si ce n'est pas déjà fait).
2. Clique sur **New repository** → nom : `agenda-wezembeek` → **Public** → *Create repository*.

### 2. Envoyer les fichiers
**Option simple (navigateur)** : sur la page du dépôt, *Add file → Upload files*,
glisse **le contenu** du dossier décompressé (`agenda.py`, `requirements.txt`,
`README.md`, `tests/`), puis *Commit changes*.

Le dossier `.github` est masqué sur Mac/Windows, donc crée le robot à la main :
*Add file → Create new file* → nom : `.github/workflows/agenda.yml` → colle le
contenu du fichier `agenda.yml` fourni → *Commit changes*.

**Option ligne de commande** :
```bash
cd agenda-wezembeek
git init -b main && git add . && git commit -m "Agenda"
git remote add origin https://github.com/<TON-COMPTE>/agenda-wezembeek.git
git push -u origin main
```

### 3. Lancer le robot une première fois
Onglet **Actions** → *Mise à jour de l'agenda* → **Run workflow**.
Après ±1 minute, un dossier `docs/` apparaît dans le dépôt.

> Si l'étape « Publier » échoue avec une erreur de permission :
> *Settings → Actions → General → Workflow permissions* → **Read and write permissions** → *Save*, puis relance.

### 4. Activer la page web
*Settings → Pages* → **Source : Deploy from a branch** → Branch **main**, dossier **/docs** → *Save*.
Après 1–2 minutes, ton agenda est en ligne :

- Page FR : `https://<TON-COMPTE>.github.io/agenda-wezembeek/`
- Page NL : `https://<TON-COMPTE>.github.io/agenda-wezembeek/nl.html`
- Tes messages : `https://<TON-COMPTE>.github.io/agenda-wezembeek/whatsapp.html` ← à mettre en favori sur ton téléphone

### 5. T'abonner toi-même
Ouvre la page FR → **Google Agenda** (ou **iPhone / Mac / Outlook**).
Pour Outlook : *Ajouter un calendrier → S'abonner à partir du web* → colle le lien `.ics`.

---

## Routine du jeudi (2 minutes)
1. Ouvre `…/whatsapp.html` sur ton téléphone.
2. **Copier** le bloc FR → colle-le dans le groupe d'annonces de la communauté FR.
3. Idem pour le bloc NL → communauté NL.

## Les communautés WhatsApp
- Crée une **Communauté** par langue (*Agenda Wezembeek-Oppem* / *Agenda Wezembeek-Oppem NL*).
  Dans une communauté, seul l'admin peut publier dans le groupe **Annonces** : c'est exactement ce que tu veux.
  Dans les paramètres, désactive la possibilité pour les membres de créer d'autres groupes.
- Alternative : une **Chaîne WhatsApp** (*Channel*) par langue — également en lecture seule
  pour les abonnés, et les numéros des abonnés n'y sont pas visibles.
- Mets le lien de la page agenda dans la description de la communauté/chaîne.

---

## Personnaliser
Tous les textes (salutation, titre, pied de message…) sont dans le bloc `TEXTS`
en haut de `agenda.py`. Le jour de publication et la durée : `PUBLISH_WEEKDAY`
et `WINDOW_DAYS`.

## Si quelque chose casse
- Si le site de la commune change de mise en page, le robot **n'écrase rien** :
  il s'arrête en erreur et GitHub t'envoie un e-mail. L'ancien agenda reste en ligne.
- Tester en local : `pip install -r requirements.txt && python agenda.py`
  (tests : `python tests/test_agenda.py`).
- GitHub met en pause les tâches planifiées d'un dépôt sans aucune activité pendant 60 jours ;
  ici le robot fait lui-même des mises à jour, ce qui ne devrait pas arriver. Si besoin : *Actions → Enable workflow*.
