# 🎬 SubSync Tool

**Télécharge, extrait et synchronise automatiquement les sous-titres pour toutes vos séries et films.**

Le pipeline automatique garantit des sous-titres parfaitement calés sur l'audio, quel que soit le framerate ou la source vidéo.

```
🎬 Vidéo
  │
  ├─ .srt déjà présent ?      → 🔧 alass (synchro)    → ✅ video.fr.srt
  ├─ Sous-titres dans le MKV ? → 📤 ffmpeg (extraction) → 🔧 alass → ✅ video.fr.srt
  └─ Aucun sous-titre ?       → 🌐 subliminal (DL)     → 🔧 alass → ✅ video.fr.srt
```

---

## 🚀 Installation rapide

```bash
git clone https://github.com/votre-org/subsync-tool.git ~/.subsync-tool
cd ~/.subsync-tool
./install.sh
```

L'installeur vérifie les prérequis, télécharge `alass`, installe les dépendances Python, crée la configuration par défaut et ajoute les alias shell.

**Prérequis** : `python3`, `pip`, `ffmpeg`, `curl` ou `wget`.

### Variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `SUBSYNC_HOME` | `~/.subsync-tool` | Dossier d'installation |
| `SUBSYNC_MEDIA_ROOT` | `~/media` | Racine des dossiers Films/Séries |

---

## 🖥️ Interface Web

Une interface web permet de piloter SubSync sans ligne de commande :

```bash
subsync-web                  # Lancer le serveur → http://localhost:5001
subsync-web --stop           # Arrêter le serveur
subsync-web --port 8080      # Changer le port
subsync-web --root /chemin   # Changer le dossier racine
subsync-web --debug          # Mode debug Flask
```

**Fonctionnalités :**
- 📊 Dashboard avec statistiques globales Films / Séries
- 🧭 Navigation Série → Saison → Épisodes
- 🔍 Actions (Scan, Force, Dry-Run) scopées à la vue courante
- 📋 Filtres par statut (✅ OK, ⚠️ Warning, ❌ Manquant, ✓ Validé, 🇫🇷 VF)
- ✓ Validation manuelle des sous-titres en 1 clic
- 🇫🇷 Marquage « Pas besoin de ST » pour les vidéos en VF ou sans dialogues
- ▶️ Lecture vidéo avec VLC en 1 clic
- 💻 Console avec logs en direct (SSE)
- ⚙️ Page de configuration (dossiers + clé API OpenSubtitles)
- ❓ Panneau d'aide latéral (touche `?`)
- 🔧 Assistant d'installation automatique sur la page d'accueil

---

## 📦 Architecture

```
$SUBSYNC_HOME/
├── subsync.sh               ← CLI (bash)
├── alass                    ← Binaire de synchronisation (v2.0+)
├── repair_srt.py            ← Réparation SRT corrompus
├── add_warning.py           ← Avertissement dans les .srt
├── install.sh               ← Script d'installation
├── .gitignore
├── LICENSE                  ← MIT
│
├── README.md                ← Documentation utilisateur
├── docs/
│   └── DEVELOPMENT.md       ← Documentation technique + API + suivi
│
└── web/                     ← Interface web
    ├── server.py            ← Serveur Flask (16 routes)
    ├── scanner.py           ← Scan du filesystem
    ├── config.example.json  ← Exemple de configuration
    ├── requirements.txt     ← flask
    ├── templates/
    │   └── index.html       ← SPA
    └── static/
        ├── style.css        ← Thème Catppuccin Mocha
        └── app.js           ← Logique frontend
```

---

## 🚀 Utilisation CLI

```bash
# Scanner et traiter un dossier
subsync ~/media/Series/

# Forcer le retéléchargement
subsync --force ~/media/Series/The\ Boys/

# Vérifier ce qui manque sans rien télécharger
subsync --dry-run ~/media/

# Télécharger des sous-titres anglais sans synchro
subsync --lang eng --no-sync ~/media/Films/

# Valider un sous-titre vérifié correct
subsync --validate "Normal.People.S01E01.720p.STAN.WEBRip.x264-GalaxyTV"

# Lister les sous-titres validés
subsync --list-validated
```

### Options

| Option | Description |
|--------|-------------|
| `--force` | Retélécharge et resynchronise même si un `.srt` existe déjà |
| `--no-sync` | Désactive la synchronisation alass |
| `--lang CODE` | Code langue IETF (défaut : `fra` = français) |
| `--dry-run` | Affiche ce qui serait fait sans rien modifier |
| `--validate "NOM"` | Marque un sous-titre comme vérifié |
| `--unvalidate "NOM"` | Retire la validation manuelle |
| `--list-validated` | Liste les sous-titres validés |
| `--help` | Affiche l'aide |

---

## ⚙️ Fonctionnement

### Pipeline de traitement

1. **Détection** — pour chaque vidéo, le script vérifie si un `.fr.srt` existe
2. **Acquisition** — sous-titres embarqués (MKV) extraits via `ffmpeg`, ou téléchargement via `subliminal` (OpenSubtitles.com + providers gratuits)
3. **Synchronisation** — `alass` aligne le texte avec l'audio par reconnaissance vocale, corrige les différences de framerate
4. **Vérification** — l'écart entre le dernier dialogue et la fin de la vidéo est mesuré
5. **Nommage** — le sous-titre final est `<video>.fr.srt`, chargé automatiquement par tous les lecteurs

### Alertes de synchronisation

Si l'écart dépasse 10 secondes, un avertissement est ajouté au début du `.srt` et un fichier `subsync-warnings.txt` est généré.

Pour valider un sous-titre que tu as vérifié correct :
```bash
subsync --validate "Nom de l'épisode"
```

---

## 🔧 Configuration

### Dossiers de médias

Éditer `$SUBSYNC_HOME/web/config.json` ou utiliser la page Configuration de l'interface web :

```json
{
  "films_path": "/chemin/vers/Films",
  "series_path": "/chemin/vers/Series"
}
```

### Clé API OpenSubtitles

```toml
# ~/.config/subliminal/subliminal.toml
[provider.opensubtitlescom]
apikey = "votre-cle-api"
```

La clé est aussi modifiable depuis la page Configuration de l'interface web.

### Planification (cron)

```bash
# Tous les jours à 3h
0 3 * * * $HOME/.subsync-tool/subsync.sh "$HOME/media/Series/" >> /tmp/subsync-cron.log 2>&1
```

---

## 🐛 Dépannage

| Problème | Solution |
|----------|----------|
| `alass échoué (code 1)` | Sous-titre mal formé → réparation automatique tentée |
| `Téléchargement impossible` | Vérifier la clé API OpenSubtitles ou trouver un .srt manuellement |
| `[SYNC] Écart détecté` | Le sous-titre ne correspond pas à cette version (PAL vs NTSC). Vérifier puis `--validate` |
| `ratio FPS: 25` | Différence de framerate détectée, correction automatique appliquée |

---

## 📄 Licence

MIT — voir [LICENSE](LICENSE).

## 🤝 Contribuer

Les contributions sont les bienvenues. Consulter [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) pour l'architecture, l'API et le suivi du projet.
