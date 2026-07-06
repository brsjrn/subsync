#!/usr/bin/env python3
"""
Module de scan du filesystem multimédia.

Parse l'arborescence multimédia pour extraire :
- Les films (dans le dossier Films/)
- Les séries → saisons → épisodes (dans le dossier Séries/)

Pour chaque vidéo, détermine le statut du sous-titre :
  ok, warning, missing, validated, ignored
"""

import os
import re
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm'}
SUBTITLE_SUFFIXES = ['.fr.srt', '.fra.srt', '.srt']

SUBSYNC_HOME = os.environ.get('SUBSYNC_HOME', os.path.expanduser('~/.subsync-tool'))
ROOT_DIR = os.environ.get('SUBSYNC_MEDIA_ROOT', os.path.expanduser('~/media'))
VALIDATED_FILE = os.path.join(SUBSYNC_HOME, 'validated-subs.txt')

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict = {}
_cache_time: float = 0.0
CACHE_TTL: float = 30.0  # secondes


def _cache_get(key: str):
    """Retourne la valeur cachée si le TTL n'est pas expiré."""
    if time.time() - _cache_time < CACHE_TTL:
        return _cache.get(key)
    _cache.clear()
    return None


def _cache_set(key: str, value):
    """Stocke une valeur dans le cache."""
    _cache[key] = value
    global _cache_time
    _cache_time = time.time()


def clear_cache():
    """Vide le cache manuellement."""
    _cache.clear()
    global _cache_time
    _cache_time = 0.0


# ---------------------------------------------------------------------------
# Détection des fichiers
# ---------------------------------------------------------------------------

def is_video(filepath: str) -> bool:
    """Vérifie si un fichier est une vidéo (basé sur l'extension)."""
    return os.path.splitext(filepath)[1].lower() in VIDEO_EXTENSIONS


def is_season_dir(dirname: str) -> bool:
    """Vérifie si un dossier est une saison."""
    return bool(re.search(r'saison|season', dirname, re.IGNORECASE))


def find_videos(path: str) -> list[str]:
    """
    Liste tous les fichiers vidéo récursivement dans un dossier.
    Retourne une liste de chemins absolus.
    """
    videos = []
    try:
        for root, dirs, files in os.walk(path):
            # Ignorer les dossiers cachés
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if not f.startswith('.') and is_video(f):
                    videos.append(os.path.join(root, f))
    except (PermissionError, OSError):
        pass
    return sorted(videos)


def find_srt(video_path: str) -> Optional[str]:
    """
    Cherche un fichier .srt associé à une vidéo.
    
    Cherche dans le même dossier :
    1. <stem>.fr.srt
    2. <stem>.fra.srt
    3. <stem>.srt
    4. N'importe quel .srt avec le même préfixe (30 premiers caractères)
    """
    dirname = os.path.dirname(video_path)
    stem = os.path.splitext(os.path.basename(video_path))[0]

    patterns = [
        os.path.join(dirname, f"{stem}.fr.srt"),
        os.path.join(dirname, f"{stem}.fra.srt"),
        os.path.join(dirname, f"{stem}.srt"),
    ]

    for p in patterns:
        if os.path.isfile(p):
            return p

    # Cherche avec préfixe commun (30 premiers car.)
    prefix = stem[:30]
    try:
        for f in os.listdir(dirname):
            if f.startswith(prefix) and f.endswith('.srt'):
                return os.path.join(dirname, f)
    except OSError:
        pass

    return None


# ---------------------------------------------------------------------------
# Whitelist (sous-titres validés manuellement)
# ---------------------------------------------------------------------------

def get_validated_set() -> set[str]:
    """
    Charge la whitelist depuis validated-subs.txt.
    Retourne un set de noms de fichiers (avec et sans extension).
    """
    validated = set()
    if not os.path.isfile(VALIDATED_FILE):
        return validated

    try:
        with open(VALIDATED_FILE, 'r', encoding='utf-8') as fh:
            for line in fh:
                name = line.strip()
                if name:
                    validated.add(name)
                    # Ajouter aussi sans extension pour matching flexible
                    stem = os.path.splitext(name)[0]
                    if stem != name:
                        validated.add(stem)
    except OSError:
        pass

    return validated


def add_to_validated(names: list[str]) -> int:
    """Ajoute des noms à la whitelist. Retourne le nombre ajouté."""
    current = set()
    if os.path.isfile(VALIDATED_FILE):
        try:
            with open(VALIDATED_FILE, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        current.add(line)
        except OSError:
            pass

    added = 0
    for name in names:
        name = name.strip()
        if name and name not in current:
            current.add(name)
            added += 1

    if added > 0:
        os.makedirs(os.path.dirname(VALIDATED_FILE), exist_ok=True)
        with open(VALIDATED_FILE, 'w', encoding='utf-8') as fh:
            for name in sorted(current):
                fh.write(name + '\n')
        clear_cache()

    return added


def remove_from_validated(names: list[str]) -> int:
    """Retire des noms de la whitelist. Retourne le nombre retiré."""
    if not os.path.isfile(VALIDATED_FILE):
        return 0

    current = set()
    try:
        with open(VALIDATED_FILE, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    current.add(line)
    except OSError:
        return 0

    removed = 0
    for name in names:
        name = name.strip()
        if name in current:
            current.discard(name)
            removed += 1
        # Essayer aussi sans extension
        stem = os.path.splitext(name)[0]
        if stem in current:
            current.discard(stem)
            removed += 1

    if removed > 0:
        with open(VALIDATED_FILE, 'w', encoding='utf-8') as fh:
            for name in sorted(current):
                fh.write(name + '\n')
        clear_cache()

    return removed


# ---------------------------------------------------------------------------
# Ignored (vidéos sans besoin de sous-titres)
# ---------------------------------------------------------------------------

IGNORED_FILE = os.path.join(SUBSYNC_HOME, 'no-sub-needed.txt')


def get_ignored_set() -> set[str]:
    """
    Charge la liste des vidéos n'ayant pas besoin de sous-titres.
    Retourne un set de noms de fichiers (avec et sans extension).
    """
    ignored = set()
    if not os.path.isfile(IGNORED_FILE):
        return ignored

    try:
        with open(IGNORED_FILE, 'r', encoding='utf-8') as fh:
            for line in fh:
                name = line.strip()
                if name:
                    ignored.add(name)
                    stem = os.path.splitext(name)[0]
                    if stem != name:
                        ignored.add(stem)
    except OSError:
        pass

    return ignored


def add_to_ignored(names: list[str]) -> int:
    """Ajoute des noms à la liste des vidéos sans besoin de sous-titres."""
    current = set()
    if os.path.isfile(IGNORED_FILE):
        try:
            with open(IGNORED_FILE, 'r', encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        current.add(line)
        except OSError:
            pass

    added = 0
    for name in names:
        name = name.strip()
        if name and name not in current:
            current.add(name)
            added += 1

    if added > 0:
        os.makedirs(os.path.dirname(IGNORED_FILE), exist_ok=True)
        with open(IGNORED_FILE, 'w', encoding='utf-8') as fh:
            for name in sorted(current):
                fh.write(name + '\n')
        clear_cache()

    return added


def remove_from_ignored(names: list[str]) -> int:
    """Retire des noms de la liste des vidéos sans besoin de sous-titres."""
    if not os.path.isfile(IGNORED_FILE):
        return 0

    current = set()
    try:
        with open(IGNORED_FILE, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line:
                    current.add(line)
    except OSError:
        return 0

    removed = 0
    for name in names:
        name = name.strip()
        if name in current:
            current.discard(name)
            removed += 1
        stem = os.path.splitext(name)[0]
        if stem in current:
            current.discard(stem)
            removed += 1

    if removed > 0:
        with open(IGNORED_FILE, 'w', encoding='utf-8') as fh:
            for name in sorted(current):
                fh.write(name + '\n')
        clear_cache()

    return removed


# ---------------------------------------------------------------------------
# Warnings (subsync-warnings.txt)
# ---------------------------------------------------------------------------

def _find_all_warning_files(root: str) -> list[str]:
    """Trouve TOUS les fichiers subsync-warnings.txt sous la racine."""
    found = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # Éviter de descendre trop profond (niveau saison)
            depth = dirpath[len(root):].count(os.sep)
            if depth > 3:
                dirnames.clear()
                continue
            # Ignorer les dossiers cachés
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]
            if 'subsync-warnings.txt' in filenames:
                found.append(os.path.join(dirpath, 'subsync-warnings.txt'))
    except (PermissionError, OSError):
        pass
    return found


def _parse_one_warning_file(path: str) -> dict[str, dict]:
    """Parse un fichier subsync-warnings.txt et retourne les warnings."""
    warnings = {}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            current_name = None
            for line in fh:
                line = line.rstrip()
                if line.startswith('▸ '):
                    current_name = line[2:].strip()
                    warnings[current_name] = {'gap': '', 'detail': ''}
                elif line.strip().startswith('écart:') and current_name:
                    warnings[current_name]['gap'] = line.strip().replace('écart: ', '')
                elif line.strip().startswith('dernier') and current_name:
                    warnings[current_name]['detail'] = line.strip()
    except OSError:
        pass
    return warnings


def parse_warnings(root: str = None) -> dict[str, dict]:
    """
    Parse tous les fichiers subsync-warnings.txt sous la racine.
    Agrège les warnings de tous les fichiers trouvés (global + par série).

    Retourne un dict:
      { "NomFichier.mkv": {"gap": "+0m34s", "detail": "dernier sous-titre ..."} }
    """
    if root is None:
        root = ROOT_DIR

    cache_key = f'warnings_{root}'
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    all_warnings = {}
    warning_files = _find_all_warning_files(root)

    for wf in warning_files:
        parsed = _parse_one_warning_file(wf)
        # Merge : les fichiers plus spécifiques (ex: par série) écrasent
        # le global (au cas où il y aurait des doublons)
        all_warnings.update(parsed)

    _cache_set(cache_key, all_warnings)
    return all_warnings


# ---------------------------------------------------------------------------
# Infos vidéo
# ---------------------------------------------------------------------------

def _format_duration(seconds: float) -> str:
    """Convertit des secondes en HH:MM:SS ou MM:SS."""
    if seconds <= 0:
        return '?'
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m:02d}:{s:02d}'


def _get_duration(video_path: str) -> tuple[str, int]:
    """Retourne (durée formatée, durée secondes) via ffprobe."""
    import subprocess
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=5
        )
        secs = float(result.stdout.strip() or 0)
        return _format_duration(secs), int(secs)
    except (subprocess.TimeoutExpired, ValueError, OSError, FileNotFoundError):
        return '?', 0


def get_video_info(video_path: str,
                   validated_set: set[str] = None,
                   warnings_map: dict = None,
                   ignored_set: set[str] = None) -> dict:
    """
    Retourne un dictionnaire VideoFile complet pour une vidéo.
    """
    if validated_set is None:
        validated_set = get_validated_set()
    if warnings_map is None:
        warnings_map = parse_warnings()
    if ignored_set is None:
        ignored_set = get_ignored_set()

    name = os.path.basename(video_path)
    stem = os.path.splitext(name)[0]
    srt_path = find_srt(video_path)
    has_srt = srt_path is not None

    # Déterminer le statut
    is_val = name in validated_set or stem in validated_set
    is_ign = name in ignored_set or stem in ignored_set

    warning_info = warnings_map.get(name, warnings_map.get(stem, None))
    has_warning = warning_info is not None and bool(warning_info.get('gap', ''))

    if is_val:
        status = 'validated'
        status_label = '✓ Validé'
        warning_gap = ''
        warning_detail = ''
    elif is_ign and not has_srt:
        status = 'ignored'
        status_label = '🇫🇷 VF'
        warning_gap = ''
        warning_detail = ''
    elif has_srt and has_warning:
        status = 'warning'
        warning_gap = warning_info.get('gap', '') if warning_info else ''
        warning_detail = warning_info.get('detail', '') if warning_info else ''
        status_label = f'⚠️ {warning_gap}' if warning_gap else '⚠️ Warning'
    elif has_srt:
        status = 'ok'
        status_label = '✅ OK'
        warning_gap = ''
        warning_detail = ''
    else:
        status = 'missing'
        status_label = '❌ Manquant'
        warning_gap = ''
        warning_detail = ''

    return {
        'name': name,
        'stem': stem,
        'path': video_path,
        'type': 'unknown',  # sera surchargé par l'appelant
        'series': '',
        'season': '',
        'has_srt': has_srt,
        'srt_path': srt_path or '',
        'status': status,
        'status_label': status_label,
        'warning_gap': warning_gap,
        'warning_detail': warning_detail,
        'is_validated': is_val,
        'is_ignored': is_ign,
        'duration': '?',     # rempli à la demande
        'duration_sec': 0,
    }


# ---------------------------------------------------------------------------
# Scan des Films
# ---------------------------------------------------------------------------

def scan_films(films_path: str, with_duration: bool = False,
               validated_set: set[str] = None,
               warnings_map: dict = None,
               ignored_set: set[str] = None) -> dict:
    """
    Scan le dossier Films.
    Retourne {"videos": [...], "stats": {...}}
    """
    if validated_set is None:
        validated_set = get_validated_set()
    if warnings_map is None:
        warnings_map = parse_warnings()
    if ignored_set is None:
        ignored_set = get_ignored_set()

    videos = []
    stats = {'total': 0, 'ok': 0, 'warning': 0, 'missing': 0, 'validated': 0, 'ignored': 0}

    for vpath in find_videos(films_path):
        info = get_video_info(vpath, validated_set, warnings_map, ignored_set)
        info['type'] = 'film'
        if with_duration:
            info['duration'], info['duration_sec'] = _get_duration(vpath)
        videos.append(info)
        stats[info['status']] += 1
        stats['total'] += 1

    return {'videos': videos, 'stats': stats}


# ---------------------------------------------------------------------------
# Scan des Séries
# ---------------------------------------------------------------------------

def _group_by_series(series_path: str, with_duration: bool = False,
                     validated_set: set[str] = None,
                     warnings_map: dict = None,
                     ignored_set: set[str] = None) -> dict:
    """
    Parcourt l'arborescence Séries/ et groupe les vidéos par série/saison.

    Retourne:
      {
        "series": {
          "Andor": {
            "path": "...",
            "seasons": {
              "Saison 1": [VideoFile, ...],
              "Saison 2": [VideoFile, ...],
              "Sans saison": [VideoFile, ...]
            },
            "stats": {...}
          },
          ...
        },
        "global_stats": {...}
      }
    """
    if validated_set is None:
        validated_set = get_validated_set()
    if warnings_map is None:
        warnings_map = parse_warnings()
    if ignored_set is None:
        ignored_set = get_ignored_set()

    all_videos = find_videos(series_path)

    # Structure: series_name -> season_name -> [videos]
    series_map: dict[str, dict] = {}

    for vpath in all_videos:
        rel = os.path.relpath(vpath, series_path)
        parts = rel.split(os.sep)

        if len(parts) < 2:
            # Fichier à la racine de Séries/ → on ignore ou on met dans "Divers"
            series_name = '(Racine Séries)'
            season_name = 'Sans saison'
        else:
            series_name = parts[0]
            rest = parts[1:-1]  # parties intermédiaires

            # Déterminer la saison
            season_name = 'Sans saison'
            for i, part in enumerate(rest):
                if is_season_dir(part):
                    season_name = part
                    break
            # Si pas de saison explicite, regarder si le nom du fichier
            # est dans un sous-dossier de la série
            if season_name == 'Sans saison' and len(rest) > 0:
                # Vérifier si un des rest contient une saison
                pass

        if series_name not in series_map:
            series_map[series_name] = {
                'path': os.path.join(series_path, series_name)
                if series_name != '(Racine Séries)' else series_path,
                'seasons': {}
            }

        if season_name not in series_map[series_name]['seasons']:
            series_map[series_name]['seasons'][season_name] = []

        info = get_video_info(vpath, validated_set, warnings_map, ignored_set)
        info['type'] = 'episode'
        info['series'] = series_name
        info['season'] = season_name
        if with_duration:
            info['duration'], info['duration_sec'] = _get_duration(vpath)
        series_map[series_name]['seasons'][season_name].append(info)

    # Calculer les stats par série et globales
    global_stats = {'total': 0, 'ok': 0, 'warning': 0,
                    'missing': 0, 'validated': 0, 'ignored': 0}
    series_list = []

    for sname in sorted(series_map.keys()):
        sdata = series_map[sname]
        sstats = {'total': 0, 'ok': 0, 'warning': 0,
                  'missing': 0, 'validated': 0, 'ignored': 0}

        # Trier les saisons
        sorted_seasons = {}
        for season_name in sorted(sdata['seasons'].keys()):
            episodes = sdata['seasons'][season_name]
            # Trier les épisodes par nom
            episodes.sort(key=lambda e: e['name'])
            sorted_seasons[season_name] = episodes
            for ep in episodes:
                sstats[ep['status']] += 1
                sstats['total'] += 1

        sdata['seasons'] = sorted_seasons

        series_list.append({
            'name': sname,
            'path': sdata['path'],
            'type': 'series',
            'seasons': sorted_seasons,
            'season_names': list(sorted_seasons.keys()),
            'stats': sstats,
            'episode_count': sstats['total'],
        })

        for k in global_stats:
            global_stats[k] += sstats[k]

    return {
        'series_list': series_list,
        'stats': global_stats,
    }


def scan_series(series_path: str, with_duration: bool = False,
                validated_set: set[str] = None,
                warnings_map: dict = None,
                ignored_set: set[str] = None) -> dict:
    """Scan le dossier Séries. Retourne la structure complète."""
    return _group_by_series(series_path, with_duration,
                            validated_set, warnings_map, ignored_set)


# ---------------------------------------------------------------------------
# Scan complet
# ---------------------------------------------------------------------------

def scan_tree(films_path: str = None, series_path: str = None,
               with_duration: bool = False) -> dict:
    """
    Scan complet des dossiers Films et Séries.

    Retourne le MediaTree complet:
      {
        "films": { "videos": [...], "stats": {...} },
        "series": { "series_list": [...], "stats": {...} },
        "films_path": "/mnt/.../Films",
        "series_path": "/mnt/.../Séries",
        "scanned_at": "2026-07-06T21:00:00"
      }
    """
    if films_path is None:
        films_path = os.path.join(ROOT_DIR, 'Films')
    if series_path is None:
        series_path = os.path.join(ROOT_DIR, 'Séries')

    root_for_warnings = os.path.dirname(series_path)

    cache_key = f'tree_{films_path}_{series_path}_{with_duration}'
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    validated_set = get_validated_set()
    warnings_map = parse_warnings(root_for_warnings)
    ignored_set = get_ignored_set()

    films_data = {'videos': [], 'stats': {'total': 0, 'ok': 0, 'warning': 0,
                                          'missing': 0, 'validated': 0, 'ignored': 0}}
    if os.path.isdir(films_path):
        films_data = scan_films(films_path, with_duration,
                                validated_set, warnings_map, ignored_set)

    series_data = {'series_list': [], 'stats': {'total': 0, 'ok': 0,
                                                 'warning': 0, 'missing': 0,
                                                 'validated': 0, 'ignored': 0}}
    if os.path.isdir(series_path):
        series_data = scan_series(series_path, with_duration,
                                  validated_set, warnings_map, ignored_set)

    result = {
        'films': films_data,
        'series': series_data,
        'films_path': films_path,
        'series_path': series_path,
        'scanned_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }

    _cache_set(cache_key, result)
    return result


def get_status(path: str, with_duration: bool = False) -> dict:
    """
    Statut détaillé d'un dossier spécifique.
    Détecte automatiquement si c'est un dossier Films, Séries, Série ou Saison.
    """
    validated_set = get_validated_set()
    warnings_map = parse_warnings()
    ignored_set = get_ignored_set()

    videos = []
    stats = {'total': 0, 'ok': 0, 'warning': 0, 'missing': 0, 'validated': 0, 'ignored': 0}

    if not os.path.isdir(path):
        return {'path': path, 'videos': [], 'stats': stats, 'error': 'Dossier introuvable'}

    for vpath in find_videos(path):
        info = get_video_info(vpath, validated_set, warnings_map, ignored_set)
        # Déterminer le type et la série/saison
        rel_to_root = os.path.relpath(vpath, ROOT_DIR)
        parts = rel_to_root.split(os.sep)
        if len(parts) > 0 and parts[0] == 'Films':
            info['type'] = 'film'
        else:
            info['type'] = 'episode'
            if len(parts) > 1:
                info['series'] = parts[1] if parts[0] == 'Séries' else parts[0]
            # Chercher la saison dans le chemin
            for part in parts:
                if is_season_dir(part):
                    info['season'] = part
                    break

        if with_duration:
            info['duration'], info['duration_sec'] = _get_duration(vpath)
        videos.append(info)
        stats[info['status']] += 1
        stats['total'] += 1

    return {'path': path, 'videos': videos, 'stats': stats}


# ---------------------------------------------------------------------------
# Test rapide
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import json
    import sys

    root = sys.argv[1] if len(sys.argv) > 1 else ROOT_DIR
    print(f"Scan de {root}...")
    tree = scan_tree(root, with_duration=False)
    print(f"Films : {tree['films']['stats']}")
    print(f"Séries : {tree['series']['stats']}")
    print(f"Séries trouvées : {len(tree['series']['series_list'])}")
    for s in tree['series']['series_list']:
        print(f"  {s['name']}: {s['stats']} ({len(s['season_names'])} saisons)")
