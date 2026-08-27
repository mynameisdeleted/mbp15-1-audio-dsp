#!/bin/bash
# Apply script for MacBook Pro 15,1 audio DSP graph edits

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
GRAPH_SRC="$SCRIPT_DIR/graph.json"
GRAPH_DST="/usr/share/t2-linux-audio/15_1/graph.json"

if [ ! -f "$GRAPH_SRC" ]; then
    echo "Error: $GRAPH_SRC not found!"
    exit 1
fi

echo "Copying graph.json to system path..."
sudo cp "$GRAPH_SRC" "$GRAPH_DST"

echo "Restarting WirePlumber..."
systemctl --user restart wireplumber

echo "Done! The new DSP configuration is loaded."
