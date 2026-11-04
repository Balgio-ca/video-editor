# video-editor : montage de reels automatisé

Des rushs bruts vers un reel vertical prêt à publier, sans montage manuel : coupes des silences et des
faux départs, sous-titres animés mot à mot, b-roll, accroche, verdicts animés, carte de fin, son
normalisé à -14 LUFS. Le pipeline fait le premier montage ; un humain relit, ajuste `edit.json` et
relance le rendu.

Conçu par [Balgio](https://balgio.ca) pour des reels de commerces locaux en français du Québec ;
l'anglais est aussi pris en charge.

**Licence : [PolyForm Noncommercial 1.0.0](LICENSE).** Usage personnel, recherche, enseignement et
organismes sans but lucratif seulement. Tout usage commercial (agence, client payant, contenu pour une
entreprise) est interdit sans une licence commerciale de Balgio.

- [docs/EDIT.md](docs/EDIT.md) : tous les réglages de retouche, avec exemples
- [STANDARDS.md](STANDARDS.md) : les règles de qualité qu'un reel doit respecter
- [examples/](examples/) : un projet exemple (`sujets.json`, `brief.txt`) et [clients/exemple-plancher.json](clients/exemple-plancher.json)

---

## Ce que fait le pipeline

| Étape | Outil | Résultat dans le dossier du sujet |
|---|---|---|
| 1. normalize | FFmpeg (VideoToolbox), LUT S-Log3 détectée seule | `rush_1080.mp4` (1080 × 1920, 30 i/s) |
| 2. cut | auto-editor | `rush_cut.mp4` (silences retirés) |
| 3. transcribe | mlx-whisper large-v3-turbo, deuxième passe sur les trous | `words.json` (chaque mot horodaté) |
| 4. edito | modèle de langue au choix (Claude, Gemini, OpenAI, Ollama...) | `edit.json` (corrections, pages, b-roll, coupes, accroche) |
| 5. broll | b-roll du client, photos de son catalogue, sinon Pexels | `broll/`, `broll.json` |
| 6. compose | gabarit HTML HyperFrames | `comp/index.html` |
| 7. render | HyperFrames, puis loudnorm | `out/<client>/AAAA-MM_Titre.mp4` |

Chaque étape est mise en cache : relancer reprend là où le dernier fichier manque. Pour refaire une
étape, effacer son fichier de sortie et relancer.

---

## Installation (macOS, puce Apple)

Prérequis : macOS sur puce Apple (M1 et plus), [Homebrew](https://brew.sh), Google Chrome,
[nvm](https://github.com/nvm-sh/nvm).

```bash
git clone https://github.com/Balgio-ca/video-editor.git
cd video-editor
brew install ffmpeg uv
nvm install            # Node 22, version fixée dans .nvmrc
npm install            # HyperFrames, le moteur de rendu
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env   # puis remplir les clés (voir plus bas)
```

Vérifier :

```bash
.venv/bin/python pipeline/reel.py --help
nvm use && npx hyperframes --version
```

La transcription utilise mlx-whisper, qui tourne seulement sur puce Apple. Sur Linux ou Windows,
remplacer `step_transcribe` dans `pipeline/reel.py` par faster-whisper ou whisper.cpp (même format de
sortie : une liste de mots avec `text`, `start`, `end`).

---

## Choisir le modèle de langue

Seule l'étape édito appelle un modèle de langue : il lit la transcription et décide des coupes, des
pages de sous-titres, du b-roll et de l'accroche. Tout le reste tourne en local.

| `LLM_PROVIDER` ou `--llm` | Clé dans `.env` | Modèle par défaut |
|---|---|---|
| `claude-cli` (défaut) | aucune : installer [Claude Code](https://claude.com/claude-code) et faire `claude login` une fois | `sonnet` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` |
| `gemini` | `GEMINI_API_KEY` ([clé gratuite](https://aistudio.google.com/apikey)) | `gemini-2.5-pro` |
| `openai` | `OPENAI_API_KEY` | `gpt-4.1` |

Le fournisseur `openai` accepte tout service compatible avec l'API OpenAI grâce à `OPENAI_BASE_URL` :

```bash
# Ollama en local, sans clé
OPENAI_BASE_URL=http://localhost:11434/v1 LLM_PROVIDER=openai LLM_MODEL=qwen3:32b \
  .venv/bin/python pipeline/rendre.py mon-projet promo-hiver --jusqua edito
```

Le modèle se change avec `LLM_MODEL` ou `--model`. Un petit modèle suit mal la consigne (index de mots,
pages de 3 mots au plus) : le pipeline refuse alors l'édito avec un message d'erreur.

---

## Tutoriel : un premier reel

### 1. Le profil du client

Copier [clients/_template.json](clients/_template.json) en `clients/<client>.json` (exemple complet :
[clients/exemple-plancher.json](clients/exemple-plancher.json)). Les champs qui comptent le plus :

- `noms_propres` : les noms que Whisper doit bien écrire (commerce, rues, marques).
- `couleur_marque` : la couleur des mots clés des sous-titres.
- `cta_court` : l'appel à l'action affiché à la fin, un `*mot*` en couleur.
- `carte_fin.fichier` : une vidéo de carte de fin (logo, adresse) collée à la fin.
- `broll.pexels_contexte` : des mots-clés anglais du métier, pour la recherche Pexels.

### 2. Le projet et ses sujets

```
work/mon-projet/
  sujets.json
  promo-hiver/
    brief.txt          facultatif : consignes pour l'édito
    src/C0040.MP4      les rushs
    src/C0041.MP4
```

`work/mon-projet/sujets.json` (exemple complet : [examples/sujets.json](examples/sujets.json)) :

```json
{
  "_projet": {"client": "exemple-plancher", "mois": "2026-11"},
  "promo-hiver": {"rushs": ["C0040.MP4", "C0041.MP4"], "motif": "Promo-Hiver"}
}
```

- `motif` : début du nom du fichier final (`out/exemple-plancher/2026-11_Promo-Hiver-....mp4`).
- `langue` : `fr` (défaut) ou `en`.
- `lut` : `auto` (détecte le S-Log3), `none` pour garder l'image plate.
- `rotation` : `auto`, `none`, `cw` ou `ccw` si la caméra a mal noté l'orientation.
- Un rush avec un `/` est relatif au dossier du projet : plusieurs sujets peuvent tirer chacun leur
  extrait d'une même entrevue (`"rushs": ["../entrevue/src/C0032.MP4"]`, avec une consigne d'extrait
  dans le `brief.txt` de chaque sujet, voir [examples/brief.txt](examples/brief.txt)).

### 3. Lancer

```bash
set -a; source .env; set +a
.venv/bin/python pipeline/rendre.py mon-projet promo-hiver --broll
```

Le reel sort dans `out/exemple-plancher/`. Pour un lot complet, l'édito de tous les sujets d'abord,
puis chaque rendu :

```bash
.venv/bin/python pipeline/rendre.py mon-projet --tous --jusqua edito
.venv/bin/python pipeline/rendre.py mon-projet --tous --broll
```

### 4. Contrôler

```bash
.venv/bin/python pipeline/controle.py mon-projet promo-hiver --ecoute
# out/exemple-plancher/2026-11_Promo-Hiver-....mp4 : 34.5 s, -14.1 LUFS, accroche 3.500 s, 3 b-roll
# work/mon-projet/check_promo-hiver.jpg
# ÉCOUTE : (la retranscription du montage, pour repérer un mot mangé par une coupe)
```

La planche `check_<sujet>.jpg` montre l'accroche, le milieu de chaque b-roll, la chute et la carte de fin.

### 5. Retoucher

```bash
.venv/bin/python pipeline/plan.py mon-projet promo-hiver   # transcription indexée, coupes, b-roll
```

Modifier `work/mon-projet/promo-hiver/edit.json`, puis relancer `rendre.py` (sans `--broll` si les
fenêtres de b-roll n'ont pas bougé). Quelques retouches courantes, toutes décrites dans
[docs/EDIT.md](docs/EDIT.md) :

```json
"coupes":   [{"debut_mot": 223, "fin_mot": 224, "raison": "« en fait » de remplissage"}],
"corrections": {"258": "dégât"},
"broll":    [{"debut_mot": 256, "fin_mot": 259, "source": "pexels-id:7681545"}],
"voix_off": [{"debut_mot": 199, "fin_mot": 221, "effet": "telephone"}],
"verdicts": [{"mot": 222, "type": "faux"}]
```

Pour choisir un b-roll Pexels à l'œil :

```bash
.venv/bin/python pipeline/pexels_candidats.py /tmp/px "eau=water leak floor" "chat=cat on wood floor"
# écrit /tmp/px/_candidats.jpg : une rangée par recherche, l'id Pexels sur chaque vignette
```

---

## Les outils

| Script | Usage |
|---|---|
| `pipeline/rendre.py <projet> <sujet>` | monte un sujet ; `--broll`, `--jusqua <étape>`, `--tous`, `--llm`, `--model`, `--verbeux` |
| `pipeline/reel.py` | le pipeline lui-même, utilisable sans projet (`--help`) |
| `pipeline/controle.py <projet> <sujet> [--ecoute]` | durée, LUFS, planche de contact, retranscription du montage |
| `pipeline/plan.py <projet> <sujet>` | la carte pour retoucher `edit.json` |
| `pipeline/broll_usage.py <projet>` | combien de fois chaque b-roll sert dans le lot |
| `pipeline/pexels_candidats.py <dossier> "tag=requête"...` | planche de vignettes Pexels |
| `pipeline/apercu.sh <reel.mp4>` | copie 720p de moins de 30 Mo pour un téléphone |
| `pipeline/fusion_elisions.py <projet> <sujet>` | recolle les élisions séparées par Whisper (« l » + « 'eau ») |
| `pipeline/archive_broll.sh <sortie> <source>...` | convertit des rushs d'archive (dossier local ou `hôte:/chemin`) en b-roll 1080 |
| `pipeline/planche_clips.py <dossier> [pas]` | planche de vignettes d'un dossier de clips |
| `pipeline/make_slog3_lut.py` | régénère la LUT S-Log3 vers Rec.709 |

### Le b-roll du client

Les clips et photos du client se rangent dans `work/<client>/assets/broll/` avec un `index.json` qui
les décrit, pour que l'édito sache quoi choisir :

```json
[
  {"id": "planches-empilees", "file": "planches-empilees.mp4", "type": "video", "duree": 11.4,
   "description": "Planches de bois franc empilées contre un mur, lent panoramique.",
   "tags": ["bois franc", "stock", "entrepôt"]}
]
```

Les photos du catalogue du client vont dans `work/<client>/assets/produits/index.json` (ids `site-...`) :
quand la personne nomme un produit, l'édito montre la vraie photo plutôt qu'un plan générique.

---

## Ce qui n'est pas dans le dépôt

`work/`, `out/`, `.env` et les profils de vrais clients restent sur la machine (`.gitignore`) : ce sont
des données de clients et des secrets. Seuls `clients/_template.json` et l'exemple fictif sont versionnés.

## Composants tiers

Voir [THIRD_PARTY.md](THIRD_PARTY.md) : polices Montserrat et Caveat (SIL Open Font License),
modèles de détection de visage d'OpenCV, et les dépendances installées par `requirements.txt` et `npm`.
