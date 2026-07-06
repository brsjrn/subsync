#!/usr/bin/env bash
#=============================================================================
# subsync.sh — Télécharge et synchronise automatiquement les sous-titres
#
# Usage :
#   subsync.sh [--force] [--lang fra] /chemin/vers/medias...
#
# Dépendances : subliminal, alass, ffprobe
#
# Processus pour chaque vidéo :
#   1. Si déjà un .srt → le synchroniser avec alass (sauf si --no-sync)
#   2. Si pas de .srt → télécharger avec subliminal PUIS synchroniser
#   3. Renommer en <vidéo>.<lang>.srt pour lecture automatique
#=============================================================================

set -uo pipefail

# === Configuration ==========================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUBSYNC_HOME="${SUBSYNC_HOME:-$SCRIPT_DIR}"
ALASS="$SUBSYNC_HOME/alass"
LANG="${SUBSYNC_LANG:-fra}"
FORCE=false
NO_SYNC=false
DRY_RUN=false
TARGET_LANG_SHORT="fr"
VIDEO_EXTENSIONS="mp4|mkv|avi|mov|webm"

# === Couleurs ===============================================================
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_err()   { echo -e "${RED}[ERROR]${NC} $*"; }
log_sync()  { echo -e "${MAGENTA}[SYNC]${NC} $*"; }
log_step()  { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

# === Variables globales pour le rapport =====================================
declare -a WARNINGS=()
declare -A SERIES_WARNINGS=()  # dossier_série → liste d'avertissements
SYNC_GAP_THRESHOLD=10  # écart en secondes au-delà duquel on avertit
WARNING_FILE="subsync-warnings.txt"     # nom du fichier à la racine du dossier scanné
VALIDATED_FILE="$SUBSYNC_HOME/validated-subs.txt"  # whitelist des sous-titres validés manuellement

# === Whitelist : sous-titres validés manuellement ============================

is_validated() {
    local video_name="$1"
    [[ -f "$VALIDATED_FILE" ]] || return 1
    # Comparer avec et sans extension vidéo
    local name_noext="${video_name%.*}"
    grep -qFx "$video_name" "$VALIDATED_FILE" 2>/dev/null || \
    grep -qFx "$name_noext" "$VALIDATED_FILE" 2>/dev/null
}

validate_sub() {
    local video_name="$1"
    mkdir -p "$(dirname "$VALIDATED_FILE")"
    echo "$video_name" >> "$VALIDATED_FILE"
    sort -u "$VALIDATED_FILE" -o "$VALIDATED_FILE"
    log_ok "Sous-titre validé : $video_name (ne sera plus signalé)"
}

unvalidate_sub() {
    local video_name="$1"
    [[ -f "$VALIDATED_FILE" ]] || return 1
    grep -vFx "$video_name" "$VALIDATED_FILE" > "${VALIDATED_FILE}.tmp" 2>/dev/null
    mv "${VALIDATED_FILE}.tmp" "$VALIDATED_FILE"
    log_info "Validation retirée : $video_name"
}

usage() {
    cat <<EOF
Usage: subsync.sh [OPTIONS] PATH...

Options:
  --force              Force le retéléchargement même si un .srt existe
  --no-sync            Désactive la synchronisation avec alass
  --lang CODE          Code langue IETF (défaut: fra = français)
  --dry-run            Affiche ce qui serait fait sans rien modifier
  --validate "NOM"     Marque un sous-titre comme vérifié et correct
  --unvalidate "NOM"   Retire la validation manuelle
  --list-validated     Liste les sous-titres validés manuellement
  --help               Affiche cette aide

Exemples:
  subsync.sh ~/Séries/
  subsync.sh --force "/mnt/media/The Expanse - Saison 2/"
  subsync.sh --lang eng ~/Films/monfilm.mp4
  subsync.sh --validate "Normal.People.S01E01.720p.STAN.WEBRip.x264-GalaxyTV"
  subsync.sh --list-validated
EOF
    exit 0
}

# === Analyse des arguments ==================================================
PATHS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)       FORCE=true; shift ;;
        --no-sync)     NO_SYNC=true; shift ;;
        --lang)        LANG="$2"; TARGET_LANG_SHORT="${2:0:2}"; shift 2 ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --validate)    do_validate=true; VALIDATE_NAME="$2"; shift 2 ;;
        --unvalidate)  do_unvalidate=true; UNVALIDATE_NAME="$2"; shift 2 ;;
        --list-validated) do_list_validated=true; shift ;;
        --help)        usage ;;
        -*)            echo "Option inconnue: $1"; usage ;;
        *)             PATHS+=("$1"); shift ;;
    esac
done

# === Actions spéciales (pas besoin de PATH) ===
if [[ "${do_list_validated:-false}" == true ]]; then
    if [[ -f "$VALIDATED_FILE" ]] && [[ -s "$VALIDATED_FILE" ]]; then
        echo "Sous-titres validés manuellement :"
        cat "$VALIDATED_FILE"
    else
        echo "Aucun sous-titre validé manuellement."
    fi
    exit 0
fi

if [[ "${do_validate:-false}" == true ]]; then
    validate_sub "$VALIDATE_NAME"
    exit 0
fi

if [[ "${do_unvalidate:-false}" == true ]]; then
    unvalidate_sub "$UNVALIDATE_NAME"
    exit 0
fi

# === Vérification des PATH ==================================================
if [[ ${#PATHS[@]} -eq 0 ]]; then
    echo "Erreur: aucun chemin spécifié." >&2
    usage
fi

# === Vérification des dépendances ===========================================
check_deps() {
    local missing=()
    command -v subliminal >/dev/null 2>&1 || missing+=("subliminal (pip install --break-system-packages subliminal)")
    command -v ffprobe >/dev/null 2>&1    || missing+=("ffprobe (apt install ffmpeg)")
    [[ -x "$ALASS" ]]                      || missing+=("alass ($SUBSYNC_HOME/alass)")

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_err "Dépendances manquantes :"
        for m in "${missing[@]}"; do
            echo "       - $m"
        done
        exit 1
    fi
}

# === Fonctions ==============================================================

# Trouve le fichier .srt associé à une vidéo
find_existing_srt() {
    local video="$1"
    local dir; dir=$(dirname "$video")
    local stem; stem=$(basename "$video" | sed 's/\.[^.]*$//')

    local patterns=(
        "${dir}/${stem}.${TARGET_LANG_SHORT}.srt"
        "${dir}/${stem}.srt"
        "${dir}/${stem}.fr.srt"
        "${dir}/${stem}.fra.srt"
    )

    for p in "${patterns[@]}"; do
        [[ -f "$p" ]] && { echo "$p"; return 0; }
    done

    # Cherche aussi .srt avec préfixe commun
    local prefix="${stem:0:30}"
    local found
    found=$(find "$dir" -maxdepth 1 -name "${prefix}*.srt" -print -quit 2>/dev/null)
    [[ -n "$found" ]] && { echo "$found"; return 0; }

    return 1
}

# Télécharge le meilleur sous-titre avec subliminal
download_srt() {
    local video="$1"
    local lang="$2"

    log_info "Téléchargement ($lang)..."

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] subliminal download -l $lang $video"
        return 0
    fi

    local output
    output=$(subliminal download -l "$lang" "$video" 2>&1)
    local rc=$?

    if [[ $rc -ne 0 ]]; then
        log_err "Échec du téléchargement"
        echo "$output" | tail -5
        return 1
    fi

    # Vérifier qu'un .srt a été créé
    local srt
    if srt=$(find_existing_srt "$video"); then
        log_ok "Téléchargé : $(basename "$srt")"
        return 0
    else
        log_warn "Aucun .srt trouvé après téléchargement"
        return 1
    fi
}

# Répare un fichier SRT mal formé (lignes vides parasites, etc.)
repair_srt() {
    local srt="$1"
    local repaired="$2"

    if [[ "$DRY_RUN" == true ]]; then
        return 0
    fi

    python3 "$SCRIPT_DIR/repair_srt.py" "$srt" "$repaired" 2>/dev/null && return 0
    return 1
}

# Vérifie la qualité de synchronisation et ajoute un warning si nécessaire
# Retourne 0 si OK, 1 si problème détecté
check_sync_quality() {
    local video="$1"
    local srt="$2"

    if [[ "$DRY_RUN" == true ]] || [[ ! -f "$srt" ]]; then
        return 0
    fi

    local video_dur
    video_dur=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$video" 2>/dev/null || echo "0")

    # Trouver le dernier timestamp "utile" (exclure les crédits de traduction)
    local last_ts
    last_ts=$(grep -E '^[0-9]{2}:[0-9]{2}:[0-9]{2}' "$srt" | \
              grep -v 'www\.\|Synchro\|Traduit\|Firefly\|addic7ed\|Merci\|Sous-titr\|sous-titr\|- \|— ' | \
              tail -1 | awk '{print $1}')

    if [[ -z "$last_ts" ]]; then
        last_ts=$(grep -E '^[0-9]{2}:[0-9]{2}:[0-9]{2}' "$srt" | tail -1 | awk '{print $1}')
    fi

    # Convertir en secondes
    local last_sec
    last_sec=$(echo "$last_ts" | awk -F: '{print $1*3600 + $2*60 + $3}')
    local video_sec=${video_dur%.*}

    if [[ -z "$last_sec" ]] || [[ "$last_sec" == "0" ]]; then
        return 0
    fi

    local gap=$(( last_sec - video_sec ))
    local gap_abs=${gap#-}  # valeur absolue

    # Si le sous-titre a été validé manuellement → on ignore
    if is_validated "$video_name"; then
        return 0
    fi

    # Si l'écart dépasse le seuil → problème
    if [[ $gap_abs -gt $SYNC_GAP_THRESHOLD ]]; then
        local gap_fmt
        if [[ $gap -gt 0 ]]; then
            gap_fmt="+$(printf '%dm%02ds' $((gap/60)) $((gap%60)))"
        else
            gap_fmt="$(printf '%dm%02ds' $((gap/60)) $((gap%60)))"
        fi

        local video_name; video_name=$(basename "$video")

        # Trouver le dossier de la série pour le fichier warnings
        local series_dir
        series_dir=$(find_series_dir "$video")

        # Ajouter au tableau global et au tableau par série
        local warn_entry="${video_name}|écart: ${gap_fmt}|dernier sous-titre à ${last_ts} (vidéo: ${video_sec}s)"
        WARNINGS+=("$warn_entry")
        SERIES_WARNINGS["$series_dir"]+="${warn_entry}"$'\n'

        # Ajouter un sous-titre d'avertissement au début du .srt
        log_sync "Écart de synchronisation détecté : ${gap_fmt} — ajout d'un avertissement dans le .srt"
        python3 "$SCRIPT_DIR/add_warning.py" "$srt" "$gap" "$gap_fmt" 2>/dev/null || true
        return 1
    fi

    return 0
}

# Trouve le dossier de la série à partir du chemin d'une vidéo
# Ex: .../Séries/Normal People/Saison 1/episode.mkv → .../Séries/Normal People
# Ex: .../Séries/Common Side Effects/episode.mkv      → .../Séries/Common Side Effects
find_series_dir() {
    local video="$1"
    local parent; parent=$(dirname "$video")
    local grandparent; grandparent=$(dirname "$parent")

    # Si le parent contient "saison" ou "season", le dossier série est le grand-parent
    if echo "$(basename "$parent")" | grep -qi "saison\|season"; then
        echo "$grandparent"
    else
        echo "$parent"
    fi
}

# Écrit un fichier récapitulatif unique à la racine du dossier scanné
write_warning_files() {
    if [[ "$DRY_RUN" == true ]]; then
        return
    fi

    # Déterminer la racine : utiliser le premier PATH, remonter si c'est un fichier ou un dossier de saison
    local root_dir="${PATHS[0]}"
    if [[ -f "$root_dir" ]]; then
        root_dir=$(dirname "$root_dir")
    fi
    # Si on est dans un dossier de saison, remonter au dossier de la série
    if echo "$(basename "$root_dir")" | grep -qi "saison\|season"; then
        root_dir=$(dirname "$root_dir")
    fi

    local warning_file="${root_dir}/${WARNING_FILE}"

    # Collecter tous les avertissements triés par série
    local all_warnings=""
    local total=0
    while IFS= read -r series_dir; do
        [[ -z "$series_dir" ]] && continue
        local content="${SERIES_WARNINGS[$series_dir]:-}"
        [[ -z "$content" ]] && continue
        local series_name="${series_dir##*/}"
        all_warnings+="## $series_name"$'\n'
        all_warnings+="$content"$'\n'
        # Compter les entrées (une par ligne non-vide du contenu)
        local count_in_series
        count_in_series=$(echo "$content" | grep -c "écart:" 2>/dev/null) || count_in_series=0
        total=$(( total + count_in_series ))
    done < <(printf '%s\n' "${!SERIES_WARNINGS[@]}" | sort)

    if [[ -z "$all_warnings" ]] || [[ $total -eq 0 ]]; then
        # Aucun avertissement : supprimer le fichier s'il existe (tout est clean)
        rm -f "$warning_file"
        return
    fi

    {
        echo "# ⚠ Sous-titres potentiellement désynchronisés"
        echo "# Généré par SubSync Tool le $(date '+%Y-%m-%d à %H:%M')"
        echo "# Racine : $root_dir"
        echo "#"
        echo "# Chaque épisode listé ci-dessous a un écart de synchronisation"
        echo "# supérieur à ${SYNC_GAP_THRESHOLD}s entre le sous-titre et la vidéo."
        echo "# Un avertissement s'affiche au début de la lecture."
        echo "#"
        echo "# ➜ Si un sous-titre est en réalité correct, valide-le avec :"
        echo "#      subsync --validate \"Nom de l'épisode\""
        echo "#"
        echo "# ➜ Pour retirer la validation :"
        echo "#      subsync --unvalidate \"Nom de l'épisode\""
        echo "#"
        echo "# ➜ Pour relancer la vérification :"
        echo "#      subsync \"$root_dir\""
        echo ""

        # Grouper par série et formater
        local current_series=""
        while IFS= read -r line; do
            if [[ "$line" == "## "* ]]; then
                current_series="${line##\#\# }"
                echo ""
                echo "━━━ $current_series ━━━"
            elif [[ -n "$line" ]]; then
                IFS='|' read -r fname gap_detail detail <<< "$line"
                echo "▸ $fname"
                echo "  $gap_detail"
                echo "  $detail"
                echo ""
            fi
        done <<< "$all_warnings"

        echo ""
        echo "# $(date '+%Y-%m-%d %H:%M') — $total problème(s) détecté(s)"
    } > "$warning_file"

    log_info "Fichier de suivi mis à jour : ${warning_file} (${total} problème(s))"
}

# Synchronise un sous-titre avec alass
sync_with_alass() {
    local video="$1"
    local srt_input="$2"

    local dir; dir=$(dirname "$video")
    local stem; stem=$(basename "$video" | sed 's/\.[^.]*$//')
    local srt_output="${dir}/${stem}.${TARGET_LANG_SHORT}.srt"

    # Si l'entrée est déjà la sortie, passer par un fichier temporaire
    local srt_temp=""
    if [[ "$srt_input" == "$srt_output" ]]; then
        srt_temp="${srt_output}.tmp.srt"
        cp "$srt_input" "$srt_temp"
        srt_input="$srt_temp"
    fi

    # === Étape 0 : Réparer le SRT si nécessaire ===
    local srt_repaired="${srt_input}.repaired.srt"
    if repair_srt "$srt_input" "$srt_repaired"; then
        srt_input="$srt_repaired"
    fi

    log_info "Synchronisation alass..."

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] alass $video $srt_input → $srt_output"
        [[ -n "$srt_temp" ]] && rm -f "$srt_temp"
        rm -f "$srt_repaired"
        return 0
    fi

    local output rc
    output=$("$ALASS" "$video" "$srt_input" "$srt_output" 2>&1)
    rc=$?

    # === Essayer avec --no-split si échec ===
    if [[ $rc -ne 0 ]]; then
        log_info "Nouvelle tentative avec --no-split..."
        output=$("$ALASS" --no-split "$video" "$srt_input" "$srt_output" 2>&1)
        rc=$?
    fi

    # Nettoyer les fichiers temporaires
    [[ -n "$srt_temp" ]] && rm -f "$srt_temp"
    rm -f "$srt_repaired"

    if [[ $rc -ne 0 ]]; then
        log_warn "alass échoué (code $rc), sous-titre conservé tel quel"
        if [[ "$srt_input" != "$srt_output" ]]; then
            cp "$srt_input" "$srt_output"
        fi
        # Nettoyer quand même les anciens .srt
        find "$dir" -maxdepth 1 -name "${stem}*.srt" ! -name "${stem}.${TARGET_LANG_SHORT}.srt" -delete 2>/dev/null || true
        return 1
    fi

    # Extraire le ratio FPS pour info
    local fps_ratio
    fps_ratio=$(echo "$output" | grep -oP "ratio is [0-9.]+" | sed 's/ratio is //' || echo "?")
    log_ok "Synchronisé (ratio FPS: $fps_ratio)"

    # Supprimer les anciens .srt redondants
    find "$dir" -maxdepth 1 -name "${stem}*.srt" ! -name "${stem}.${TARGET_LANG_SHORT}.srt" -delete 2>/dev/null || true

    return 0
}

# Extrait les sous-titres français embedded d'un fichier vidéo
extract_embedded_srt() {
    local video="$1"
    local output="$2"

    if [[ "$DRY_RUN" == true ]]; then
        log_info "[DRY-RUN] ffmpeg extraction sous-titres embedded → $output"
        return 0
    fi

    # Trouver l'index du premier flux de sous-titre en français
    local sub_index
    sub_index=$(ffprobe -v quiet -show_entries stream=index,codec_type:stream_tags=language \
        -of csv=p=0 "$video" 2>/dev/null | grep "subtitle,fr" | head -1 | cut -d, -f1)

    if [[ -z "$sub_index" ]]; then
        return 1
    fi

    log_info "Extraction sous-titre embedded (flux #${sub_index})..."

    ffmpeg -y -v quiet -i "$video" -map 0:${sub_index} -c:s srt "$output" 2>/dev/null

    if [[ -s "$output" ]]; then
        log_ok "Sous-titre extrait : $(basename "$output")"
        return 0
    else
        rm -f "$output"
        return 1
    fi
}

# Traite une vidéo complète
process_video() {
    local video="$1"
    local video_name; video_name=$(basename "$video")

    echo ""
    echo -e "${CYAN}▶${NC} $video_name"

    # Récupérer la durée
    local duration
    duration=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$video" 2>/dev/null || echo "?")
    local duration_fmt="?"
    if [[ "$duration" != "?" ]]; then
        duration_fmt=$(printf '%02d:%02d' $(( ${duration%.*} / 60 )) $(( ${duration%.*} % 60 )))
    fi

    local dir; dir=$(dirname "$video")
    local stem; stem=$(basename "$video" | sed 's/\.[^.]*$//')
    local target="${dir}/${stem}.${TARGET_LANG_SHORT}.srt"

    local existing_srt
    existing_srt=$(find_existing_srt "$video" 2>/dev/null || true)

    # === CAS 1 : Sous-titre externe existant → synchroniser seulement ===
    if [[ -n "$existing_srt" ]] && [[ "$FORCE" != true ]]; then
        log_info "Sous-titre existant : $(basename "$existing_srt")"
        if [[ "$NO_SYNC" != true ]]; then
            sync_with_alass "$video" "$existing_srt"
            check_sync_quality "$video" "$target" || true
        else
            log_info "--no-sync : pas de synchronisation"
            if [[ "$existing_srt" != "$target" ]]; then
                [[ "$DRY_RUN" != true ]] && cp "$existing_srt" "$target"
                log_info "Renommé → $(basename "$target")"
            fi
            check_sync_quality "$video" "$target" || true
        fi
        return 0
    fi

    # === CAS 2 : Essayer d'extraire les sous-titres embedded ===
    local embedded_srt="${dir}/${stem}.embedded.fr.srt"
    if extract_embedded_srt "$video" "$embedded_srt"; then
        log_info "Sous-titre embedded extrait"
        if [[ "$NO_SYNC" != true ]]; then
            sync_with_alass "$video" "$embedded_srt"
            check_sync_quality "$video" "$target" || true
        else
            [[ "$DRY_RUN" != true ]] && cp "$embedded_srt" "$target"
            rm -f "$embedded_srt"
            log_info "Renommé → $(basename "$target")"
            check_sync_quality "$video" "$target" || true
        fi
        return 0
    fi

    # === CAS 3 : Télécharger puis synchroniser ===
    if [[ "$FORCE" == true ]]; then
        log_info "Mode FORCE : retéléchargement"
    fi

    # Étape 1 : Télécharger
    if ! download_srt "$video" "$LANG"; then
        log_err "Téléchargement impossible pour $video_name"
        return 1
    fi

    # Retrouver le sous-titre téléchargé
    local new_srt
    new_srt=$(find_existing_srt "$video" 2>/dev/null || true)
    if [[ -z "$new_srt" ]]; then
        log_err "Sous-titre introuvable après téléchargement"
        return 1
    fi

    # Étape 2 : Synchroniser
    if [[ "$NO_SYNC" != true ]]; then
        sync_with_alass "$video" "$new_srt"
        check_sync_quality "$video" "$target" || true
    else
        if [[ "$new_srt" != "$target" ]]; then
            [[ "$DRY_RUN" != true ]] && cp "$new_srt" "$target"
            log_info "Renommé → $(basename "$target")"
        fi
        check_sync_quality "$video" "$target" || true
    fi

    return 0
}

# === Scan récursif ==========================================================
find_videos() {
    local paths=("$@")
    local -a videos=()

    for p in "${paths[@]}"; do
        if [[ -f "$p" ]]; then
            local ext="${p##*.}"
            if [[ "$ext" =~ ^($VIDEO_EXTENSIONS)$ ]]; then
                videos+=("$p")
            else
                log_warn "Extension non reconnue, ignoré : $p"
            fi
        elif [[ -d "$p" ]]; then
            while IFS= read -r -d '' f; do
                videos+=("$f")
            done < <(find "$p" -type f -regextype posix-extended \
                -regex ".*\.($VIDEO_EXTENSIONS)" -print0 2>/dev/null || true)
        else
            log_warn "Chemin inexistant : $p"
        fi
    done

    printf '%s\n' "${videos[@]}" | sort -u
}

# === MAIN ===================================================================
main() {
    echo -e "${CYAN}"
    echo "╔══════════════════════════════════════════╗"
    echo "║     🎬  SubSync Tool                     ║"
    echo "║  Sous-titres automatiques synchronisés   ║"
    echo "╚══════════════════════════════════════════╝"
    echo -e "${NC}"
    echo "Langue   : $LANG ($TARGET_LANG_SHORT)"
    echo "Synchro  : $([[ "$NO_SYNC" == true ]] && echo 'non' || echo 'alass')"
    echo "Force    : $FORCE"
    echo "Dry-run  : $DRY_RUN"
    echo ""

    check_deps

    log_step "Scan des vidéos..."
    mapfile -t videos < <(find_videos "${PATHS[@]}")

    if [[ ${#videos[@]} -eq 0 ]]; then
        log_err "Aucune vidéo trouvée."
        exit 1
    fi

    log_info "${#videos[@]} vidéo(s) trouvée(s)"

    # Traiter chaque vidéo
    local ok=0 fail=0
    for video in "${videos[@]}"; do
        if process_video "$video"; then
            ((ok++))
        else
            ((fail++))
        fi
    done

    # Rapport
    echo ""
    log_step "Rapport"
    echo -e "  ${GREEN}✓ $ok traité(s)${NC}"
    [[ $fail -gt 0 ]] && echo -e "  ${RED}✗ $fail échec(s)${NC}"

    # Écrire les fichiers de warnings par série
    write_warning_files

    # Afficher les avertissements de synchronisation
    if [[ ${#WARNINGS[@]} -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}╔══════════════════════════════════════════════════════════╗${NC}"
        echo -e "${YELLOW}║  ⚠  SOUS-TITRES POTENTIELLEMENT DÉSYNCHRONISÉS          ║${NC}"
        echo -e "${YELLOW}║     Un avertissement a été ajouté au début de ces .srt  ║${NC}"
        echo -e "${YELLOW}╚══════════════════════════════════════════════════════════╝${NC}"
        for w in "${WARNINGS[@]}"; do
            IFS='|' read -r fname gap_detail detail <<< "$w"
            echo -e "  ${YELLOW}⚠${NC} ${fname}"
            echo -e "     ${gap_detail} — ${detail}"
        done
        echo ""

        # Chemin du fichier récapitulatif
        local report_root="${PATHS[0]}"
        [[ -f "$report_root" ]] && report_root=$(dirname "$report_root")
        if echo "$(basename "$report_root")" | grep -qi "saison\|season"; then
            report_root=$(dirname "$report_root")
        fi
        echo -e "${CYAN}  Récapitulatif : ${report_root}/${WARNING_FILE}${NC}"
    fi
    echo ""
}

main
