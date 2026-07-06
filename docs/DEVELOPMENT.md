# SubSync Tool — Documentation technique

> Dernière mise à jour : 2026-07-06

---

## Table des matières

1. [Architecture](#1--architecture)
2. [Stack et dépendances](#2--stack-et-dépendances)
3. [Pipeline de traitement](#3--pipeline-de-traitement)
4. [Modèle de données](#4--modèle-de-données)
5. [Spécifications de l'API](#5--spécifications-de-lapi)
6. [Spécifications UI/UX](#6--spécifications-uiux)
7. [Thème graphique](#7--thème-graphique)
8. [Points techniques notables](#8--points-techniques-notables)
9. [Bugs résolus](#9--bugs-résolus)
10. [Limitations connues et pistes](#10--limitations-connues-et-pistes)
11. [Commandes utiles](#11--commandes-utiles)
12. [Suivi du projet](#12--suivi-du-projet)

---

## 1 — Architecture

```
$SUBSYNC_HOME/ (~/.subsync-tool par défaut)
├── subsync.sh               ← Script maître CLI (bash, ~685 lignes)
├── alass                    ← Binaire Rust v2.0+ (synchro audio ↔ texte)
├── repair_srt.py            ← Réparation SRT corrompus (pysubs2)
├── add_warning.py           ← Avertissement dans le .srt (pysubs2)
├── install.sh               ← Script d'installation
├── .gitignore
├── LICENSE                  ← MIT
│
├── validated-subs.txt       ← Whitelist (généré)
├── no-sub-needed.txt        ← Vidéos sans besoin de ST (généré)
│
├── README.md                ← Documentation utilisateur
│
└── web/                     ← Interface web (Flask)
    ├── server.py            ← Serveur (13 REST + 1 SSE + 1 page = 16 routes)
    ├── scanner.py           ← Scan du filesystem (~775 lignes)
    ├── config.example.json  ← Exemple de configuration
    ├── requirements.txt     ← flask
    ├── templates/
    │   └── index.html       ← SPA
    └── static/
        ├── style.css        ← Thème Catppuccin Mocha (~990 lignes)
        └── app.js           ← Logique frontend (~1300 lignes)

~/.config/subliminal/
└── subliminal.toml          ← Clé API OpenSubtitles.com
```

---

## 2 — Stack et dépendances

### Stack

| Composant | Technologie |
|-----------|-------------|
| CLI | Bash 4+ |
| Backend Web | Python 3 + Flask 3.x |
| Frontend | HTML5 + CSS3 + Vanilla JS (SPA) |
| Temps réel | Server-Sent Events (SSE) |
| Synchro audio | alass (Rust, binaire externe) |
| Téléchargement ST | subliminal (Python) |

### Dépendances

| Composant | Version | Installation |
|-----------|---------|-------------|
| `bash` | ≥ 4.0 | Système |
| `ffmpeg` / `ffprobe` | système | `apt install ffmpeg` |
| `python3` | 3.12 | Système |
| `flask` | 3.1+ | `pip install flask` |
| `subliminal` | 2.6+ | `pip install subliminal` |
| `pysubs2` | 1.8+ | Dépendance de subliminal |
| `alass` | 2.0+ | Téléchargé par `install.sh` |

### Flux de données

```
Navigateur                    Serveur Flask                   Système
    │                              │                             │
    ├─ GET / ──────────────────────→│                             │
    │←─ HTML (SPA) ─────────────────│                             │
    │                              │                             │
    ├─ GET /api/tree ──────────────→│                             │
    │                              ├─ scanner.scan_tree() ──────→│
    │                              │←── arborescence + statuts ──│
    │←─ JSON ───────────────────────│                             │
    │                              │                             │
    ├─ POST /api/run {path, mode} ─→│                             │
    │                              ├─ subprocess.Popen() ───────→│
    │                              │        subsync.sh            │
    │←─ SSE: job_id ────────────────│                             │
    │←─ SSE: log line ─────────────│←─ stdout ──────────────────│
    │←─ SSE: done ─────────────────│ (process exit)              │
```

---

## 3 — Pipeline de traitement

```
Pour chaque vidéo (.mp4, .mkv, .avi, .mov, .webm) :

1. Sous-titre .fr.srt déjà présent ET pas --force ?
   → sync_with_alass() → check_sync_quality() → ✅

2. Sous-titres embedded dans le MKV ?
   → ffmpeg extraction (1er flux subtitle:fre)
   → sync_with_alass() → check_sync_quality() → ✅

3. Sinon :
   → subliminal download (OpenSubtitles.com + providers gratuits)
   → sync_with_alass() → check_sync_quality() → ✅
```

### sync_with_alass()

1. Réparation SRT via `repair_srt.py` (pysubs2 load/save pour normaliser)
2. `alass video.mkv input.srt output.srt`
3. Si échec → retry avec `--no-split` (transformation uniforme au lieu de découpage en blocs)
4. Si échec → conserve le sous-titre tel quel

### check_sync_quality()

1. Vérifie si la vidéo est whitelistée (`validated-subs.txt`) → skip
2. Compare le dernier timestamp utile du .srt avec la durée de la vidéo
3. Si écart > `SYNC_GAP_THRESHOLD` (10s par défaut) :
   - Ajoute un warning dans le .srt (8 premières secondes) via `add_warning.py`
   - Stocke dans `SERIES_WARNINGS[]` pour le rapport final
   - Écrit `subsync-warnings.txt`

### subliminal

- Provider principal : `opensubtitlescom` (API key configurée)
- Providers gratuits en fallback : gestdown, subtitulamos, tvsubtitles, addic7ed...
- Si un sous-titre embedded ou externe existe déjà → téléchargement skip
- Le mode `--force` supprime le .fr.srt existant avant de lancer

### Cache scanner (web)

- TTL de 30 secondes (modifiable via `CACHE_TTL` dans `scanner.py`)
- Invalidation manuelle via `POST /api/refresh` ou `scanner.clear_cache()`
- Les clés de cache incluent les chemins Films/Séries et l'option duration

---

## 4 — Modèle de données

### 4.1 VideoFile

```json
{
  "name": "Andor - S02E01.mkv",
  "stem": "Andor - S02E01",
  "path": "/media/Series/Andor/Saison 2/Andor - S02E01.mkv",
  "type": "episode",
  "series": "Andor",
  "season": "Saison 2",
  "has_srt": true,
  "srt_path": "/media/Series/Andor/Saison 2/Andor - S02E01.fr.srt",
  "status": "warning",
  "status_label": "⚠️ +0m34s",
  "warning_gap": "+0m34s",
  "warning_detail": "dernier sous-titre à 00:50:01 (vidéo: 3035s)",
  "is_validated": false,
  "is_ignored": false,
  "duration": "50:35",
  "duration_sec": 3035
}
```

### 4.2 Statuts

| Statut | Badge | Condition |
|--------|-------|-----------|
| `ok` | ✅ | `.fr.srt` présent, pas d'avertissement, pas whitelisté, pas ignoré |
| `warning` | ⚠️ | `.fr.srt` présent, avertissement, pas whitelisté, pas ignoré |
| `missing` | ❌ | Aucun `.fr.srt` trouvé, pas ignoré |
| `validated` | ✓ | Présent dans `validated-subs.txt` |
| `ignored` | 🇫🇷 | Présent dans `no-sub-needed.txt` (VF, muet…) |

**Priorité** : `validated` > `ignored` > `warning` > `ok` > `missing`

### 4.3 MediaTree

```json
{
  "films": {
    "videos": [ /* VideoFile */ ],
    "stats": { "total": 87, "ok": 80, "warning": 2, "missing": 5, "validated": 0, "ignored": 0 }
  },
  "series": {
    "series_list": [ /* SeriesNode */ ],
    "stats": { "total": 200, "ok": 175, "warning": 22, "missing": 3, "validated": 1, "ignored": 0 }
  },
  "films_path": "/media/Films",
  "series_path": "/media/Series",
  "scanned_at": "2026-07-06T21:00:00"
}
```

### 4.4 SeriesNode

```json
{
  "name": "Andor",
  "path": "/media/Series/Andor",
  "type": "series",
  "seasons": { "Saison 1": [/* episodes */], "Saison 2": [/* episodes */] },
  "season_names": ["Saison 1", "Saison 2"],
  "stats": { "total": 24, "ok": 0, "warning": 24, "missing": 0, "validated": 0, "ignored": 0 },
  "episode_count": 24
}
```

---

## 5 — Spécifications de l'API

### 5.1 GET /api/tree

Scan complet des dossiers Films et Séries.

- **Paramètres** : `?films_path=...&series_path=...&duration=1`
- `duration=1` : inclut les durées vidéo (ffprobe, plus lent)
- **Réponse** : `MediaTree` (voir §4.3)
- **Cache** : 30 secondes

### 5.2 GET /api/status

Statut détaillé d'un dossier.

- **Paramètre** : `?path=/media/Series/Andor/Saison 2/`
- **Réponse** : `{ "path": "...", "videos": [/* VideoFile */], "stats": {...} }`

### 5.3 GET /api/stats

Statistiques agrégées.

- **Paramètre** : `?path=/media/Series/Andor/`
- **Réponse** : `{ "total": 24, "ok": 0, "warning": 24, ... }`

### 5.4 GET /api/validated

- **Réponse** : `{ "files": ["Nom.mkv", ...], "count": 2 }`

### 5.5 GET /api/warnings

- **Réponse** : `{ "warnings": [{"file": "...", "gap": "...", "detail": "..."}], "count": 87 }`

### 5.6 GET/POST /api/config

- **GET** : retourne `{ "films_path": "...", "series_path": "...", "opensubtitles_apikey": "..." }`
- **POST** : body `{ "films_path": "...", "series_path": "...", "opensubtitles_apikey": "..." }` → sauvegarde dans `config.json` et `subliminal.toml`

### 5.7 POST /api/run

Lance une commande `subsync.sh`.

- **Body** :
```json
{
  "path": "/media/Series/Andor/",
  "mode": "scan"
}
```
- `paths` (liste) accepté comme alternative à `path`
- **Mode** : `"scan"` | `"force"` | `"dry-run"`
- **Réponse** : `{ "job_id": "abc12345", "command": "...", "path": "...", "mode": "scan", "started_at": "21:00:00", "status": "running", "ok": 0, "fail": 0 }`
- **Erreur** : `409` si un job est déjà en cours

### 5.8 GET /api/stream/<job_id>

Flux SSE des logs.

- **Events** :
  - `start` : `{"job_id": "abc12345"}`
  - `log` : `{"type": "log", "line": "[INFO] ...", "stream": "stdout"}`
  - `progress` : `{"type": "progress", "file": "▶ video.mkv"}`
  - `done` : `{"type": "done", "exit_code": 0, "message": "Terminé"}`
  - `error` : `{"type": "error", "message": "..."}`
  - Heartbeat : commentaire SSE toutes les 15s

### 5.9 POST /api/stop/<job_id>

- **Réponse** : `{ "status": "stopped" }` ou `404`

### 5.10 POST /api/validate

- **Body** : `{ "files": ["Andor - S02E01.mkv"] }`
- **Réponse** : `{ "added": 1, "total_validated": 5, "files": [...] }`

### 5.11 POST /api/unvalidate

- **Body** : `{ "files": ["Andor - S02E01.mkv"] }`
- **Réponse** : `{ "removed": 1, "total_validated": 4, "files": [...] }`

### 5.12 POST /api/ignore

Marque une vidéo comme n'ayant pas besoin de ST.

- **Body** : `{ "files": ["video.mkv"] }`
- **Action** : écrit dans `no-sub-needed.txt`
- **Réponse** : `{ "added": 1, "total_ignored": 3 }`

### 5.13 POST /api/unignore

- **Body** : `{ "files": ["video.mkv"] }`
- **Réponse** : `{ "removed": 1, "total_ignored": 2 }`

### 5.14 POST /api/play

Lance VLC sur une vidéo.

- **Body** : `{ "path": "/media/Series/Andor - S02E01.mkv" }`
- **Action** : `vlc --play-and-exit <path>` (processus détaché)
- **Réponse** : `{ "status": "launched", "file": "..." }`

### 5.15 POST /api/refresh

Invalide le cache et retourne l'arbre à jour.

- **Réponse** : `MediaTree` (identique à `/api/tree`)

### 5.16 GET /api/setup/check

Vérifie que tous les prérequis sont satisfaits. Appelé au chargement de la page d'accueil.

- **Réponse** :
```json
{
  "ready": false,
  "checks": {
    "alass":       {"ok": true,  "label": "alass (synchro audio)", "action": "terminal", "fix": "cd ... && ./install.sh"},
    "ffmpeg":      {"ok": true,  "label": "ffmpeg / ffprobe",      "action": "terminal", "fix": "sudo apt install ffmpeg"},
    "subliminal":  {"ok": true,  "label": "subliminal",             "action": "terminal", "fix": "pip install subliminal"},
    "config":      {"ok": false, "label": "Configuration",          "action": "page",     "fix": "config"},
    "films_path":  {"ok": false, "label": "Dossier Films",          "action": "page",     "fix": "config"},
    "series_path": {"ok": false, "label": "Dossier Séries",         "action": "page",     "fix": "config"}
  }
}
```
- `ready` : `true` si tous les checks sont OK
- Chaque check a un champ `action` :
  - `"terminal"` → commande affichée à copier-coller dans le terminal
  - `"page"` → bouton renvoyant vers la page Configuration

---

## 6 — Spécifications UI/UX

### 6.1 Layout général

```
┌──────────┬──────────────────────────────────────┐
│ Sidebar  │  Top bar (fil d'Ariane + actions)     │
│ 220px    │──────────────────────────────────────│
│          │                                      │
│ 🏠 Acc.  │  Zone de contenu                     │
│          │  (stats, tableau, console)            │
│ 🎥 Films │                                      │
│          │                                      │
│ 📺 Séries│                                      │
│  ▸ Andor │                                      │
│  ...     │                                      │
└──────────┴──────────────────────────────────────┘
│          Panneau d'aide (coulissant droite, 420px) │
│          Console (bas, redimensionnable)           │
```

### 6.2 Vues

| Vue | Contenu |
|-----|---------|
| **Accueil** | Stats Films/Séries, sous-titres manquants, fichiers à scanner, derniers avertissements |
| **Films** | Tableau filtrable avec sélection multiple |
| **Séries** | Liste des séries avec stats, navigation → Saisons → Épisodes |
| **Saison** | Tableau d'épisodes (même layout que Films) |
| **Whitelist** | Liste des sous-titres validés manuellement |
| **Warnings** | Liste des avertissements de synchronisation |
| **Configuration** | Dossiers médias + clé API OpenSubtitles |
| **Aide** | Panneau latéral coulissant (touche `?`) |

### 6.3 Actions

| Action | Scope |
|--------|-------|
| 🔍 Scanner | Vue courante (tout, une série, une saison, fichiers sélectionnés) |
| ⚡ Force | Vue courante |
| 👁️ Dry-Run | Vue courante |
| ✓ Valider | Fichiers sélectionnés |
| 🇫🇷 Ignorer | Fichiers sélectionnés |
| ▶️ Lire | Un fichier (VLC) |

### 6.4 Console

- SSE : logs en direct, couleurs ANSI → HTML
- Barre de progression
- Boutons : Stop, Copier, Clear, Toggle
- Persistante à travers les changements de vue

### 6.5 Panneau d'aide

- Coulissant depuis la droite (420px, animation 300ms)
- Ouverture : bouton top bar, lien sidebar, touche `?`
- Fermeture : ✕, Échap, clic sur l'overlay

### 6.6 Raccourcis clavier

| Touche | Action |
|--------|--------|
| `Échap` | Fermer l'aide / Désélectionner |
| `?` | Ouvrir l'aide |
| `Ctrl+Entrée` | Lancer le scan |

---

## 7 — Thème graphique

### Palette — Catppuccin Mocha (dark IDE)

| Token | Hex | Usage |
|-------|-----|-------|
| `--bg-base` | `#1e1e2e` | Fond principal |
| `--bg-mantle` | `#181825` | Sidebar, header |
| `--bg-crust` | `#11111b` | Console, cartes |
| `--bg-surface` | `#313244` | Surfaces (tableau, stats) |
| `--border` | `#45475a` | Bordures |
| `--text-primary` | `#cdd6f4` | Texte principal |
| `--text-secondary` | `#a6adc8` | Texte secondaire |
| `--text-muted` | `#6c7086` | Textes désactivés |
| `--accent` | `#89b4fa` | Bleu — liens, boutons |
| `--ok` | `#a6e3a1` | Vert — statut OK |
| `--warning` | `#f9e2af` | Jaune — Warning |
| `--error` | `#f38ba8` | Rouge — Erreur/Missing |
| `--validated` | `#cba6f7` | Mauve — Validé |
| `--running` | `#94e2d5` | Teal — En cours |

### Typographie

| Usage | Police | Taille |
|-------|--------|--------|
| Titres | system-ui, sans-serif | 1.25–1.5rem / 600 |
| Corps | system-ui, sans-serif | 0.875rem / 400 |
| Code/Console | JetBrains Mono, Fira Code, monospace | 0.8rem / 400 |
| Stats | system-ui, sans-serif | 1.5–2rem / 700 |

---

## 8 — Points techniques notables

### Gestion de `set -u`

Le script CLI utilise `set -uo pipefail`. Le `-u` rend les variables non définies comme des erreurs :
- Toujours utiliser `${var:-default}` pour les variables optionnelles
- Les boucles `for` sur des tableaux associatifs sont risquées → utiliser `while IFS= read -r`

### Chemins avec espaces

- `find ... -print0 | while IFS= read -r -d ''` pour le scan
- `printf '%s\n' "${!array[@]}"` plutôt que `echo` pour les clés de tableaux
- Toujours quoter les variables : `"$variable"`

### Code langue

- IETF : `fra` (subliminal)
- Court : `fr` (nom de fichier .fr.srt)
- ffmpeg : `fre` (metadata streams)
- Conversion automatique : `${LANG:0:2}` → `fr`

### alass

- Ratio FPS affiché : `25/24` = vidéo 25fps, sous-titre conçu pour 24fps
- Le grep capture `ratio is [0-9.]+` → extrait la première valeur numérique
- `--no-split` : transformation uniforme (vs découpage en blocs)
- Échec fréquent : SRT mal formé (lignes vides parasites)

### Portabilité

- `SUBSYNC_HOME` : dossier d'installation (défaut `~/.subsync-tool`)
- `SUBSYNC_MEDIA_ROOT` : racine des médias (défaut `~/media`)
- Le binaire `alass` est téléchargé par `install.sh`, pas commité

---

## 9 — Bugs résolus

### SRT corrompu → échec alass

**Cause** : ligne vide parasite entre timecode et texte dans le .srt
**Solution** : `repair_srt.py` normalise via pysubs2

### Double appel check_sync_quality → doublons

**Cause** : appelée dans `sync_with_alass()` ET `process_video()`
**Solution** : retiré de `sync_with_alass()`, conservé dans `process_video()`

### Boucle for sur tableau associatif → crash

**Cause** : `set -u` + clés avec espaces
**Solution** : `while IFS= read -r ... done < <(printf ...)`

### Fichier warnings dans le mauvais dossier

**Cause** : `dirname()` du .mkv donnait le dossier saison
**Solution** : remonter d'un niveau si le parent contient "saison"/"season"

### PAL vs NTSC insolubles

**Cause** : différences de montage entre versions 25fps et 23.976fps
**Solution** : système de validation manuelle (`--validate`)

### Job bloqué après exécution

**Cause** : `is_running` ne filtrait pas les jobs terminés
**Solution** : `is_running` et `get_active_job` ignorent les jobs avec `status='done'`

### Filtres par statut inopérants

**Cause** : `<input type="checkbox">` imbriqué dans `<label>` → double-toggle
**Solution** : chips `<span>` avec classe `active`, gérés en JS via `STATE.activeFilters`

---

## 10 — Limitations connues et pistes

### Limitations

1. **PAL vs NTSC** : insoluble automatiquement quand les montages diffèrent
2. **Séries sans dialogues** (ex: Primal) : alass échoue souvent
3. **Bonus/Featurettes** : aucun sous-titre disponible en ligne
4. **Seuil de 10s** : faux positifs sur les longs génériques → `SYNC_GAP_THRESHOLD` modifiable
5. **Pas de parallélisation** : traitement séquentiel, ~45 min pour 240 vidéos

### Pistes d'amélioration

- [x] ~~Interface web~~ → SubSync Web (2026-07-06)
- [x] ~~Support des films~~ → config web
- [x] ~~Validation manuelle~~ → UI web
- [x] ~~Rapport HTML~~ → dashboard web
- [x] ~~Marquage VF~~ → statut `ignored`
- [x] ~~Lecture VLC~~ → `POST /api/play`
- [x] ~~Panneau d'aide latéral~~ → touche `?`
- [ ] Parallélisation avec `xargs -P` ou GNU parallel
- [ ] Option `--threshold N` pour régler le seuil de détection
- [ ] Détection plus fine du dernier "vrai" dialogue
- [ ] Mode watch (inotify) pour traiter les nouveaux fichiers automatiquement
- [ ] Cache des résultats alass pour les fichiers non modifiés
- [ ] Intégration Bazarr comme alternative à subliminal

---

## 11 — Commandes utiles

```bash
# Vérifier la syntaxe
bash -n subsync.sh

# Debug d'une seule vidéo
bash -x subsync.sh --force "/path/video.mkv" 2>&1 | less

# Tester subliminal manuellement
subliminal --debug download -l fra "/path/video.mkv"

# Tester alass manuellement
alass video.mkv input.srt output.srt

# Compter les .fr.srt
find /media/Series -name "*.fr.srt" | wc -l

# Vérifier le FPS d'une vidéo
ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate \
  -of default=noprint_wrappers=1:nokey=1 video.mkv

# Voir la whitelist
cat validated-subs.txt

# Lancer le serveur web
cd web && python3 server.py --debug
```

---

## 12 — Suivi du projet

| Date | Étape | Statut |
|------|-------|--------|
| 2026-07-06 | Rédaction du cahier des charges | ✅ |
| 2026-07-06 | Structure et dépendances | ✅ |
| 2026-07-06 | Module scanner | ✅ |
| 2026-07-06 | API GET | ✅ |
| 2026-07-06 | API exécution + SSE | ✅ |
| 2026-07-06 | API whitelist | ✅ |
| 2026-07-06 | HTML + CSS | ✅ |
| 2026-07-06 | JavaScript | ✅ |
| 2026-07-06 | Intégration et polish | ✅ |
| 2026-07-06 | Cycle de vie des jobs (bugfix) | ✅ |
| 2026-07-06 | Filtres par statut (bugfix) | ✅ |
| 2026-07-06 | Page Configuration + Aide | ✅ |
| 2026-07-06 | Fonctionnalité « Pas besoin de ST » | ✅ |
| 2026-07-06 | Lecture VLC | ✅ |
| 2026-07-06 | Panneau d'aide latéral | ✅ |
| 2026-07-06 | Portabilité (env vars, chemins génériques) | ✅ |
| 2026-07-06 | Préparation dépôt GitHub | ✅ |
| 2026-07-06 | Consolidation documentation | ✅ |

> **Statut** : v1.0.0 — Prêt pour dépôt GitHub. Maintenance active.
