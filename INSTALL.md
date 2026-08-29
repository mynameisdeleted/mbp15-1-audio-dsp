# Install

How to get this DSP graph running on a **MacBook Pro 15,1** under Linux (T2 /
`t2linux`, or Asahi on the Intel-T2 stack where applicable).

For what the graph *does*, see [README.md](README.md). This file is only the
mechanics of getting the pieces in place.

---

## 1. What has to be true first

This repo is **just a `graph.json`** (plus `apply.sh`). It is not a driver and
not self-contained. Three things must already exist on the machine:

| Requirement | Provided by | Why |
|---|---|---|
| Raw speaker PCM exposed by the kernel/ALSA | the `t2linux` kernel + ALSA stack | there is nothing to process otherwise |
| A hidden sink `alsa_output.platform-sound.RawSpeakers` with a filter-chain spliced in front of it | the **t2 speaker-DSP package** (`t2-linux-audio` / `t2-apple-audio-dsp`), specifically its WirePlumber drop-in `51-t2-dsp.conf` | this graph *attaches to* that spliced filter-chain; no package → no sink → nothing to apply |
| The FIR correction files at `/usr/share/t2-linux-audio/15_1/` | the same package | `graph.json` references them by absolute path (see §4) |
| The LV2 plugins the graph loads | your distro + a source build for one of them | see §3 |

If `wpctl status` shows no **"MacBook Pro 15,1 DSP Speakers"** sink and no
`alsa_output.platform-sound.RawSpeakers`, stop here and install the t2 speaker-DSP
package for your distro first — see <https://wiki.t2linux.org/guides/audio-config/>.

---

## 2. Get the repo

```sh
git clone <this-repo> mbp15-1-audio-dsp
cd mbp15-1-audio-dsp
chmod +x apply.sh install-deps.sh    # if git didn't preserve the bit
```

---

## 3. LV2 plugin dependencies

The graph loads four LV2 plugins from three bundles. (`copy` and `convolver` are
PipeWire builtins — nothing to install.)

> **Shortcut:** `./install-deps.sh` does everything in this section — detects
> `dnf`/`pacman`/`apt`/`zypper`, installs LSP + SWH, builds Bankstown from source
> if it's missing, then verifies all five URIs. The manual steps below are what
> it runs, for reference or when it can't.

| Plugin URI in `graph.json` | Bundle | Package (varies by distro) |
|---|---|---|
| `http://lsp-plug.in/plugins/lv2/para_equalizer_x16_stereo` | LSP Plugins | `lsp-plugins` / `lsp-plugins-lv2` |
| `http://lsp-plug.in/plugins/lv2/mb_compressor_stereo` | LSP Plugins | ″ |
| `http://lsp-plug.in/plugins/lv2/loud_comp_mono` | LSP Plugins | ″ |
| `http://plugin.org.uk/swh-plugins/fastLookaheadLimiter` | SWH Plugins | `swh-plugins` / `lv2-swh-plugins` |
| `https://chadmed.au/bankstown` | Bankstown | **not packaged on most distros — build from source** |

### 3a. LSP + SWH (from your package manager)

```sh
# Fedora / Fedora Asahi Remix
sudo dnf install lsp-plugins swh-plugins

# Arch / t2linux
sudo pacman -S lsp-plugins swh-plugins       # or AUR: lsp-plugins-lv2

# Debian / Ubuntu
sudo apt install lsp-plugins swh-plugins
```

Package names drift — if the above miss, search: `dnf search lsp`,
`pacman -Ss lsp-plugins`, `apt-cache search swh`. The authority is whether the
URIs resolve (§3c), not the package name.

### 3b. Bankstown (source build)

Bankstown (`virtualbass` in the graph) is chadmed's psychoacoustic bass plugin.
On Fedora Asahi Remix it ships in the `asahi-audio` stack; everywhere else,
build it:

```sh
# needs: rust/cargo, clang, lv2 headers, git
git clone https://github.com/chadmed/bankstown
cd bankstown
make                       # runs: cargo build --release

# install the bundle. LIBDIR defaults to /usr/lib64 — override on distros
# that use /usr/lib (Arch, Debian/Ubuntu):
sudo make install                       # Fedora
sudo make install LIBDIR=/usr/lib       # Arch, Debian, Ubuntu
# → installs to $LIBDIR/lv2/bankstown.lv2/

cd ..
```

Per-user install (no sudo) also works — copy the built
`target/release/libbankstown.so` → `~/.lv2/bankstown.lv2/bankstown.so` alongside
`bankstown.ttl` and `manifest.ttl` from the repo.

### 3c. Verify all four URIs resolve

```sh
for uri in \
  http://lsp-plug.in/plugins/lv2/para_equalizer_x16_stereo \
  http://lsp-plug.in/plugins/lv2/mb_compressor_stereo \
  http://lsp-plug.in/plugins/lv2/loud_comp_mono \
  http://plugin.org.uk/swh-plugins/fastLookaheadLimiter \
  https://chadmed.au/bankstown ; do
    lv2ls | grep -qxF "$uri" && echo "ok   $uri" || echo "MISSING $uri"
done
```

Every line must say `ok`. `lv2ls` is from `lilv` (`lilv-utils` / `lilv`).

---

## 4. FIR correction files

`graph.json` references them by **absolute path**:

```
/usr/share/t2-linux-audio/15_1/tweeters-44k.wav   tweeters-48k.wav   tweeters-96k.wav
/usr/share/t2-linux-audio/15_1/woofers-44k.wav    woofers-48k.wav    woofers-96k.wav
```

```sh
ls -l /usr/share/t2-linux-audio/15_1/*.wav
```

These are **not vendored in this repo** and the paths are **deliberately not
relative**:

- The t2 speaker-DSP package installs them to this fixed FHS path on every
  distro, and you already need that package for the sink to exist at all (§1),
  so the absolute path is stable wherever the prerequisite is met.
- PipeWire's convolver resolves a non-absolute `filename` against the process
  working directory, which for a WirePlumber-spawned service is unpredictable
  (`/` or `$HOME`). Relative paths would be *less* portable, not more.

If you have your own recalibrated FIRs, drop them at that path (or edit the six
`filename` entries in `graph.json` to point at yours) before §5.

---

## 5. Apply

```sh
./apply.sh
```

`apply.sh`:

1. validates `graph.json` is well-formed JSON (`python3` or `jq`)
2. **builds the effective graph** → `~/.audiograph.json`: if `user_eq.json`
   exists next to the script, its contents replace the `user_eq` node's
   `control` block (`jq`); otherwise it's a straight copy of `graph.json` (§7)
3. checks `/usr/share/t2-linux-audio/15_1/` exists (§1)
4. checks every FIR `.wav` **referenced by the graph** is present (§4)
5. checks every LV2 plugin URI **the graph loads** resolves in `lv2ls` (§3)

then `sudo cp`s `~/.audiograph.json` into place, restarts WirePlumber, and
confirms the sink came up. Steps 4–5 read the paths/URIs straight out of the
merged graph, so they stay correct if you edit either file.

Pass `-f` to skip the preflight (JSON validation still runs):

```sh
./apply.sh -f
```

---

## 6. Confirm it loaded

```sh
wpctl status | grep -i "DSP Speakers"
pw-cli ls Node | grep -i t2-151-speakers
```

Select **"MacBook Pro 15,1 DSP Speakers"** as the output (`wpctl set-default
<id>`, or your DE's sound settings), then play something.

To watch the plugins actually run / spot xruns:

```sh
pw-top        # look for the filter-chain node, check for XRUN
```

---

## 7. Pick a sound profile

`user_eq` is the first node in the graph — an 8-band tone control that defaults
flat (= the reference voicing). To change it without touching the committed
`graph.json`:

```sh
cp user_eq.example.json user_eq.json      # git-ignored
$EDITOR user_eq.json                        # set the g_* values
./apply.sh                                  # merges it into ~/.audiograph.json and installs
```

`jq` must be installed for this path. Delete `user_eq.json` to return to the
default. Preset values (Rock, Classical, Movie–dialogue, …) are in
[README.md § User preference EQ](README.md#user-preference-eq).

---

## 8. After a system update

A `t2-linux-audio` package update **overwrites**
`/usr/share/t2-linux-audio/15_1/graph.json` and silently reverts to the stock
graph. Re-run `./apply.sh` afterward. (Plugin packages updating is fine — the
graph only cares that the URIs still resolve.)

---

## 9. Revert to stock

```sh
sudo cp /path/to/t2-apple-audio-dsp/configs/15_1/graph.json \
        /usr/share/t2-linux-audio/15_1/graph.json
systemctl --user restart wireplumber
```

Or reinstall the t2 speaker-DSP package.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No "DSP Speakers" sink after apply | t2 speaker-DSP package / `51-t2-dsp.conf` not installed | §1 |
| Sink present, but silent / falls back to another device | a plugin URI failed to load, so the whole filter-chain fails | §3c — find the `MISSING` line |
| `wireplumber` won't start after apply | malformed `graph.json` | `python3 -m json.tool graph.json`; `journalctl --user -u wireplumber -b` |
| Works, but no bass enhancement | `bankstown` (`virtualbass`) not loaded | §3b, then §3c |
| Distortion when loud | drive too high for your unit — see [README.md § Tuning knobs](README.md#tuning-knobs) | lower `wlim.limit`, or the `user_eq` bass bands |
| Reverted itself after an update | expected — see §8 | re-run `./apply.sh` |
