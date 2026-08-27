# MacBook Pro 15,1 — custom speaker DSP graph

A modified PipeWire `filter-chain` graph for the built-in speakers of the
**MacBook Pro 15,1** (Intel T2) running Linux, plus a script to install it.

This is **not a driver**. The T2 kernel/ALSA stack exposes the raw speaker PCM;
WirePlumber (via `t2-linux-audio`'s `51-t2-dsp.conf`) renames it to
`alsa_output.platform-sound.RawSpeakers`, hides it, and splices this graph in
front of it. The graph does the crossover, voicing EQ, dynamics, and FIR
correction that the T2's own DSP does under macOS.

## Origin

Forked from `configs/15_1/graph.json` in
[lemmyg/t2-apple-audio-dsp](https://github.com/lemmyg/t2-apple-audio-dsp)
(which itself borrows FIR filters and structure from
[chadmed/asahi-audio](https://github.com/chadmed/asahi-audio)).

All structural elements are unchanged: node names, FIR `.wav` paths
(`/usr/share/t2-linux-audio/15_1/`), `capture.props` / `playback.props`,
`target.object = alsa_output.platform-sound.RawSpeakers`, 4-channel FL/FR/RL/RR
output, allowed rates 48000/44100, and the `capture.volumes` mapping that ties
the sink volume slider to the loudness-compensation stage.

## Signal chain

```
in ─▶ equalizer ─▶ virtualbass ─▶ multiband_compressor ─▶ limiter ─▶ ell/elr ─▶ copyL/R ─┬▶ convLT/convRT (tweeter FIR) ─▶ out
     (LSP x16)     (bankstown)   (LSP mb_comp x4)      (fastLookahead) (loud_comp)        └▶ convLW/convRW (woofer FIR)  ─▶ out
```

## Changes vs. upstream `15_1/graph.json`

| Stage | Upstream | This fork | Purpose |
|---|---|---|---|
| Pre-EQ | *none* | LSP `para_equalizer_x16_stereo`, `g_in 0.7` | Warm/bass-forward voicing curve |
| EQ band 0 | n/a | 24 dB/oct **high-pass @ 50 Hz** (`ft_0 2`, `s_0 1`) | Keep subsonic energy off the small woofers |
| Dynamics | single-band `compressor_stereo` | `mb_compressor_stereo`, 4 bands (xover 120/400/1000 Hz) | See rationale below |
| Woofer FIR gain | `1.0` | `1.5` (`convLW` / `convRW`) | More low-end output (overdrive) |

Everything else is byte-identical to upstream.

## Design rationale

**Goal:** mild-volume music should sound warm and full; bass-heavy material
should not distort the woofers or duck the midrange.

- **Warm at low volume** is handled two ways:
  - `ell` / `elr` (`loud_comp_mono`) is a true ISO-226 equal-loudness
    compensator. The sink volume slider feeds `ell:volume` / `elr:volume`
    (cubic, −65→0 dB), so bass/treble lift automatically increases as you turn
    the volume down and recedes as you turn it up.
  - The static EQ bells (31.5–125 Hz, +1.4 to +2.5 dB) add a fixed warmth tilt.

- **Bass beats don't distort** is handled by multiband, not broadband,
  compression. A single-band compressor keyed off a kick drum applies gain
  reduction to the *whole* spectrum — vocals and mids pump on every beat, and
  loud bass can shut the woofers down across all frequencies. The multiband
  confines the gain reduction to band 0 (< 120 Hz): ~10:1 above ≈ −17 dB with a
  10 ms attack, so the sub band is clamped to a near-fixed ceiling while the
  midrange stays open.

- **`virtualbass` (bankstown)** synthesizes harmonics of the bass in the
  60–150 Hz window, so the ear perceives low end the driver never has to
  physically produce — the psychoacoustic counterpart to the 50 Hz high-pass.

## Tuning knobs

In `graph.json`, `multiband_compressor.control`:

| Key | Now | Effect |
|---|---|---|
| `al_0` | `0.142` (≈ −17 dB) | Bass clamp threshold — lower = clamps sooner |
| `cr_0` | `10.0` | Bass ratio — raise toward 20:1+ for true limiting |
| `at_0` | `10.0` ms | Lower to ~5 ms if kick transients still poke through |
| `ce_1` / `ce_2` / `ce_3` | `1` | Set to `0` to disable bands 1–3 and compress **only** the bass |
| `sf_1` | `120.0` Hz | Lower to ~90–100 Hz to keep band 0 off the low mids |

In `graph.json`, woofer convolvers (`convLW` / `convRW`): `gain 1.5` sets actual
woofer SPL — the dynamics ceiling won't save you if this is too hot; back toward
`1.35` if heavy bass still distorts.

## Install

```sh
./apply.sh
```

This copies `graph.json` to `/usr/share/t2-linux-audio/15_1/graph.json` (needs
`sudo`) and restarts WirePlumber (`systemctl --user restart wireplumber`).

Requires the `t2-linux-audio` / `t2-apple-audio-dsp` package to already be
installed (it provides the FIR `.wav` files, `51-t2-dsp.conf`, and the
`mic.json` graph).

## Revert

```sh
sudo cp /path/to/t2-apple-audio-dsp/configs/15_1/graph.json \
        /usr/share/t2-linux-audio/15_1/graph.json
systemctl --user restart wireplumber
```

Note: a `t2-linux-audio` package update will overwrite the installed file and
silently revert these changes — re-run `./apply.sh` afterward.
