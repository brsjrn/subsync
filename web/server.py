#!/usr/bin/env python3
"""
SubSync Web — Serveur Flask

Interface web pour SubSync Tool.
Lancement : python3 server.py [--port 5001] [--root /chemin/medias]
"""

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid

from flask import (Flask, Response, jsonify, render_template, request,
                   stream_with_context)

# Ajouter le dossier courant au path pour importer scanner
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scanner

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config['ROOT_DIR'] = os.environ.get('SUBSYNC_MEDIA_ROOT', os.path.expanduser('~/media'))

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
SUBLIMINAL_CONFIG = os.path.expanduser('~/.config/subliminal/subliminal.toml')
SUBSYNC_HOME = os.environ.get('SUBSYNC_HOME', os.path.expanduser('~/.subsync-tool'))


def load_config():
    """Charge la configuration depuis config.json et subliminal.toml."""
    root = app.config['ROOT_DIR']
    defaults = {
        'films_path': os.path.join(root, 'Films'),
        'series_path': os.path.join(root, 'Séries'),
    }
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                defaults.update(data)
        except (json.JSONDecodeError, OSError):
            pass
    # Charger la clé API OpenSubtitles
    defaults['opensubtitles_apikey'] = _read_opensubtitles_apikey()
    return defaults


def save_config(data: dict):
    """Sauvegarde la configuration dans config.json et subliminal.toml."""
    # Séparer les champs : apikey → subliminal.toml, le reste → config.json
    apikey = data.pop('opensubtitles_apikey', None)
    if apikey is not None:
        _write_opensubtitles_apikey(apikey)

    current = load_config()
    current.pop('opensubtitles_apikey', None)  # ne pas sauvegarder dans config.json
    current.update(data)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as fh:
        json.dump(current, fh, indent=2, ensure_ascii=False)
    # Mettre à jour les chemins dans le scanner
    scanner.ROOT_DIR = os.path.dirname(current['series_path'])
    scanner.clear_cache()


def _read_opensubtitles_apikey() -> str:
    """Lit la clé API OpenSubtitles depuis subliminal.toml."""
    if not os.path.isfile(SUBLIMINAL_CONFIG):
        return ''
    try:
        with open(SUBLIMINAL_CONFIG, 'r', encoding='utf-8') as fh:
            content = fh.read()
        import re
        m = re.search(r'apikey\s*=\s*"([^"]*)"', content)
        return m.group(1) if m else ''
    except OSError:
        return ''


def _write_opensubtitles_apikey(apikey: str):
    """Écrit ou met à jour la clé API OpenSubtitles dans subliminal.toml."""
    import re
    os.makedirs(os.path.dirname(SUBLIMINAL_CONFIG), exist_ok=True)

    if not os.path.isfile(SUBLIMINAL_CONFIG):
        # Créer le fichier s'il n'existe pas
        content = (
            '[provider.opensubtitlescom]\n'
            f'apikey = "{apikey}"\n'
        )
    else:
        with open(SUBLIMINAL_CONFIG, 'r', encoding='utf-8') as fh:
            content = fh.read()
        if re.search(r'^\s*apikey\s*=', content, re.MULTILINE):
            content = re.sub(
                r'apikey\s*=\s*"[^"]*"',
                f'apikey = "{apikey}"',
                content,
            )
        elif '[provider.opensubtitlescom]' in content:
            # Section existe mais pas d'apikey → ajouter après la section
            content = re.sub(
                r'(\[provider\.opensubtitlescom\][^\[]*?)\n',
                f'\\1\napikey = "{apikey}"\n',
                content,
                flags=re.DOTALL,
            )
        else:
            # Section n'existe pas → ajouter à la fin
            content += f'\n[provider.opensubtitlescom]\napikey = "{apikey}"\n'

    with open(SUBLIMINAL_CONFIG, 'w', encoding='utf-8') as fh:
        fh.write(content)

# ---------------------------------------------------------------------------
# Gestionnaire de jobs
# ---------------------------------------------------------------------------

class JobManager:
    """Gère l'exécution des commandes subsync en subprocess."""

    def __init__(self):
        self._job = None          # Job actif ou None
        self._process = None      # subprocess.Popen
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._stopped = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            if self._job is None:
                return False
            # Considérer comme "plus en cours" si terminé depuis > 5 secondes
            if self._job.get('status') == 'done':
                return False
            return True

    def get_active_job(self) -> dict | None:
        with self._lock:
            if self._job is None:
                return None
            if self._job.get('status') == 'done':
                return None
            return dict(self._job)

    def start(self, path: str | list[str], mode: str, script: str = None) -> str:
        """
        Lance une commande.
        Accepte un chemin unique (str) ou une liste de chemins (list[str]).
        Par défaut, lance subsync.sh. Si 'script' est fourni, exécute ce script à la place.
        Retourne le job_id.
        Lève RuntimeError si un job est déjà en cours.
        """
        with self._lock:
            # Nettoyer un job terminé
            if self._job is not None and self._job.get('status') == 'done':
                self._job = None

            if self._job is not None:
                raise RuntimeError('Un job est déjà en cours')

            job_id = str(uuid.uuid4())[:8]

            # Déterminer le script à exécuter
            if script:
                cmd = [script]
                # Passer les chemins en arguments
                if isinstance(path, str):
                    cmd.append(path)
                else:
                    cmd.extend(path)
            else:
                script = os.path.join(SUBSYNC_HOME, 'subsync.sh')
                if isinstance(path, str):
                    paths = [path]
                else:
                    paths = list(path)
                cmd = [script]
                if mode == 'force':
                    cmd.append('--force')
                elif mode == 'dry-run':
                    cmd.append('--dry-run')
                cmd.extend(paths)

            self._job = {
                'job_id': job_id,
                'command': ' '.join(cmd),
                'path': path if isinstance(path, str) else f'{len(path)} fichiers',
                'mode': mode,
                'started_at': time.strftime('%H:%M:%S'),
                'status': 'running',
                'ok': 0,
                'fail': 0,
            }
            self._stopped = False
            self._queue = queue.Queue()

        # Lancer dans un thread séparé
        thread = threading.Thread(target=self._run, args=(cmd, job_id),
                                  daemon=True)
        thread.start()
        return job_id

    def _run(self, cmd: list[str], job_id: str):
        """Exécute la commande et alimente la queue de logs."""
        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, 'SUBSYNC_LANG': 'fra'},
            )

            for line in iter(self._process.stdout.readline, ''):
                if self._stopped:
                    self._process.terminate()
                    break
                line = line.rstrip()
                self._queue.put({'type': 'log', 'line': line, 'stream': 'stdout'})

                # Essayer de parser la progression
                if '▶' in line:
                    self._queue.put({'type': 'progress', 'file': line.strip()})

            self._process.wait()
            rc = self._process.returncode

            if self._stopped:
                self._queue.put({
                    'type': 'done',
                    'exit_code': -1,
                    'ok': 0, 'fail': 0,
                    'message': 'Job arrêté par l\'utilisateur',
                })
            else:
                self._queue.put({
                    'type': 'done',
                    'exit_code': rc,
                    'ok': 0, 'fail': 0,
                    'message': 'Terminé' if rc == 0 else f'Échec (code {rc})',
                })

        except Exception as e:
            self._queue.put({
                'type': 'error',
                'message': str(e),
            })
        finally:
            self._process = None
            with self._lock:
                if self._job and self._job['job_id'] == job_id:
                    self._job['status'] = 'done'

    def stop(self, job_id: str) -> bool:
        """Arrête le job en cours."""
        with self._lock:
            if self._job is None or self._job['job_id'] != job_id:
                return False
            self._stopped = True
            if self._process and self._process.poll() is None:
                self._process.terminate()
            return True

    def stream(self, job_id: str):
        """Générateur SSE pour les logs en direct."""
        with self._lock:
            if self._job is None or self._job['job_id'] != job_id:
                yield f"event: error\ndata: {{\"message\": \"Job introuvable\"}}\n\n"
                return

        # Envoyer l'event de démarrage
        yield f"event: start\ndata: {{\"job_id\": \"{job_id}\"}}\n\n"

        # Timeout : 45 minutes max
        deadline = time.time() + 2700
        last_heartbeat = time.time()

        while time.time() < deadline:
            try:
                event = self._queue.get(timeout=1.0)
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

                if event['type'] in ('done', 'error'):
                    break
            except queue.Empty:
                # Envoyer un heartbeat toutes les 15 secondes
                if time.time() - last_heartbeat > 15:
                    yield f": heartbeat\n\n"
                    last_heartbeat = time.time()

                # Vérifier si le job est toujours actif
                with self._lock:
                    if self._job is None:
                        break
                    if self._job['status'] == 'done':
                        yield f"event: done\ndata: {{\"message\": \"Job terminé\"}}\n\n"
                        break


# Instance globale
job_manager = JobManager()


# ---------------------------------------------------------------------------
# Routes — Pages
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    """Page principale de l'interface."""
    config = load_config()
    return render_template('index.html',
                           root_dir=app.config['ROOT_DIR'],
                           config=config)


# ---------------------------------------------------------------------------
# Routes — API GET
# ---------------------------------------------------------------------------

@app.route('/api/tree')
def api_tree():
    """Arborescence complète Films + Séries avec statuts."""
    config = load_config()
    films_path = request.args.get('films_path', config['films_path'])
    series_path = request.args.get('series_path', config['series_path'])
    with_duration = request.args.get('duration', '0') == '1'
    try:
        tree = scanner.scan_tree(films_path=films_path,
                                 series_path=series_path,
                                 with_duration=with_duration)
        return jsonify(tree)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    """Lecture ou mise à jour de la configuration."""
    if request.method == 'GET':
        return jsonify(load_config())
    elif request.method == 'POST':
        data = request.get_json(silent=True) or {}
        allowed = {'films_path', 'series_path', 'opensubtitles_apikey'}
        update = {k: v for k, v in data.items() if k in allowed}
        if not update:
            return jsonify({'error': 'Aucun champ valide'}), 400
        # Vérifier que les chemins (si fournis) existent
        for key in ('films_path', 'series_path'):
            if key in update and not os.path.isdir(update[key]):
                return jsonify({'error': f'Dossier introuvable : {update[key]}'}), 400
        save_config(update)
        scanner.clear_cache()
        return jsonify({'status': 'saved', 'config': load_config()})


@app.route('/api/status')
def api_status():
    """Statut d'un dossier spécifique."""
    path = request.args.get('path', app.config['ROOT_DIR'])
    with_duration = request.args.get('duration', '0') == '1'
    if not path or not os.path.isdir(path):
        return jsonify({'error': 'Chemin invalide'}), 400
    try:
        status = scanner.get_status(path, with_duration=with_duration)
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def api_stats():
    """Statistiques agrégées d'un dossier."""
    path = request.args.get('path', app.config['ROOT_DIR'])
    try:
        status = scanner.get_status(path, with_duration=False)
        return jsonify(status.get('stats', {}))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/validated')
def api_validated():
    """Liste des sous-titres validés."""
    try:
        validated_file = scanner.VALIDATED_FILE
        files = []
        if os.path.isfile(validated_file):
            with open(validated_file, 'r', encoding='utf-8') as fh:
                files = sorted(line.strip() for line in fh if line.strip())
        return jsonify({
            'files': files,
            'count': len(files),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/warnings')
def api_warnings():
    """Avertissements parsés depuis subsync-warnings.txt."""
    root = request.args.get('root', app.config['ROOT_DIR'])
    try:
        warnings = scanner.parse_warnings(root)
        warning_list = [
            {'file': k, 'gap': v.get('gap', ''), 'detail': v.get('detail', '')}
            for k, v in warnings.items()
        ]
        warning_list.sort(key=lambda w: w['file'])
        return jsonify({
            'warnings': warning_list,
            'count': len(warning_list),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Routes — API POST (actions)
# ---------------------------------------------------------------------------

@app.route('/api/run', methods=['POST'])
def api_run():
    """Lance une commande subsync."""
    data = request.get_json(silent=True) or {}
    path = data.get('path')
    paths = data.get('paths')  # liste de chemins (alternative à path)
    mode = data.get('mode', 'scan')

    if mode not in ('scan', 'force', 'dry-run'):
        return jsonify({'error': f'Mode invalide : {mode}'}), 400

    target = path or paths
    if not target:
        return jsonify({'error': 'Aucun chemin spécifié (path ou paths requis)'}), 400

    # Vérifier que les chemins existent
    if isinstance(target, str):
        if not os.path.exists(target):
            return jsonify({'error': f'Chemin introuvable : {target}'}), 400
    else:
        for p in target:
            if not os.path.exists(p):
                return jsonify({'error': f'Chemin introuvable : {p}'}), 400

    try:
        job_id = job_manager.start(target, mode)
        job = job_manager.get_active_job()
        scanner.clear_cache()
        return jsonify(job), 200
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stream/<job_id>')
def api_stream(job_id):
    """Flux SSE des logs d'un job."""
    def generate():
        yield from job_manager.stream(job_id)
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        }
    )


@app.route('/api/stop/<job_id>', methods=['POST'])
def api_stop(job_id):
    """Arrête le job en cours."""
    if job_manager.stop(job_id):
        return jsonify({'status': 'stopped'})
    return jsonify({'error': 'Job introuvable'}), 404


@app.route('/api/play', methods=['POST'])
def api_play():
    """Lance une vidéo avec VLC."""
    data = request.get_json(silent=True) or {}
    path = data.get('path', '')

    if not path or not os.path.isfile(path):
        return jsonify({'error': f'Fichier introuvable : {path}'}), 400

    try:
        subprocess.Popen(
            ['vlc', '--play-and-exit', path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # détacher du serveur
        )
        return jsonify({'status': 'launched', 'file': os.path.basename(path)})
    except FileNotFoundError:
        return jsonify({'error': 'VLC introuvable. Vérifie que vlc est dans le PATH.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/ignore', methods=['POST'])
def api_ignore():
    """Marque des vidéos comme n'ayant pas besoin de sous-titres."""
    data = request.get_json(silent=True) or {}
    files = data.get('files', [])

    if not files:
        return jsonify({'error': 'Aucun fichier spécifié'}), 400

    try:
        added = scanner.add_to_ignored(files)
        return jsonify({
            'added': added,
            'total_ignored': len(scanner.get_ignored_set()),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/unignore', methods=['POST'])
def api_unignore():
    """Retire le marquage « pas besoin de sous-titres »."""
    data = request.get_json(silent=True) or {}
    files = data.get('files', [])

    if not files:
        return jsonify({'error': 'Aucun fichier spécifié'}), 400

    try:
        removed = scanner.remove_from_ignored(files)
        return jsonify({
            'removed': removed,
            'total_ignored': len(scanner.get_ignored_set()),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/validate', methods=['POST'])
def api_validate():
    """Ajoute des fichiers à la whitelist."""
    data = request.get_json(silent=True) or {}
    files = data.get('files', [])

    if not files:
        return jsonify({'error': 'Aucun fichier spécifié'}), 400

    try:
        added = scanner.add_to_validated(files)
        validated = sorted(scanner.get_validated_set())
        return jsonify({
            'added': added,
            'total_validated': len(validated),
            'files': validated,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/unvalidate', methods=['POST'])
def api_unvalidate():
    """Retire des fichiers de la whitelist."""
    data = request.get_json(silent=True) or {}
    files = data.get('files', [])

    if not files:
        return jsonify({'error': 'Aucun fichier spécifié'}), 400

    try:
        removed = scanner.remove_from_validated(files)
        validated = sorted(scanner.get_validated_set())
        return jsonify({
            'removed': removed,
            'total_validated': len(validated),
            'files': validated,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    """Invalide le cache et retourne l'arbre à jour."""
    scanner.clear_cache()
    return api_tree()


# ---------------------------------------------------------------------------
# Routes — Setup / Installation
# ---------------------------------------------------------------------------

@app.route('/api/setup/check')
def api_setup_check():
    """Vérifie que tous les prérequis sont satisfaits."""
    config = load_config()
    checks = {}

    # --- alass ---
    alass_path = os.path.join(SUBSYNC_HOME, 'alass')
    checks['alass'] = {
        'ok': os.path.isfile(alass_path) and os.access(alass_path, os.X_OK),
        'label': 'alass (synchro audio)',
        'detail': '',
        'fix': f'Téléchargé automatiquement par l\'installation.'
    }
    if not checks['alass']['ok']:
        checks['alass']['detail'] = f'Binaire introuvable : {alass_path}'

    # --- ffmpeg ---
    try:
        result = subprocess.run(['ffprobe', '-version'], capture_output=True, timeout=5)
        checks['ffmpeg'] = {
            'ok': result.returncode == 0,
            'label': 'ffmpeg / ffprobe',
            'detail': '',
            'fix': 'sudo apt install ffmpeg'
        }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        checks['ffmpeg'] = {
            'ok': False,
            'label': 'ffmpeg / ffprobe',
            'detail': 'Commande introuvable.',
            'fix': 'sudo apt install ffmpeg'
        }

    # --- subliminal ---
    try:
        import subliminal
        checks['subliminal'] = {
            'ok': True,
            'label': 'subliminal (téléchargement)',
            'detail': '',
            'fix': 'pip install subliminal'
        }
    except ImportError:
        checks['subliminal'] = {
            'ok': False,
            'label': 'subliminal (téléchargement)',
            'detail': 'Module Python introuvable.',
            'fix': 'pip install subliminal'
        }

    # --- config ---
    films_path = config.get('films_path', '')
    series_path = config.get('series_path', '')
    placeholder = '/chemin/vers/vos/'
    config_ok = (
        bool(films_path) and bool(series_path) and
        placeholder not in films_path and placeholder not in series_path
    )
    checks['config'] = {
        'ok': config_ok,
        'label': 'Configuration des dossiers',
        'detail': '' if config_ok else 'Les chemins Films/Séries utilisent les valeurs par défaut.',
        'fix': 'Configurer dans la page ⚙️ Configuration'
    }

    # --- media folders ---
    for key, label in [('films', 'Dossier Films'), ('series', 'Dossier Séries')]:
        cfg_key = f'{key}_path'
        path = config.get(cfg_key, '')
        ok = os.path.isdir(path)
        checks[cfg_key] = {
            'ok': ok,
            'label': label,
            'detail': '' if ok else f'Dossier introuvable : {path}',
            'fix': f'Vérifier le chemin dans ⚙️ Configuration'
        }

    all_ok = all(c['ok'] for c in checks.values())

    return jsonify({
        'ready': all_ok,
        'checks': checks,
        'install_available': os.path.isfile(os.path.join(SUBSYNC_HOME, 'install.sh')),
    })


@app.route('/api/setup/install', methods=['POST'])
def api_setup_install():
    """Lance le script d'installation (via le système de jobs)."""
    install_script = os.path.join(SUBSYNC_HOME, 'install.sh')
    if not os.path.isfile(install_script):
        return jsonify({'error': 'Script install.sh introuvable'}), 400

    try:
        # Passer le script comme script personnalisé, et le HOME comme path
        job_id = job_manager.start(SUBSYNC_HOME, 'install', script=install_script)
        job = job_manager.get_active_job()
        scanner.clear_cache()
        return jsonify(job), 200
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='SubSync Web Server')
    parser.add_argument('--port', type=int, default=5001, help='Port (défaut: 5001)')
    parser.add_argument('--host', default='127.0.0.1', help='Host (défaut: 127.0.0.1)')
    parser.add_argument('--root', default=os.environ.get('SUBSYNC_MEDIA_ROOT', os.path.expanduser('~/media')),
                        help='Dossier racine des médias')
    parser.add_argument('--debug', action='store_true', help='Mode debug Flask')
    parser.add_argument('--stop', action='store_true',
                        help='Arrêter le serveur en cours d\'exécution')
    args = parser.parse_args()

    if args.stop:
        import signal
        try:
            result = subprocess.run(
                ['lsof', '-ti', f':{args.port}'],
                capture_output=True, text=True
            )
            pids = result.stdout.strip().split()
            if not pids or pids == ['']:
                print(f"Aucun serveur SubSync Web trouvé sur le port {args.port}.")
                return
            for pid in pids:
                os.kill(int(pid), signal.SIGTERM)
            print(f"Serveur SubSync Web arrêté (port {args.port}).")
        except ProcessLookupError:
            print(f"Aucun serveur trouvé sur le port {args.port}.")
        except Exception as e:
            print(f"Erreur lors de l'arrêt : {e}")
        return

    app.config['ROOT_DIR'] = args.root
    scanner.ROOT_DIR = args.root

    print(f"\n{'='*50}")
    print(f"  🎬  SubSync Web")
    print(f"  →  http://{args.host}:{args.port}")
    print(f"  📂  {args.root}")
    print(f"{'='*50}\n")

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == '__main__':
    main()
