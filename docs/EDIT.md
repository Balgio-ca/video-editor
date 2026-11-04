# Retoucher un reel : référence de `edit.json`

L'étape édito écrit `work/<projet>/<sujet>/edit.json`. C'est le plan de montage : chaque retouche se
fait en modifiant ce fichier, puis en relançant le rendu :

```bash
.venv/bin/python pipeline/rendre.py <projet> <sujet>          # composition et rendu
.venv/bin/python pipeline/rendre.py <projet> <sujet> --broll  # si les fenêtres de b-roll ont changé
```

Tout est repéré par **index de mot** dans `words.json`. Pour les voir :

```bash
.venv/bin/python pipeline/plan.py <projet> <sujet>
# TRANSCRIPTION : 0:Le 1:client 2:arrive 3:mais 4:il 5:n'a 6:pas 7:ses 8:mesures 9:Ça 10:c'est ...
```

Les temps (`debut_s`, `fin_s`, `t`) sont en secondes : dans le **rush** pour les coupes, dans le
**reel monté** pour les verdicts posés à un temps. Après une modification des coupes ou des voix,
effacer `talk.mp4` et `talk.segs.json` pour forcer le réassemblage de la piste parlée.

---

## Coupes : `coupes`

Plages de mots retirées du montage.

```json
"coupes": [
  {"debut_mot": 0, "fin_mot": 40, "raison": "avant la question"},
  {"debut_mot": 223, "fin_mot": 224, "raison": "« en fait » de remplissage"}
]
```

La coupe se pose seule dans le creux sonore le plus proche : 120 ms d'air après le dernier mot gardé,
reprise à l'attaque de la voix du mot suivant. Quand la transcription a mal placé un mot (une
respiration ou un « euh » collé au mot suivant), on impose les bornes en secondes :

```json
{"debut_mot": 0, "fin_mot": 1756, "debut_s": 0.0, "fin_s": 546.11, "raison": "le « euh » avant la question"}
```

Pour retirer un bruit **entre** deux mots sans retirer de mot, on met `debut_mot` plus grand que
`fin_mot` (plage de mots vide) et on donne les secondes :

```json
{"debut_mot": 1411, "fin_mot": 1410, "debut_s": 438.10, "fin_s": 438.72, "raison": "claquement de lèvres avant « Oui »"}
```

Pour trouver le bon temps, regarder l'enveloppe sonore autour du mot (`reel.load_envelope`) ou
retranscrire un court extrait du rush avec Whisper.

**Règle d'or** : couper les faux départs, les reprises et les échanges avec l'équipe, jamais les mots
qui portent l'explication (« malheureusement », « parce que », « tout de suite ») : sans eux la
réponse perd son sens.

## Extrait : `extrait`

Pour une longue entrevue, l'édito choisit un passage ; tout ce qui est avant et après devient une coupe.

```json
"extrait": {"debut_mot": 199, "fin_mot": 358, "sujet": "vinyle au sous-sol"}
```

## Corrections de sous-titres : `corrections`

Remplace le texte affiché d'un mot. Une chaîne vide masque le mot (utile pour fusionner).

```json
"corrections": {
  "258": "dégât",
  "280": "Saint-Laurent", "281": "",
  "972": "5000 $", "973": ""
}
```

## Pages de sous-titres : `pages`

Groupes de 1 à 3 mots affichés ensemble, dans l'ordre, qui couvrent tous les mots gardés.

```json
"pages": [
  {"mots": [41, 42, 43], "style": "normal"},
  {"mots": [53, 54], "style": "box"},
  {"mots": [893, 894], "style": "big"},
  {"mots": [65, 66], "style": "script"}
]
```

| Style | Rendu |
|---|---|
| `normal` | blanc gras sur bandeau sombre, le mot prononcé en couleur de marque |
| `big` | mot clé en gros, couleur de marque |
| `box` | promesse, prix ou date dans un cadre arrondi (3 fois au plus par reel) |
| `script` | interjection en cursive |
| `barre` | titre plein écran barré d'un X rouge ; `"x_mot": 57` fait tomber le X sur un autre mot |

Une page de plus de 3 mots est refusée. Éviter un mot seul en fin de phrase : regrouper plutôt
« pas installer tel | ou tel produit » que « tel ou tel | produit ».

## Accroche : `accroche`

Titre en haut de l'image au début du reel. Un mot entre `*étoiles*` prend la couleur de marque.

```json
"accroche": {"texte": "Vrai ou faux : du *vinyle* au sous-sol, c'est mieux?", "fin_mot": 216}
```

`fin_mot` : dernier mot pendant lequel l'accroche reste (3,5 s au moins). `debut` (secondes) la fait
attendre la fin d'une intro plein écran : `"debut": 2.4`.

## B-roll : `broll`

Fenêtres d'images posées par-dessus la voix.

```json
"broll": [
  {"debut_mot": 256, "fin_mot": 259, "source": "pexels-id:7681545", "pourquoi": "de l'eau qui coule sur un plancher"},
  {"debut_mot": 303, "fin_mot": 310, "source": "local:site-tfspc-102", "pourquoi": "photo du catalogue : vinyle à clic"},
  {"debut_mot": 432, "fin_mot": 443, "source": "local:archive-mains-epaisseur-planches", "duree": 2.5, "debut_source": 4.0}
]
```

| Source | Quoi |
|---|---|
| `local:<id>` | clip ou photo du client indexé dans `work/<client>/assets/broll/index.json`, ou photo du catalogue (`assets/produits/index.json`, ids `site-...`) |
| `pexels-id:<n>` | un clip Pexels précis (choisi avec `pexels_candidats.py`) |
| `pexels:<requête>` | le premier résultat Pexels pour cette recherche |

Options : `duree` (secondes) impose la longueur, `debut_source` le point d'entrée dans le clip.

Le pipeline arrange les fenêtres : jamais deux en chevauchement, et jamais moins de 1,5 s de visage
entre deux b-roll (il raccourcit la fenêtre ou l'enchaîne à la suivante). Bonnes pratiques : une image
littérale de ce qui est dit, la photo du produit quand un produit est nommé, un clip Pexels une seule
fois par série, un clip du client trois fois au plus (`broll_usage.py <projet>` compte).

## Impacts : `impacts`

```json
"impacts": [{"mot": 224, "type": "punch"}, {"mot": 1070, "type": "impact"}]
```

`punch` : coup de zoom sur le visage avec un whoosh. `impact` : en plus, la page devient un gros titre
plein écran (à éviter sur une page de 3 mots, elle se coupe sur deux lignes).

## Voix hors champ en effet téléphone : `voix_off`

La question posée derrière la caméra passe en voix téléphone, avec des sous-titres sur fond blanc.

```json
"voix_off": [{"debut_mot": 199, "fin_mot": 221, "effet": "telephone"}]
```

`nom` ajoute une étiquette au-dessus du sous-titre (`"nom": "Caméraman"`). `image_de: [t0, t1]`
remplace l'image par un autre passage du rush (en secondes), étiré à la durée de la voix.

## Pré-ouverture : `preroll`

Un son fourni (jingle, question enregistrée à part) joué avant le montage, sur un passage du rush.

```json
"preroll": {
  "audio": "work/exemple-plancher/assets/voix/jingle-rf/intro-rf.wav",
  "image_de": "avant",
  "sous_titres": false
}
```

`image_de` : `"avant"` (les secondes du rush juste avant la reprise) ou `[t0, t1]`. Autres clés :
`duree`, `gain`, `style` (`tel` par défaut), `nom`, `corrections` (sur la transcription du son),
`sous_titres: false` pour ne rien afficher. Tous les temps du reel sont décalés de la durée du son.

## Verdicts plein écran : `verdicts`

Écran de couleur animé qui claque au moment où la personne tranche : balayage, icône qui se dessine,
mot géant, son.

```json
"verdicts": [
  {"mot": 222, "type": "faux"},
  {"mot": 381, "type": "vrai"},
  {"mot": 561, "type": "mitige"},
  {"mot": 1411, "type": "mitige", "texte": "<span class=\"vd-v\">OUI</span><span class=\"vd-e\">ET</span><span class=\"vd-x\">NON</span>"},
  {"mot": 53, "type": "green"},
  {"mot": 316, "type": "red"}
]
```

| Type | Écran |
|---|---|
| `vrai` | vert, crochet, petit saut |
| `faux` | rouge, X, tremblement |
| `mitige` | moitié vert, moitié rouge, « VRAI ET FAUX » (`texte` pour « OUI ET NON », « GREEN OU RED »...) |
| `green` / `red` | drapeau qui claque, « GREEN FLAG » / « RED FLAG » |

Options : `duree` (1,3 s par défaut), `t` (secondes dans le reel monté, au lieu de `mot`), `sfx: false`
pour couper le son du verdict.

Intro d'une série en deux écrans sur un jingle, sans voix :

```json
"preroll": {"audio": "…/intro-rf.wav", "image_de": "avant", "sous_titres": false},
"verdicts": [
  {"t": 0.0, "type": "green", "duree": 1.3, "sfx": false},
  {"t": 1.15, "type": "red", "duree": 1.3, "sfx": false},
  {"mot": 53, "type": "green"}
],
"accroche": {"texte": "Il arrive sans ses *mesures* : red flag ou green flag?", "fin_mot": 48, "debut": 2.4}
```

## Autocollants : `stickers`

Une image qui surgit sur un mot, avec un son.

```json
"stickers": [
  {"mot": 57, "svg": "fleur-de-lys", "sfx": "ping"},
  {"mot": 233, "svg": "souris", "anim": "traverse", "duree": 1.6},
  {"mot": 240, "svg": "mon-perso", "anim": "entree", "duree": 2.2}
]
```

`svg` : nom d'un fichier `.svg` ou `.png` de `templates/balgio-reel/stickers/`. `anim` : par défaut un
pop en haut à droite, `traverse` (court le long du bas de l'image), `entree` (entre par la droite, se
penche, ressort). N'utiliser que des images dont on a les droits.

## Étalonnage : `grade`

```json
"grade": {"cible": 112, "saturation": 0.85, "contraste": 1.0}
"grade": {"gamma": 0.98, "contraste": 1.3, "saturation": 1.4, "filtre": "colorbalance=rs=-0.08:bs=0.08"}
```

Sans `gamma`, le pipeline calcule la correction pour amener la luminance moyenne à `cible`. Avec
`gamma`, il l'applique tel quel. `filtre` : n'importe quel filtre FFmpeg appliqué avant. Pour un rush
S-Log3 à garder plat, mettre `"lut": "none"` dans `sujets.json`.

## Effets sonores posés à la main : `sons`

```json
"sons": [
  {"mot": 57, "fichier": "caisse", "volume": 0.4},
  {"t": 12.5, "fichier": "whoosh-cinematic", "decalage": -0.05}
]
```

Le pipeline pose déjà des sons tout seul (whoosh sur un b-roll, pop sur un encadré, verdicts), en
évitant qu'ils se marchent dessus. Un son de `sons` passe toujours. `fichier` est le nom sans
extension, cherché dans cet ordre : `work/<projet>/assets/sons/`, `work/<client>/assets/sons/`,
[`sons/`](../sons/README.md) à la racine, puis la banque fournie (`whoosh`, `whoosh-short`,
`whoosh-cinematic`, `pop`, `ping`, `chime`, `click`, `click-soft`, `sparkle`, `riser`, `impact-bass-1`,
`impact-bass-2`, `glitch-1`, `notification`, `typing`...). Le même nom marche dans `stickers` (`sfx`),
`cartes` (`son`) et les verdicts. Un son se crée avec `python pipeline/generer.py son "description" --nom caisse`.

## Cartes de titre : `cartes`

Un écran plein cadre à la couleur de marque, avec un titre et un sous-titre, pour séparer les parties
d'un reel (« Question 2 », « Étape 3 », « Avant / après »).

```json
"cartes": [
  {"mot": 359, "titre": "Question 2", "sous_titre": "L'ingénierie se sable?"},
  {"t": 0.0, "titre": "3 erreurs", "sous_titre": "à éviter avant de rénover", "duree": 2.0, "fond": "#111111"}
]
```

Options : `duree` (1,6 s), `fond` (couleur de marque), `couleur` du texte (blanc), `son` (`whoosh`),
`sfx: false` pour aucun son.

## Mixage : `mix`

Le mixage se règle dans le profil client (`"mix"`, pour tous ses reels) ou dans `edit.json` (pour un reel).

```json
"mix": {"ducking": true, "musique_voix": 0.4, "musique_fin": 0.55, "effets": 0.8, "lufs": -14}
```

| Clé | Rôle | Défaut |
|---|---|---|
| `ducking` | la musique baisse d'elle-même quand quelqu'un parle et remonte dans les pauses | `false` |
| `musique_voix` | niveau de la musique pendant la parole | 0,08 (0,4 avec le ducking) |
| `musique_fin` | niveau de la musique sur la carte de fin | 0,55 |
| `musique_lufs` | normalisation de la musique avant le mixage | -18 |
| `ducking_seuil`, `ducking_ratio` | sensibilité et force du ducking | 0,05 et 3 |
| `effets` | multiplie le volume de tous les effets sonores | 1,0 |
| `lufs` | volume final du reel | -14 (Instagram, TikTok) |

La musique elle-même se choisit dans le profil (`"musique": {"fichier": "..."}`), ou se crée avec
`python pipeline/generer.py musique "description" --sortie ... --duree 30`.

## Carte de fin générée

Dans le profil client, une carte de fin peut être une vidéo fournie ou se générer à partir du profil :

```json
"logo": "work/mon-client/assets/logo.png",
"carte_fin": {"type": "auto", "duree": 3.0, "fond": "#111111", "texte": "Passe nous voir cette semaine"}
```

La carte générée montre le logo (ou le nom du client sans logo), la phrase (`texte`, sinon
`cta_defaut`), le téléphone en couleur de marque, l'adresse et le site, avec une entrée animée.
`"telephone": false`, `"adresse": false` ou `"site": false` retirent une ligne. Pour une vidéo
fournie : `{"type": "video", "fichier": "work/mon-client/assets/END-CARD.mp4"}`.

## Médias générés par IA

Quand aucun plan du client ni de Pexels ne montre ce qui est dit, `pipeline/generer.py` crée le média
et l'ajoute au b-roll du client :

```bash
python pipeline/generer.py image "sous-sol inondé, eau sur un plancher de bois" --client mon-client --nom sous-sol
python pipeline/generer.py video "enfant qui souffle les bougies d'un gâteau" --client mon-client --nom bougies
```

```json
"broll": [{"debut_mot": 256, "fin_mot": 259, "source": "local:gen-sous-sol"}]
```

Une image générée s'anime en lent zoom, comme toute photo. Ne jamais générer un produit du client :
un produit nommé se montre avec sa vraie photo. Pour une voix off ou une question enregistrée :
`python pipeline/generer.py voix "texte" --sortie ...`, puis `preroll` ou `voix_off`.
