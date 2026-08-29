#!/bin/bash
# Install the LV2 plugins this DSP graph loads:
#   LSP Plugins  - para_equalizer_x16_stereo, mb_compressor_stereo, loud_comp_mono
#   SWH Plugins  - fastLookaheadLimiter
#   Bankstown    - https://chadmed.au/bankstown   (built from source)
#
# Does NOT install the t2 speaker-DSP package (FIR .wav files + the WirePlumber
# splice that creates the sink). See INSTALL.md sections 1 and 4 for that.

set -u

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BUILD_DIR="$SCRIPT_DIR/build"

URIS=(
    http://lsp-plug.in/plugins/lv2/para_equalizer_x16_stereo
    http://lsp-plug.in/plugins/lv2/mb_compressor_stereo
    http://lsp-plug.in/plugins/lv2/loud_comp_mono
    http://plugin.org.uk/swh-plugins/fastLookaheadLimiter
    https://chadmed.au/bankstown
)

have()     { command -v "$1" >/dev/null 2>&1; }
lv2_have() { have lv2ls && lv2ls 2>/dev/null | grep -qxF "$1"; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if have sudo; then SUDO="sudo"; else
        echo "Error: run as root or install sudo." >&2; exit 1
    fi
fi

if   have dnf;    then PM=dnf
elif have pacman; then PM=pacman
elif have apt;    then PM=apt
elif have zypper; then PM=zypper
else PM=""; fi

have lv2ls || echo "note: lv2ls not found - install 'lilv-utils' (deb) / 'lilv' (arch/fedora) to verify URIs"

# ---------------------------------------------------------------- LSP + SWH
need_lsp=1; need_swh=1
lv2_have http://lsp-plug.in/plugins/lv2/para_equalizer_x16_stereo && need_lsp=0
lv2_have http://plugin.org.uk/swh-plugins/fastLookaheadLimiter    && need_swh=0

pkgs=()
[ "$need_lsp" -eq 1 ] && pkgs+=(lsp-plugins)
[ "$need_swh" -eq 1 ] && pkgs+=(swh-plugins)

if [ "${#pkgs[@]}" -gt 0 ]; then
    if [ -z "$PM" ]; then
        echo "!! No supported package manager (dnf/pacman/apt/zypper). Install manually: ${pkgs[*]}"
        exit 1
    fi
    echo "==> Installing ${pkgs[*]} via $PM"
    case "$PM" in
        dnf)    $SUDO dnf install -y "${pkgs[@]}" ;;
        pacman) $SUDO pacman -S --needed --noconfirm "${pkgs[@]}" ;;
        apt)    $SUDO apt-get update && $SUDO apt-get install -y "${pkgs[@]}" ;;
        zypper) $SUDO zypper install -y "${pkgs[@]}" ;;
    esac
else
    echo "==> LSP + SWH already present"
fi

# ---------------------------------------------------------------- Bankstown
if lv2_have https://chadmed.au/bankstown; then
    echo "==> Bankstown already present"
else
    echo "==> Building Bankstown from source"
    missing=()
    have git   || missing+=(git)
    have cargo || missing+=(rust/cargo)
    { have cc || have clang; } || missing+=(clang)
    if [ "${#missing[@]}" -gt 0 ]; then
        echo "!! Missing build tools: ${missing[*]}"
        echo "   Fedora: $SUDO dnf install git rust cargo clang"
        echo "   Arch:   $SUDO pacman -S git rust clang"
        echo "   Debian: $SUDO apt install git cargo clang"
        exit 1
    fi

    LIBDIR=/usr/lib64
    [ -d /usr/lib64/lv2 ] || [ -d /usr/lib64 ] || LIBDIR=/usr/lib

    mkdir -p "$BUILD_DIR"
    if [ -d "$BUILD_DIR/bankstown/.git" ]; then
        git -C "$BUILD_DIR/bankstown" pull --ff-only
    else
        git clone https://github.com/chadmed/bankstown "$BUILD_DIR/bankstown"
    fi
    make -C "$BUILD_DIR/bankstown"                       # -> cargo build --release
    $SUDO make -C "$BUILD_DIR/bankstown" install LIBDIR="$LIBDIR"
    echo "   installed to $LIBDIR/lv2/bankstown.lv2/"
fi

# ---------------------------------------------------------------- verify
echo
echo "==> Verifying plugin URIs"
fail=0
if have lv2ls; then
    for u in "${URIS[@]}"; do
        if lv2ls | grep -qxF "$u"; then
            echo "   ok       $u"
        else
            echo "   MISSING  $u"; fail=1
        fi
    done
else
    echo "   lv2ls unavailable - skipping"
    fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "All plugins resolve. Next: ./apply.sh"
else
    echo "Not all plugins resolve - see INSTALL.md section 3."
    exit 1
fi
