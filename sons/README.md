# Vos effets sonores

Déposez ici vos propres sons (`.mp3`, `.wav`, `.m4a` ou `.ogg`) : ils deviennent utilisables par leur
nom de fichier, sans l'extension, partout où `edit.json` attend un son.

```json
"sons":     [{"mot": 57, "fichier": "caisse", "volume": 0.4}],
"stickers": [{"mot": 57, "svg": "fleur-de-lys", "sfx": "caisse"}]
```

Un son propre à un client va plutôt dans `work/<client>/assets/sons/`. Un son de ce dossier remplace
un son de la banque fournie qui porte le même nom (`whoosh`, `pop`, `ping`, `chime`, `impact-bass-1`...).

Pour en créer un avec ElevenLabs :

```bash
python pipeline/generer.py son "petit ding de caisse enregistreuse" --nom caisse --duree 1
```

N'ajoutez que des sons dont vous avez les droits. Ce dossier n'est pas versionné, sauf ce fichier.
