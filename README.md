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
in ─▶ equalizer ─▶ virtualbass ─▶ multiband_compressor ─▶ limiter ─▶ ell/elr ─▶ copyL/R ─┬▶ convLT/convRT ─▶ tlim ─▶ out
     (LSP x16)     (bankstown)   (LSP mb_comp x6)      (fastLookahead) (loud_comp)        │  (tweeter FIR)   (limit)
                                                                                          └▶ convLW/convRW ─▶ wlim ─▶ out
                                                                                             (woofer FIR)    (limit)
```

## Changes vs. upstream `15_1/graph.json`

| Stage | Upstream | This fork | Purpose |
|---|---|---|---|
| Pre-EQ | *none* | LSP `para_equalizer_x16_stereo`, `g_in 0.5` | Warm/bass-forward voicing curve |
| Gain staging | n/a | EQ `g_in` padded to 0.5 (≈ −6 dB); the ~3 dB net loss restored at `multiband_compressor.g_out 1.4`, with band thresholds `al_*` scaled to match | Run the EQ + `virtualbass` cooler; recover level only after the compressor detectors, right before the limiter |
| EQ band 0 | n/a | 24 dB/oct **high-pass @ 50 Hz** (`ft_0 2`, `s_0 1`) | Keep subsonic energy off the small woofers |
| Dynamics | single-band `compressor_stereo` | `mb_compressor_stereo`, **6 bands** (xover 90/200/500/1500/5000 Hz), Modern mode | Per-band peak control that doesn't duck the mids on a bass beat |
| Woofer FIR gain | `1.0` | `1.5` (`convLW` / `convRW`) | More low-end output (overdrive) |
| Post-FIR limiters | *none* | `wlim` (−2 dB) after woofer FIR, `tlim` (−1 dB) after tweeter FIR | Hard ceiling on the *actual* driver signal — excursion / clip backstop |

Everything else is byte-identical to upstream.

## Design rationale

**Goal:** mild-volume music should sound warm and full; bass-heavy material
should not distort the woofers or duck the midrange.

- **Warm at low volume** is handled two ways:
  - `ell` / `elr` (`loud_comp_mono`) is a true ISO-226 equal-loudness
    compensator. The sink volume slider feeds `ell:volume` / `elr:volume`
    (cubic, −65→0 dB), so bass/treble lift automatically increases as you turn
    the volume down and recedes as you turn it up.
  - The static EQ bells (31.5–125 Hz) add a fixed warmth tilt. Note LSP's `g_*`
    ports are **linear amplitude, not dB** — `g_3 = 2.5` is ≈ +8 dB, offset by
    `g_in 0.5` (≈ −6 dB). This is a hot bass shelf on purpose; the dynamics
    stages below exist to keep it safe when loud.

- **Gain staging.** `g_in` on the EQ is padded to 0.5 so the boosted bands and
  `virtualbass`'s saturation stages run with headroom rather than near/over
  0 dBFS. The signal path is 32-bit float end-to-end (real clipping only happens
  at the ALSA sink), but a cooler operating point keeps `virtualbass` from being
  over-driven and keeps every plugin's internal detectors honest. The ~3 dB net
  level loss is put back at `multiband_compressor.g_out` (1.0 → 1.4) — *after*
  the band detectors, immediately before the main limiter — and the band
  thresholds `al_*` were scaled by the same factor so the compressor behaves
  exactly as before, just at a lower internal level.

- **Bass beats don't distort** is handled by multiband, not broadband,
  compression. A single-band compressor keyed off a kick drum applies gain
  reduction to the *whole* spectrum — vocals and mids pump on every beat, and
  loud bass can shut the woofers down across all frequencies. The 6-band
  multiband keeps each band responding only to its own energy. The three bands
  below ~500 Hz — where over-excursion and boom live — are effectively limiters:
  band 0 (< 90 Hz) `cr 50`, band 1 (90–200 Hz) `cr 20`, band 2 (200–500 Hz)
  `cr 15`. Bands 3–5 above that limit gently (`cr 5–6`) and none of them move
  because of a kick drum. The EQ is left untouched, so anything below the
  thresholds — i.e. quiet listening — passes with its full warm tilt intact;
  only loud peaks are clamped.

- **Woofers can't bottom out.** Everything above only limits *before* the
  woofer FIR, which then adds another +3.5 dB, and `loud_comp` adds bass gain
  after that. `wlim` / `tlim` are `fastLookaheadLimiter` instances placed
  *after* the convolvers, so they clamp the real signal the drivers see
  regardless of upstream gain. `wlim` at −2 dB is the mechanical-excursion
  backstop; `tlim` at −1 dB protects the tweeters and keeps the two paths
  time-aligned (equal lookahead latency — no comb filtering at the crossover).

- **`virtualbass` (bankstown)** synthesizes harmonics of the bass in the
  60–150 Hz window, so the ear perceives low end the driver never has to
  physically produce — the psychoacoustic counterpart to the 50 Hz high-pass.

## Tuning knobs

If the woofers still bottom out or anything distorts, in order of preference:

| Where | Key | Now | Effect |
|---|---|---|---|
| `wlim.control` | `limit` | `-2` | Lower to `-3` / `-4` — hard woofer ceiling, dB |
| `convLW` / `convRW` `config` | `gain` | `1.5` | Back toward `1.35` — less low-end drive overall |
| `multiband_compressor.control` | `al_0` | `0.093` (≈ −21 dB) | Lower = bass band clamps sooner |
| `multiband_compressor.control` | `cr_0` | `50.0` | Already near brick-wall; leave it |
| `multiband_compressor.control` | `at_0` | `6.0` ms | Lower to ~4 ms if kick transients poke through (adds some LF harmonic distortion) |

If the midrange sounds over-controlled / lifeless, raise `al_1`–`al_5` (higher =
those bands stay out of the way longer) or lower their ratios `cr_1`–`cr_5`
toward `2.0`. Band 2 (200–500 Hz) at `cr 15` reaches into low-mid body — if male
vocals / snare sound boxy or thin, drop `cr_2` back toward `8`.

**Gain staging.** To run the EQ / `virtualbass` even cooler, lower
`equalizer.g_in` further (e.g. `0.4`, `0.35`) and put the same factor back into
`multiband_compressor.g_out`, then scale `al_0`–`al_5` by that factor so the
compressor keeps the same behaviour. If bass feels thinner after the pad, nudge
`virtualbass.amt` up (`1.0` → `1.2`) rather than raising `g_in` back.

`tlim.control` `limit` (`-1`) is the tweeter ceiling — rarely needs touching, but
**keep `tlim` present even if you disable it** (`limit` high), because it also
holds the tweeter/woofer time alignment.

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
