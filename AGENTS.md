# Guide pour l'agent IA

Ce dépôt est conçu pour être piloté par un agent de code (Claude Code, Codex, Gemini CLI, Cursor...).
La personne décrit ce qu'elle veut en langage courant (« monte les rushs du dossier X en reels »,
« la coupe après la question est trop sèche », « mets du b-roll de souris ») ; l'agent lance les
scripts, regarde le résultat, retouche `edit.json` et relance. Ce fichier dit comment bien faire ce travail.

## Prise en main

1. Lire [README.md](README.md) (installation, commandes), [docs/EDIT.md](docs/EDIT.md) (tous les
   réglages de retouche) et [STANDARDS.md](STANDARDS.md) (règles de qualité).
2. Lancer `python pipeline/diagnostic.py` (avec le Python du `.venv`) et corriger chaque point
   « À FAIRE » avec la commande qu'il donne, avant toute autre chose.
3. Un lot de reels = un projet `work/<projet>/` avec `sujets.json`, un dossier par sujet et ses
   rushs dans `<sujet>/src/`. Le profil du client est dans `clients/<client>.json` (partir de
   `clients/_template.json` ; demander à la personne le nom, la couleur, l'adresse, le téléphone,
   les noms propres et l'appel à l'action plutôt que de les inventer).
4. Pour un nouveau dossier de rushs : `python pipeline/nouveau_projet.py <projet> --client <client>
   --mois AAAA-MM <dossier>`, puis remplir le `brief.txt` de chaque sujet si la personne a donné des consignes.

## Le cycle de travail

```bash
python pipeline/rendre.py <projet> --tous --jusqua edito     # édito de tout le lot
python pipeline/rendre.py <projet> <sujet> --broll           # rendu d'un sujet
python pipeline/controle.py <projet> <sujet> --ecoute        # contrôle
python pipeline/apercu.py out/<client>/<fichier>.mp4         # copie légère à montrer
```

Travailler **un sujet à la fois** : rendre, contrôler soi-même, montrer, attendre le retour, corriger,
puis passer au suivant. Ne jamais livrer un reel sans l'avoir contrôlé.

## Contrôler soi-même avant de montrer

Le contrôle automatique ne juge ni le sens d'une image ni le ressenti d'une coupe. Pour chaque reel :

1. `controle.py --ecoute` : lire la retranscription du montage d'un bout à l'autre. Un mot manquant,
   un « euh » ou un souffle au début, une phrase qui ne se tient plus = une coupe à revoir.
2. Ouvrir la planche `work/<projet>/check_<sujet>.jpg` (accroche, milieu de chaque b-roll, fin) :
   chaque b-roll doit montrer littéralement ce qui est dit à ce moment.
3. Relire la liste complète des sous-titres affichés :
   ```bash
   python -c "import re,sys;s=open(sys.argv[1]).read();print(' | '.join(re.sub(r'<[^>]+>','',c) for c in re.findall(r'<div id=\"cap\d+\"[^>]*>(.*?)</div>',s)))" work/<projet>/<sujet>/comp/index.html
   ```
   Chercher : élision seule (« l' », « c' »), nombre coupé, mot seul sur une page en fin de phrase,
   faute dans un nom propre, valeur fausse (« 3000 mètres » pour « 3 mm »).
4. Pour une jonction douteuse, extraire une image ou le son autour du temps avec FFmpeg et regarder.

## Placer une coupe au bon endroit

La transcription place parfois mal un mot : un « euh », un souffle ou un claquement de lèvres reste
collé au mot suivant. On regarde alors le son et on coupe en secondes :

```bash
python pipeline/ecouter.py <projet> <sujet> 545.4 546.5
```

Il affiche l'enveloppe (niveau de 0 à 1 toutes les 30 ms), les mots de `words.json` et une réécoute
fraîche du passage. La voix est au-dessus de 0,3 ; un souffle ou un murmure vers 0,1 ; le silence sous
0,05. On pose la coupe dans le creux juste avant l'attaque du mot gardé, avec `debut_s` / `fin_s` (voir
[docs/EDIT.md](docs/EDIT.md#coupes--coupes)), puis on efface `talk.mp4` et `talk.segs.json` et on relance.

## Règles de montage apprises en production

- **Débuts serrés** : le reel part sur l'attaque de la voix et sur le visage, sans respiration, sans
  « OK », « donc », « euh » ni « question numéro 2 ». **Fins sèches** sans couper la dernière syllabe.
- **Ne jamais couper l'explication** : les mots qui font passer de la croyance à la réponse
  (« malheureusement », « parce que », « tout de suite ») et les bouts d'histoire (« puis finalement
  il revient me dire... ») restent. Couper les faux départs, les reprises, les échanges avec l'équipe.
  En cas de doute, garder : la personne dira « il manque une explication » bien plus souvent que
  « c'est trop long ».
- **Meilleure prise** : quand une phrase est dite plusieurs fois, comparer les prises et garder la plus
  claire, souvent la dernière.
- **B-roll littéral** : l'image montre ce qui est dit (une flaque pour « dégât d'eau », un chat pour
  « urine de chat »). Un produit nommé se montre avec la photo du catalogue du client. Pas de plan dont
  un texte lisible contredit le propos (un formulaire « HOME INSURANCE » sur « soumission »). Si rien
  ne colle, garder le visage : la personne qui montre quelque chose dans le cadre vaut mieux qu'un plan générique.
- **Jamais un éclair de visage** : moins de 1,5 s de visage entre deux b-roll, on enchaîne b-roll à
  b-roll (le pipeline le fait, vérifier quand même).
- **Variété** : un clip Pexels une seule fois par série, un clip du client trois fois au plus
  (`python pipeline/broll_usage.py <projet>`). Choisir un Pexels à l'œil avec `pexels_candidats.py`.
- **Question hors champ** : toute question posée derrière la caméra passe en `voix_off` effet téléphone,
  sans nom affiché. Pour savoir qui parle, comparer la hauteur de voix ou repérer un « tu » adressé à la
  personne filmée ; l'image seule trompe.
- **Verdicts** : dans une série vrai ou faux / red flag green flag, le verdict plein écran tombe sur le
  mot où la personne tranche (`verdicts`), mitigé quand elle répond « oui et non ».
- **Sous-titres** : 3 mots au plus, jamais un mot seul en fin de phrase, nombres en chiffres (« 5000 $ »,
  « 2 ¼ », « 5-6 pouces »), noms propres corrects.
- **Couleur** : image naturelle, pas saturée. Un rush S-Log mal éclairé se garde plat (`"lut": "none"`)
  avec un léger `grade` manuel plutôt qu'une LUT qui donne des couleurs criardes.
- Les autocollants et les images ajoutés doivent être libres de droits.

## Habillage et son

- Sons posés à la main : `"sons"` dans `edit.json`, par nom de fichier (banque fournie, `sons/`,
  `assets/sons/` du client). Un son par moment fort, pas plus : le pipeline en pose déjà sur les
  b-roll et les encadrés.
- Cartes de titre (`"cartes"`) pour séparer les parties d'un reel en plusieurs questions ou étapes.
- Carte de fin : `"carte_fin": {"type": "auto"}` dans le profil si le client n'a pas de vidéo de fin.
- Musique : toujours sous la voix ; `"mix": {"ducking": true}` la fait s'effacer pendant la parole.
  Vérifier à l'écoute qu'on comprend chaque mot. Une musique qui monte en fin de reel sonne gabarit :
  garder un niveau stable avec un seul fondu de sortie.

## Générer par IA

`pipeline/generer.py` crée une voix off, un effet sonore, une musique (ElevenLabs), une image ou une
vidéo de b-roll (OpenAI, Gemini).

- Ces générations coûtent de l'argent chez le fournisseur : **annoncer ce qui sera généré et attendre
  l'accord de la personne** avant de lancer, sauf si elle l'a déjà demandé explicitement.
- Ordre de préférence pour le b-roll : clip ou photo du client, photo de son catalogue, Pexels choisi
  à l'œil, et seulement ensuite une image ou une vidéo générée.
- **Jamais** d'image générée pour un produit, un lieu ou une personne réels du client : ce serait
  trompeur. Une image générée illustre une situation générale (un sous-sol inondé, une fête d'enfant).
- Pour un jingle de 2-3 s, `generer.py son` réussit mieux que `generer.py musique`.
- Une image générée devient `local:gen-<nom>` ; la regarder avant de l'utiliser (texte illisible,
  mains déformées, éléments incohérents = la refaire ou s'en passer).

## Ce qu'il ne faut pas faire

- Ne jamais versionner `work/`, `out/`, `.env` ni un vrai profil client : ce sont des données privées.
- Ne pas modifier `words.json` à la main sauf pour recaler un temps de mot (`start`, `end`) ; le texte
  affiché se corrige dans `corrections` d'`edit.json`.
- Ne pas relancer l'édito (effacer `edit.json`) pour une petite retouche : modifier `edit.json`.
- Ne rien publier ni envoyer pour la personne sans son accord explicite.
