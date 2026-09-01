#!/bin/bash
# Apply the MacBook Pro 15,1 audio DSP graph:
# build the effective graph, preflight the prerequisites, install, reload.
#
#   ./apply.sh          validate + preflight + build + install + reload
#   ./apply.sh -f       skip the preflight checks (JSON validation still runs)
#
# If  user_eq.json  exists next to this script, its contents replace the
# "user_eq" node's control block (requires jq) - copy user_eq.example.json to
# user_eq.json and edit. The merged graph is written to ~/.audiograph.json and
# that file is what gets installed.

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
GRAPH_SRC="$SCRIPT_DIR/graph.json"
OVERRIDE="$SCRIPT_DIR/user_eq.json"
MERGED="$HOME/.audiograph.json"
GRAPH_DST="/usr/share/t2-linux-audio/15_1/graph.json"

FORCE=0
SIMPLE=1
HOT=0
for arg in "${@:-}"; do
    case "$arg" in
        -f|--force|--no-check) FORCE=1 ;;
        -b|--bake|--simple) SIMPLE=1 ;;
        --full|--unbaked) SIMPLE=0 ;;
        -r|--restart|--cold) HOT=0 ;;
        -h|--hot|--soft) HOT=1 ;;
    esac
done

have() { command -v "$1" >/dev/null 2>&1; }
die()  { echo "Error: $*" >&2; exit 1; }

copy_file_safe() {
    src="$1"
    dst="$2"
    dst_dir="$(dirname "$dst")"
    if [ -w "$dst_dir" ] 2>/dev/null; then
        cp "$src" "$dst.tmp" 2>/dev/null || sudo cp "$src" "$dst.tmp" 2>/dev/null
        mv -f "$dst.tmp" "$dst" 2>/dev/null || sudo mv -f "$dst.tmp" "$dst" 2>/dev/null
    else
        sudo cp "$src" "$dst.tmp" 2>/dev/null || true
        sudo mv -f "$dst.tmp" "$dst" 2>/dev/null || true
    fi
}

PROFILE_DIR="$(python3 "$SCRIPT_DIR/detect_hardware.py" 2>/dev/null || echo "$SCRIPT_DIR/laptop-configs/apple/mbp15_1")"
if [ ! -d "$PROFILE_DIR" ]; then
    PROFILE_DIR="$SCRIPT_DIR/15_1"
fi

if [ "$SIMPLE" -eq 1 ]; then
    echo "==> Baking static DSP stages into single-stage FIR files..."
    python3 "$SCRIPT_DIR/bake-graph.py" || die "bake-graph.py failed"
    GRAPH_SRC="$SCRIPT_DIR/graph_simple.json"
    echo "==> Installing baked FIR files -> /usr/share/t2-linux-audio/15_1/"
    SRC_DIR="$PROFILE_DIR"
    if [ ! -d "$SRC_DIR" ] || ! compgen -G "$SRC_DIR/baked-*.wav" >/dev/null; then
        SRC_DIR="$SCRIPT_DIR/15_1"
    fi
    for f in "$SRC_DIR"/baked-*.wav; do
        if [ -f "$f" ]; then
            bn="$(basename "$f")"
            copy_file_safe "$f" "/usr/share/t2-linux-audio/15_1/$bn"
        fi
    done
fi

# --- json validation helper -------------------------------------------
json_ok() {
    have python3 && { python3 -c 'import json, sys; json.load(open(sys.argv[1]))' "$1" 2>/dev/null && return 0; return 1; }
    have jq      && { jq . "$1" >/dev/null 2>&1 && return 0; return 1; }
    return 2  # cannot check
}

json_ok "$GRAPH_SRC"; rc=$?
[ "$rc" -eq 1 ] && die "graph.json is not valid JSON"
[ "$rc" -eq 2 ] && echo "warn: no python3/jq - skipping JSON validation"
[ "$rc" -eq 0 ] && echo "ok: graph.json is valid JSON"

# --- build the effective graph -> ~/.audiograph.json --------------------
if [ -f "$OVERRIDE" ]; then
    have jq || die "$OVERRIDE exists but jq is not installed"
    jq -e . "$OVERRIDE" >/dev/null 2>&1 || die "$OVERRIDE is not valid JSON"
    jq -e 'any(.["filter.graph"].nodes[]; .name == "user_eq")' "$GRAPH_SRC" >/dev/null \
        || die "$GRAPH_SRC has no node named user_eq to override"
    jq --slurpfile ov "$OVERRIDE" \
       '(.["filter.graph"].nodes[] | select(.name == "user_eq") | .control) = $ov[0]' \
       "$GRAPH_SRC" > "$MERGED" || die "jq merge failed"
    echo "ok: merged user_eq.json -> $MERGED"
else
    cp "$GRAPH_SRC" "$MERGED"
    echo "ok: no user_eq.json - graph as-is -> $MERGED"
fi

json_ok "$MERGED"; rc=$?
[ "$rc" -eq 1 ] && die "merged graph $MERGED is not valid JSON"

# --- preflight (against the merged graph) ------------------------------
if [ "$FORCE" -eq 0 ]; then
    [ -d "$(dirname "$GRAPH_DST")" ] || die \
        "destination directory $(dirname "$GRAPH_DST") does not exist (is t2-linux-audio-15-1 installed?)"

    # check all convolver wav files exist
    if have jq; then
        wav_files=$(jq -r '.. | .filename? | strings' "$MERGED")
        for wav in $wav_files; do
            [ -f "$wav" ] || die "FIR WAV file missing: $wav"
        done
        echo "ok: FIR .wav files present"
    fi

    # check plugin URIs resolve
    if have lv2ls && have jq; then
        installed_lv2=$(lv2ls)
        graph_lv2=$(jq -r '.["filter.graph"].nodes[] | select(.type=="lv2") | .plugin' "$MERGED")
        for uri in $graph_lv2; do
            echo "$installed_lv2" | grep -Fqx "$uri" || die \
                "LV2 plugin URI missing: $uri (check lilv-utils/installed plugins)"
        done
        echo "ok: all LV2 plugins resolve"
    else
        echo "warn: lv2ls not found - cannot verify plugins (install lilv-utils / lilv)"
    fi
fi

wp() {
    if have wpctl; then
        timeout 1.5s wpctl "$@" 2>/dev/null || true
    fi
}

# --- preserve master volume (only needed for full WirePlumber restart) --
SAVED_VOL=""
IS_MUTED=0
if [ "$HOT" -eq 0 ]; then
    VOL_OUT="$(wp get-volume @DEFAULT_AUDIO_SINK@)"
    if [ -n "$VOL_OUT" ]; then
        SAVED_VOL="$(echo "$VOL_OUT" | awk '{print $2}')"
        if echo "$VOL_OUT" | grep -qi "MUTED"; then
            IS_MUTED=1
        fi
    fi
fi

# --- install ----------------------------------------------------------
echo "Installing $MERGED -> $GRAPH_DST"
copy_file_safe "$MERGED" "$GRAPH_DST"

if [ "$HOT" -eq 1 ]; then
    echo "Hot-reloading WirePlumber graph (zero stream drop)..."
    if systemctl --user reload wireplumber 2>/dev/null || pkill -HUP -f wireplumber 2>/dev/null; then
        echo "ok: sent SIGHUP live reload to WirePlumber"
        sleep 0.4
    else
        echo "warn: SIGHUP reload failed - restarting WirePlumber service fallback"
        systemctl --user restart wireplumber 2>/dev/null || true
        sleep 1.0
    fi
else
    # --- full PipeWire & WirePlumber cold restart ------------------------
    echo "Restarting WirePlumber (re-initialising ALSA cards)..."
    systemctl --user stop wireplumber 2>/dev/null || true
    sleep 0.4
    systemctl --user start wireplumber
    sleep 1.0
fi

# --- wait for DSP sink to be active & restore master volume ------------
for i in {1..8}; do
    if wp status | grep -qi "DSP Speakers"; then
        break
    fi
    sleep 0.5
done

# Force unmute & default sink set on EVERY run (fallback volume 0.80 if unsaved)
TARGET_VOL="${SAVED_VOL:-0.80}"

DSP_ID="$(wp status | grep -i "DSP Speakers" | grep -oE '[0-9]+\.' | head -n1 | tr -d '.')"
if [ -n "$DSP_ID" ]; then
    wp set-default "$DSP_ID"
    wp set-mute "$DSP_ID" 0
    wp set-volume "$DSP_ID" "$TARGET_VOL"
    if have pactl; then
        pactl list short sink-inputs 2>/dev/null | awk '{print $1}' | while read -r stream_id; do
            if [ -n "$stream_id" ]; then
                pactl move-sink-input "$stream_id" "audio_effect.t2-151-speakers" 2>/dev/null || true
            fi
        done
    fi
fi

wp set-mute @DEFAULT_AUDIO_SINK@ 0
wp set-volume @DEFAULT_AUDIO_SINK@ "$TARGET_VOL"

if [ "$IS_MUTED" -eq 1 ]; then
    wp set-mute @DEFAULT_AUDIO_SINK@ 1
    [ -n "$DSP_ID" ] && wp set-mute "$DSP_ID" 1
fi
echo "ok: unmuted & active sink set (vol: ${TARGET_VOL})"

# --- confirm --------------------------------------------------------
if wp status | grep -qi "DSP Speakers"; then
    echo "Done - 'MacBook Pro 15,1 DSP Speakers' sink is up."
else
    echo "Done - graph installed, WirePlumber reloaded."
    echo "If no 'DSP Speakers' sink shows: journalctl --user -u wireplumber -b -e"
fi
