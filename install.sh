#!/usr/bin/env bash
#=============================================================================
# SubSync Tool — Script d'installation
#
# Usage :
#   ./install.sh                           # Installation standard (~/.subsync-tool)
#   SUBSYNC_HOME=/opt/subsync ./install.sh # Dossier personnalisé
#   ./install.sh --no-alias                # Sans ajouter les alias shell
#=============================================================================

set -euo pipefail

SUBSYNC_HOME="${SUBSYNC_HOME:-$HOME/.subsync-tool}"
ALASS_VERSION="2.0.2"
ALASS_URL="https://github.com/kaegi/alass/releases/download/v${ALASS_VERSION}/alass-linux64"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
step()  { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }
ok()    { echo -e "  ${GREEN}✓${NC} $*"; }
err()   { echo -e "  ${RED}✗${NC} $*"; }

NO_ALIAS=false
[[ "${1:-}" == "--no-alias" ]] && NO_ALIAS=true

step "Vérification des prérequis"
command -v python3 >/dev/null 2>&1 && ok "python3" || { err "python3 requis"; exit 1; }
python3 -m pip --version >/dev/null 2>&1 && ok "pip" || { err "pip requis"; exit 1; }
command -v ffprobe >/dev/null 2>&1 && ok "ffprobe (ffmpeg)" || { err "ffmpeg requis"; exit 1; }

step "Création des dossiers"
mkdir -p "$SUBSYNC_HOME/web/static" "$SUBSYNC_HOME/web/templates"
ok "Dossier : $SUBSYNC_HOME"

step "Installation des dépendances Python"
python3 -m pip install --break-system-packages -q flask subliminal pysubs2
ok "flask, subliminal, pysubs2"

step "Téléchargement d'alass v${ALASS_VERSION}"
ALASS_PATH="$SUBSYNC_HOME/alass"
curl -sSL "$ALASS_URL" -o "$ALASS_PATH" 2>/dev/null || wget -q "$ALASS_URL" -O "$ALASS_PATH"
chmod +x "$ALASS_PATH"
ok "alass → $ALASS_PATH ($(du -h "$ALASS_PATH" | cut -f1))"

step "Configuration"
CONFIG_FILE="$SUBSYNC_HOME/web/config.json"
if [[ ! -f "$CONFIG_FILE" ]]; then
    cat > "$CONFIG_FILE" << 'CONFJSON'
{
  "films_path": "/chemin/vers/vos/Films",
  "series_path": "/chemin/vers/vos/Series"
}
CONFJSON
    ok "Fichier de config créé : $CONFIG_FILE"
    echo "     Edite-le pour y mettre les chemins de tes médias"
else
    ok "Fichier de config existant conservé"
fi

if [[ "$NO_ALIAS" == false ]]; then
    step "Ajout des alias shell"
    declare -A ALIASES=(
        ["subsync"]="$SUBSYNC_HOME/subsync.sh"
        ["subsync-web"]="cd $SUBSYNC_HOME/web && python3 server.py"
    )
    for rcfile in "$HOME/.bashrc" "$HOME/.zshrc"; do
        if [[ -f "$rcfile" ]]; then
            added=0
            for name in "${!ALIASES[@]}"; do
                if ! grep -q "alias $name=" "$rcfile" 2>/dev/null; then
                    echo "alias $name='${ALIASES[$name]}'" >> "$rcfile"
                    added=$((added + 1))
                fi
            done
            [[ $added -gt 0 ]] && ok "$added alias ajouté(s) dans $(basename "$rcfile")"
        fi
    done
fi

touch "$SUBSYNC_HOME/validated-subs.txt" "$SUBSYNC_HOME/no-sub-needed.txt"
ok "Fichiers de données initialisés"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     🎬  SubSync Tool — Installation OK    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  CLI : subsync --help"
echo "  Web : subsync-web"
echo "  Config : $CONFIG_FILE"
echo ""
echo "  Recharge ton shell : source ~/.zshrc   (ou ~/.bashrc)"
