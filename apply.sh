#!/bin/bash
# Apply the MacBook Pro 15,1 audio DSP graph:
# validate JSON, preflight the prerequisites, install, reload WirePlumber.
#
#   ./apply.sh              full checks
#   ./apply.sh -f           skip the preflight checks (still validates JSON)

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
GRAPH_SRC="$SCRIPT_DIR/graph.json"
GRAPH_DST="/usr/share/t2-linux-audio/15_1/graph.json"

FORCE=0
case "${1:-}" in -f|--force|--no-check) FORCE=1 ;; esac

have() { command -v "$1" >/dev/null 2>&1; }
die()  { echo "Error: $*" >&2; exit 1; }

[ -f "$GRAPH_SRC" ] || die "$GRAPH_SRC not found"

# 1. valid JSON -----------------------------------------------------------
if have python3; then
    python3 -m json.tool "$GRAPH_SRC" >/dev/null || die "graph.json is not valid JSON"
    echo "ok: graph.json is valid JSON"
elif have jq; then
    jq -e . "$GRAPH_SRC" >/dev/null || die "graph.json is not valid JSON"
    echo "ok: graph.json is valid JSON"
else
    echo "warn: no python3/jq - skipping JSON validation"
fi

if [ "$FORCE" -eq 0 ]; then
    # 2. t2 speaker-DSP package present --------------------------------
    [ -d "$(dirname "$GRAPH_DST")" ] || die \
"$(dirname "$GRAPH_DST") is missing - install the t2 speaker-DSP package first (INSTALL.md section 1)"

    # 3. FIR files referenced by the graph exist ----------------------
    miss=0
    while IFS= read -r w; do
        [ -f "$w" ] || { echo "  missing FIR: $w"; miss=1; }
    done < <(grep -oE '/[^" ]+\.wav' "$GRAPH_SRC" | sort -u)
    [ "$miss" -eq 0 ] && echo "ok: FIR .wav files present" \
        || die "FIR files missing - INSTALL.md section 4"

    # 4. every LV2 plugin URI the graph loads resolves ---------------
    if have lv2ls; then
        miss=0
        while IFS= read -r u; do
            lv2ls | grep -qxF "$u" || { echo "  missing plugin: $u"; miss=1; }
        done < <(grep '"plugin"' "$GRAPH_SRC" | grep -oE 'https?://[^"]+' | sort -u)
        [ "$miss" -eq 0 ] && echo "ok: all LV2 plugins resolve" \
            || die "LV2 plugins missing - run ./install-deps.sh (INSTALL.md section 3)"
    else
        echo "warn: lv2ls not found - cannot verify plugins (install lilv-utils / lilv)"
    fi
fi

# 5. install ------------------------------------------------------------
echo "Copying graph.json -> $GRAPH_DST"
sudo cp "$GRAPH_SRC" "$GRAPH_DST"

echo "Restarting WirePlumber"
systemctl --user restart wireplumber

# 6. confirm ----------------------------------------------------------
sleep 1
if have wpctl && wpctl status 2>/dev/null | grep -qi "DSP Speakers"; then
    echo "Done - 'MacBook Pro 15,1 DSP Speakers' sink is up."
else
    echo "Done - graph copied, WirePlumber restarted."
    echo "If no 'DSP Speakers' sink shows: journalctl --user -u wireplumber -b -e"
fi
