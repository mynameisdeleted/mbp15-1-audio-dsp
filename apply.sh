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
SIMPLE=0
for arg in "${@:-}"; do
    case "$arg" in
        -f|--force|--no-check) FORCE=1 ;;
        -b|--bake|--simple) SIMPLE=1 ;;
    esac
done

if [ "$SIMPLE" -eq 1 ]; then
    echo "==> Baking static DSP stages into single-stage FIR files..."
    python3 "$SCRIPT_DIR/bake-graph.py" || die "bake-graph.py failed"
    GRAPH_SRC="$SCRIPT_DIR/graph_simple.json"
    echo "==> Installing baked FIR files -> /usr/share/t2-linux-audio/15_1/"
    sudo cp "$SCRIPT_DIR/15_1/baked-"*.wav "/usr/share/t2-linux-audio/15_1/" || die "Failed to copy baked FIR files"
fi

have() { command -v "$1" >/dev/null 2>&1; }
die()  { echo "Error: $*" >&2; exit 1; }

# 0 = valid, 1 = invalid, 2 = no validator available
json_ok() {
    if   have python3; then python3 -m json.tool "$1" >/dev/null 2>&1
    elif have jq;      then jq -e . "$1" >/dev/null 2>&1
    else return 2; fi
}

[ -f "$GRAPH_SRC" ] || die "$GRAPH_SRC not found"

json_ok "$GRAPH_SRC"; rc=$?
[ "$rc" -eq 1 ] && die "graph.json is not valid JSON"
[ "$rc" -eq 2 ] && echo "warn: no python3/jq - skipping JSON validation"
[ "$rc" -eq 0 ] && echo "ok: graph.json is valid JSON"

# --- build the effective graph -> ~/.audiograph.json --------------------
if [ "$SIMPLE" -eq 1 ]; then
    cp "$GRAPH_SRC" "$MERGED"
    echo "ok: baked single-stage graph_simple.json -> $MERGED"
elif [ -f "$OVERRIDE" ]; then
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
"$(dirname "$GRAPH_DST") is missing - install the t2 speaker-DSP package first (INSTALL.md section 1)"

    miss=0
    while IFS= read -r w; do
        [ -f "$w" ] || { echo "  missing FIR: $w"; miss=1; }
    done < <(grep -oE '/[^" ]+\.wav' "$MERGED" | sort -u)
    [ "$miss" -eq 0 ] && echo "ok: FIR .wav files present" \
        || die "FIR files missing - INSTALL.md section 4"

    if have lv2ls; then
        miss=0
        while IFS= read -r u; do
            lv2ls | grep -qxF "$u" || { echo "  missing plugin: $u"; miss=1; }
        done < <(grep '"plugin"' "$MERGED" | grep -oE 'https?://[^"]+' | sort -u)
        [ "$miss" -eq 0 ] && echo "ok: all LV2 plugins resolve" \
            || die "LV2 plugins missing - run ./install-deps.sh (INSTALL.md section 3)"
    else
        echo "warn: lv2ls not found - cannot verify plugins (install lilv-utils / lilv)"
    fi
fi

# --- preserve master volume --------------------------------------------
SAVED_VOL=""
IS_MUTED=0
if have wpctl; then
    VOL_OUT="$(wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null || true)"
    if [ -n "$VOL_OUT" ]; then
        SAVED_VOL="$(echo "$VOL_OUT" | awk '{print $2}')"
        if echo "$VOL_OUT" | grep -qi "MUTED"; then
            IS_MUTED=1
        fi
    fi
fi

# --- install ----------------------------------------------------------
if [ "$SIMPLE" -eq 1 ]; then
    echo "Installing baked FIR files -> $(dirname "$GRAPH_DST")/"
    sudo cp "$SCRIPT_DIR/15_1/baked-"*.wav "$(dirname "$GRAPH_DST")/"
fi

echo "Installing $MERGED -> $GRAPH_DST"
sudo cp "$MERGED" "$GRAPH_DST"

echo "Restarting WirePlumber"
systemctl --user restart wireplumber

# --- restore master volume ---------------------------------------------
sleep 1
if [ -n "$SAVED_VOL" ] && have wpctl; then
    wpctl set-volume @DEFAULT_AUDIO_SINK@ "$SAVED_VOL" 2>/dev/null || true
    if [ "$IS_MUTED" -eq 1 ]; then
        wpctl set-mute @DEFAULT_AUDIO_SINK@ 1 2>/dev/null || true
    fi
    echo "ok: preserved master volume (${SAVED_VOL})"
fi

# --- confirm --------------------------------------------------------
if have wpctl && wpctl status 2>/dev/null | grep -qi "DSP Speakers"; then
    echo "Done - 'MacBook Pro 15,1 DSP Speakers' sink is up."
else
    echo "Done - graph installed, WirePlumber restarted."
    echo "If no 'DSP Speakers' sink shows: journalctl --user -u wireplumber -b -e"
fi
