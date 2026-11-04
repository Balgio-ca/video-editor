# video-editor

**Montage automatisé de reels verticaux, piloté par un agent IA.**

Donnez-lui des rushs bruts filmés au téléphone ou à la caméra : il coupe les silences et les faux
départs, transcrit au mot près, écrit les sous-titres animés, pose le b-roll, l'accroche, les verdicts
animés et la carte de fin, puis livre un MP4 1080 × 1920 normalisé à -14 LUFS, prêt pour Instagram,
TikTok et Facebook.

Le pipeline est conçu pour être conduit par un agent de code (Claude Code, Codex, Gemini CLI...) :
vous décrivez ce que vous voulez en langage courant, l'agent lance le montage, le contrôle, puis
retouche selon vos commentaires.

[![Licence : PolyForm Noncommercial](https://img.shields.io/badge/licence-PolyForm%20Noncommercial%201.0.0-blue)](LICENSE)
![Plateformes](https://img.shields.io/badge/plateformes-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.12-informational)

---

## Fonctions

- **Coupes propres** : silences retirés, coupe posée dans le creux sonore entre deux mots, fondu audio.
- **Transcription mot à mot** : Whisper large-v3-turbo, deuxième passe sur les passages sautés,
  noms propres du client fournis au modèle.
- **Édito par IA** : un modèle de langue choisit les coupes, les pages de sous-titres, le b-roll et
  l'accroche. Claude, Gemini, OpenAI ou un modèle local (Ollama).
- **Sous-titres animés** : 1 à 3 mots, mot prononcé en couleur de marque, styles gros, encadré, cursive.
- **B-roll** : clips et photos du client en priorité, Pexels en repli ; jamais un éclair de visage
  entre deux plans.
- **Habillage** : accroche, cartes de titre, verdicts plein écran (vrai / faux, red flag / green flag),
  voix hors champ en effet téléphone, autocollants, intro sur jingle, carte de fin générée depuis le
  profil du client.
- **Son** : musique avec ducking sous la voix, banque d'effets sonores et dossier pour les vôtres,
  volume final réglable (-14 LUFS par défaut).
- **Génération par IA** (facultatif) : voix off, effets sonores, musique et jingles par ElevenLabs ;
  images et vidéos de b-roll par OpenAI ou Gemini quand aucun vrai plan ne convient.
- **Couleur** : détection du S-Log3 et LUT vers Rec.709, étalonnage automatique de l'exposition.
- **Bilingue** : français (Québec) et anglais.

## Sommaire

- [Installation](#installation) : [macOS](#macos) · [Linux](#linux) · [Windows](#windows)
- [Démarrage rapide](#démarrage-rapide)
- [Configuration](#configuration)
- [Utilisation](#utilisation)
- [Avec un agent IA](#avec-un-agent-ia)
- [Dépannage](#dépannage)
- [Documentation](#documentation) · [Licence](#licence)

---

## Installation

Il faut partout : **FFmpeg 6 ou plus**, **Node.js 22 ou plus**, **Python 3.12**, **Google Chrome**
(utilisé par HyperFrames pour le rendu) et [uv](https://docs.astral.sh/uv/) pour Python.

| | Transcription | Encodage vidéo |
|---|---|---|
| macOS, puce Apple | mlx-whisper (GPU Apple) | VideoToolbox |
| Linux, Windows avec carte NVIDIA | faster-whisper (CUDA) | NVENC |
| Linux, Windows sans carte NVIDIA, Mac Intel | faster-whisper (processeur, plus lent) | libx264 |

Le bon moteur est choisi tout seul ; voir [Configuration](#configuration) pour le forcer.

### macOS

```bash
brew install ffmpeg uv node
brew install --cask google-chrome

git clone https://github.com/Balgio-ca/video-editor.git
cd video-editor
npm install
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
```

### Linux

Exemple pour Ubuntu ou Debian :

```bash
sudo apt update
sudo apt install -y ffmpeg git curl
curl -LsSf https://astral.sh/uv/install.sh | sh
# Node 22 par nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
source ~/.nvm/nvm.sh && nvm install 22
# Google Chrome
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y ./google-chrome-stable_current_amd64.deb

git clone https://github.com/Balgio-ca/video-editor.git
cd video-editor
npm install
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
```

Avec une carte NVIDIA, installer le pilote et CUDA 12 : faster-whisper et NVENC s'en servent seuls.
Vérifier que votre FFmpeg a `libx264` et `lut3d` (`ffmpeg -encoders | grep 264`).

### Windows

Dans PowerShell :

```powershell
winget install Gyan.FFmpeg OpenJS.NodeJS.LTS astral-sh.uv Git.Git Google.Chrome
# fermer et rouvrir PowerShell pour charger le PATH

git clone https://github.com/Balgio-ca/video-editor.git
cd video-editor
npm install
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
copy .env.example .env
```

Sous Windows, remplacer `.venv/bin/python` par `.venv\Scripts\python.exe` dans les commandes qui suivent.
Avec une carte NVIDIA, installer le dernier pilote et CUDA 12.

### Vérifier l'installation

```bash
.venv/bin/python pipeline/diagnostic.py
```

Le diagnostic vérifie FFmpeg et ses filtres, Node 22, HyperFrames, Chrome, la transcription, le modèle
de langue et les clés facultatives, puis donne la commande exacte pour corriger chaque point manquant.

---

## Démarrage rapide

**1. Un profil client.** Copier [clients/exemple-plancher.json](clients/exemple-plancher.json) en
`clients/mon-client.json` et l'adapter : nom, couleur de marque, noms propres, appel à l'action,
carte de fin.

**2. Un projet.** Le créer d'un coup à partir d'un dossier de rushs (un sujet par fichier) :

```bash
.venv/bin/python pipeline/nouveau_projet.py mon-projet --client mon-client --mois 2026-11 ~/Videos/tournage-novembre
```

ou le préparer à la main :

```
work/mon-projet/
├── sujets.json
└── promo-hiver/
    ├── brief.txt       (facultatif) consignes pour ce reel
    └── src/
        ├── C0040.MP4
        └── C0041.MP4
```

```json
{
  "_projet": {"client": "mon-client", "mois": "2026-11"},
  "promo-hiver": {"rushs": ["C0040.MP4", "C0041.MP4"], "motif": "Promo-Hiver"}
}
```

**3. Monter.**

```bash
.venv/bin/python pipeline/rendre.py mon-projet promo-hiver --broll
```

Le reel sort dans `out/mon-client/2026-11_Promo-Hiver-....mp4`.

**4. Contrôler.**

```bash
.venv/bin/python pipeline/controle.py mon-projet promo-hiver --ecoute
```

```
out/mon-client/2026-11_Promo-Hiver-Ouvert-Tout-L-Hiver.mp4 : 34.5 s, -14.1 LUFS, accroche 3.500 s, 3 b-roll
work/mon-projet/check_promo-hiver.jpg
ÉCOUTE : Cet hiver, on reste ouvert six jours semaine...
```

---

## Configuration

Tout se règle dans `.env` (chargé automatiquement) ou par variable d'environnement.

### Le modèle de langue

Seule l'étape édito appelle un modèle de langue ; le reste tourne sur la machine.

| `LLM_PROVIDER` | Clé | Modèle par défaut |
|---|---|---|
| `claude-cli` (défaut) | aucune : [Claude Code](https://claude.com/claude-code) installé et `claude login` fait | `sonnet` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` |
| `gemini` | `GEMINI_API_KEY` ([obtenir une clé](https://aistudio.google.com/apikey)) | `gemini-2.5-pro` |
| `openai` | `OPENAI_API_KEY` | `gpt-4.1` |

`LLM_MODEL` change le modèle. Le fournisseur `openai` accepte tout service compatible
(Ollama, OpenRouter, Mistral, Groq) avec `OPENAI_BASE_URL` :

```ini
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen3:32b
```

Un modèle trop petit suit mal la consigne (index de mots, pages de 3 mots) ; l'édito est alors refusé
avec un message d'erreur. Un modèle de la classe Sonnet, Gemini Pro ou GPT-4.1 est recommandé.

### Les clés facultatives

| Variable | Sert à | Sans elle |
|---|---|---|
| `PEXELS_API_KEY` | b-roll de banque ([clé gratuite](https://www.pexels.com/api/)) | seulement le b-roll du client |
| `ELEVENLABS_API_KEY` | voix off, effets sonores, musique, jingles (`generer.py voix / son / musique`) | sons de la banque et vos fichiers |
| `ELEVENLABS_VOICE_ID` | voix par défaut des voix off | préciser `--voix` à chaque fois |
| `OPENAI_API_KEY` | édito si `LLM_PROVIDER=openai` ; images (gpt-image-1) et vidéos (Sora) de b-roll | pas de génération OpenAI |
| `GEMINI_API_KEY` | édito si `LLM_PROVIDER=gemini` ; images et vidéos (Veo) de b-roll | pas de génération Gemini |
| `IMAGE_PROVIDER`, `IMAGE_MODEL` | fournisseur d'images de b-roll : `openai` (défaut) ou `gemini` | |
| `VIDEO_GEN_PROVIDER`, `VIDEO_MODEL` | fournisseur de vidéos de b-roll : `gemini` (défaut) ou `openai` | |

### La machine

| Variable | Rôle |
|---|---|
| `VIDEO_ENCODER` | `videotoolbox`, `nvenc` ou `x264` pour forcer l'encodeur |
| `WHISPER_BACKEND` | `mlx` ou `faster` pour forcer la transcription |
| `WHISPER_MODEL` | modèle Whisper (`large-v3-turbo` par défaut ; `medium` ou `small` sur une machine lente) |
| `WHISPER_DEVICE` | `cuda`, `cpu` ou `auto` pour faster-whisper |
| `HF_GPU` | `1` pour activer l'accélération GPU du rendu hors Mac |

---

## Utilisation

### Un projet, un lot de reels

`work/<projet>/sujets.json` décrit chaque reel du lot ([exemple complet](examples/sujets.json)) :

| Clé | Rôle |
|---|---|
| `_projet.client`, `_projet.mois` | client et mois par défaut de tous les sujets |
| `rushs` | fichiers dans `<sujet>/src/`, ou chemins relatifs au projet (`../entrevue/src/C0032.MP4`) pour tirer plusieurs reels d'une même entrevue |
| `motif` | début du nom du fichier final |
| `langue` | `fr` (défaut) ou `en` |
| `lut` | `auto` (détecte le S-Log3) ou `none` |
| `rotation` | `auto`, `none`, `cw`, `ccw` |

Le `brief.txt` d'un sujet guide l'édito : sujet, passage à garder, ton, consignes de b-roll
([exemple](examples/brief.txt)).

### Commandes

```bash
# premier passage sur tout le lot : transcription et édito, sans rendu
.venv/bin/python pipeline/rendre.py mon-projet --tous --jusqua edito

# rendu d'un sujet (--broll refait la recherche de b-roll)
.venv/bin/python pipeline/rendre.py mon-projet promo-hiver --broll

# re-rendu après une retouche d'edit.json
.venv/bin/python pipeline/rendre.py mon-projet promo-hiver

# édito par un autre modèle, pour ce sujet seulement
.venv/bin/python pipeline/rendre.py mon-projet promo-hiver --llm gemini
```

### Retoucher

Chaque reel a un plan de montage, `work/<projet>/<sujet>/edit.json`. On le modifie, puis on relance
`rendre.py`. Tous les réglages sont dans [docs/EDIT.md](docs/EDIT.md). Quelques exemples :

```json
{
  "coupes":      [{"debut_mot": 223, "fin_mot": 224, "raison": "« en fait » de remplissage"}],
  "corrections": {"258": "dégât"},
  "broll":       [{"debut_mot": 256, "fin_mot": 259, "source": "pexels-id:7681545"}],
  "voix_off":    [{"debut_mot": 199, "fin_mot": 221, "effet": "telephone"}],
  "verdicts":    [{"mot": 222, "type": "faux"}]
}
```

### Outils

| Script | Usage |
|---|---|
| `pipeline/diagnostic.py [--rapide]` | vérifie l'installation et les clés, dit quoi corriger |
| `pipeline/nouveau_projet.py <projet> --client C --mois AAAA-MM <rushs>` | crée un projet à partir d'un dossier de rushs |
| `pipeline/rendre.py <projet> <sujet>` | monte un sujet ; `--broll`, `--jusqua <étape>`, `--tous`, `--llm`, `--model`, `--verbeux` |
| `pipeline/generer.py voix / son / musique / image / video` | génère par IA une voix off, un effet sonore, une musique, une image ou une vidéo de b-roll |
| `pipeline/controle.py <projet> <sujet> [--ecoute]` | durée, LUFS, planche de contact, retranscription du montage |
| `pipeline/plan.py <projet> <sujet>` | transcription indexée, texte gardé, coupes, b-roll |
| `pipeline/ecouter.py <projet> <sujet> <début> <fin>` | enveloppe sonore et mots horodatés d'un passage, pour placer une coupe |
| `pipeline/pexels_candidats.py <dossier> "tag=requête"...` | planche de vignettes Pexels pour choisir un plan |
| `pipeline/broll_usage.py <projet>` | combien de fois chaque b-roll sert dans le lot |
| `pipeline/apercu.py <reel.mp4>` | copie 720p de moins de 30 Mo pour un téléphone |
| `pipeline/archive_broll.py <sortie> <source>...` | convertit des rushs d'archive (dossier local ou `hôte:/chemin`) en b-roll |
| `pipeline/fusion_elisions.py <projet> <sujet>` | recolle les élisions séparées par Whisper |
| `pipeline/planche_clips.py <dossier> [pas]` | planche de vignettes d'un dossier de clips |
| `pipeline/reel.py` | le pipeline brut, sans projet (`--help`) |

### Son, musique et mixage

- **Musique** : `"musique": {"fichier": "..."}` dans le profil client ; avec `"mix": {"ducking": true}`,
  elle baisse d'elle-même sous la voix et remonte dans les pauses.
- **Vos effets sonores** : déposez des `.mp3` ou `.wav` dans [`sons/`](sons/README.md) (ou
  `work/<client>/assets/sons/`) ; ils s'utilisent par leur nom dans `edit.json` :
  `"sons": [{"mot": 57, "fichier": "caisse"}]`.
- **Volume** : `"mix"` règle la musique sous la voix et sur la carte de fin, le volume des effets et
  le volume final. Détails dans [docs/EDIT.md](docs/EDIT.md#mixage--mix).

### Cartes

- **Carte de fin** : `"carte_fin": {"type": "auto"}` la génère à partir du profil (logo, phrase,
  téléphone, adresse, site) ; `{"type": "video", "fichier": "..."}` prend une vidéo fournie.
- **Cartes de titre** : `"cartes": [{"mot": 359, "titre": "Question 2"}]` dans `edit.json`.

### Générer ce qui manque

```bash
python pipeline/generer.py voix --liste --recherche french
python pipeline/generer.py voix "Vous cherchez un plancher pour votre sous-sol?" --sortie work/mon-client/assets/voix/question.mp3
python pipeline/generer.py son "petit ding de caisse enregistreuse" --nom caisse --duree 1
python pipeline/generer.py musique "lo-fi chaleureux, guitare douce, sans voix" --sortie work/mon-client/assets/musique/lofi.mp3 --duree 30
python pipeline/generer.py image "sous-sol inondé, eau sur un plancher de bois" --client mon-client --nom sous-sol
python pipeline/generer.py video "enfant qui souffle les bougies d'un gâteau" --client mon-client --nom bougies
```

Une image ou une vidéo générée rejoint le b-roll du client sous l'id `gen-<nom>` (`"source":
"local:gen-sous-sol"`). À réserver aux moments qu'aucun vrai plan ne montre, et jamais pour un produit
du client, qui se montre avec sa vraie photo. Ces générations sont payantes chez chaque fournisseur.

### Le b-roll du client

Les clips et photos du client vont dans `work/<client>/assets/broll/`, décrits par un `index.json`
que l'édito lit pour choisir :

```json
[
  {"id": "planches-empilees", "file": "planches-empilees.mp4", "type": "video", "duree": 11.4,
   "description": "Planches de bois franc empilées contre un mur, lent panoramique.",
   "tags": ["bois franc", "stock", "entrepôt"]}
]
```

Les photos de son catalogue vont dans `work/<client>/assets/produits/index.json` (ids `site-...`) :
quand la personne nomme un produit, c'est la vraie photo qui s'affiche.

### Comment ça marche

| Étape | Outil | Fichier produit |
|---|---|---|
| 1. normalize | FFmpeg, LUT S-Log3 | `rush_1080.mp4` |
| 2. cut | auto-editor | `rush_cut.mp4` |
| 3. transcribe | mlx-whisper ou faster-whisper | `words.json` |
| 4. edito | modèle de langue | `edit.json` |
| 5. broll | b-roll du client, catalogue, Pexels | `broll.json` |
| 6. compose | gabarit HTML [HyperFrames](https://www.npmjs.com/package/hyperframes) | `comp/index.html` |
| 7. render | HyperFrames, loudnorm | `out/<client>/AAAA-MM_Titre.mp4` |

Chaque étape est en cache : effacer un fichier produit refait l'étape et les suivantes.

---

## Avec un agent IA

Ouvrez le dossier dans votre agent et parlez-lui normalement :

> Monte les rushs de `work/salon-mai/` en reels, un sujet à la fois, et montre-moi chacun.

> Dans le reel 3, la coupe après la question est trop sèche et il manque l'explication du milieu.

> Remplace le b-roll sur « dégât d'eau » par une vraie flaque, et mets la question du caméraman en voix téléphone.

[AGENTS.md](AGENTS.md) donne à l'agent la méthode : le cycle rendre-contrôler-montrer, comment placer
une coupe à l'oreille avec `ecouter.py`, et les règles de montage apprises en production. Claude Code
le lit par `CLAUDE.md`, Gemini CLI par `GEMINI.md`, Codex et Cursor directement.

---

## Dépannage

| Symptôme | Cause et solution |
|---|---|
| Quelque chose ne marche pas | lancer `pipeline/diagnostic.py` : il dit quoi corriger |
| `HyperFrames demande Node.js 22 ou plus` | installer Node 22 (`nvm install 22`, ou `winget install OpenJS.NodeJS.LTS`) |
| `claude -p a échoué` | faire `claude login`, ou passer à un autre fournisseur (`LLM_PROVIDER`) |
| `<CLÉ> manquante pour le fournisseur` | remplir la clé dans `.env` |
| `page hors norme` | le modèle a fait une page de plus de 3 mots : relancer l'édito ou prendre un modèle plus fort |
| Transcription très lente | sans GPU, prendre `WHISPER_MODEL=small` ou `medium` |
| Image orange ou magenta | rush S-Log mal détecté : mettre `"lut": "none"` dans `sujets.json` et régler `grade` |
| Image couchée | mettre `"rotation": "cw"` ou `"ccw"` dans `sujets.json` |
| `son « x » introuvable` | le fichier `x.mp3` ou `x.wav` n'est ni dans `sons/` ni dans `assets/sons/` du client |
| `/v1/music a répondu 404` | ElevenLabs a changé ce point d'accès : voir la note dans `pipeline/generer.py` |
| Un mot manque dans le montage | `ecouter.py` sur le passage, recaler le mot dans `words.json` ou couper en secondes |

---

## Documentation

- [docs/EDIT.md](docs/EDIT.md) : tous les réglages de retouche, avec exemples
- [AGENTS.md](AGENTS.md) : la méthode de travail pour un agent IA
- [STANDARDS.md](STANDARDS.md) : les règles de qualité d'un reel
- [THIRD_PARTY.md](THIRD_PARTY.md) : composants tiers et leurs licences

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE). Libre pour un usage personnel, la recherche, l'enseignement
et les organismes sans but lucratif. Tout usage commercial demande une licence de
[Balgio](https://balgio.ca).

© 2026 Balgio
