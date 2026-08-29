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

## Prior art — why this fork

Two recurring complaints about the upstream chains, from their own issue
trackers and docs, motivated the changes here:

**It sounds thin / not warm enough.** `asahi-audio` deliberately targets *"a
mostly flat response ... without adding an excessive amount of colour"* and
explicitly rejects Apple's *"exaggerated Harman curve."* Flat magnitude is
equal-energy-per-*Hz*, which reads as bass-light against pink-balanced program
material (see [Design rationale](#why-the-voicing-curve-exists--and-why-upstream-sounds-thin)).
Users keep asking for the warmth back:

- [asahi-audio #31](https://github.com/AsahiLinux/asahi-audio/issues/31) — request for a bass/treble ("smiley") curve + a guide to change it system-wide; closed with no documented answer.
- [asahi-audio #93](https://github.com/AsahiLinux/asahi-audio/issues/93) — *"Lacks proper bass and high frequencies, sounding flat, thin, and muddy";* closed as not planned.
- [t2-apple-audio-dsp #21](https://github.com/lemmyg/t2-apple-audio-dsp/issues/21) (direct upstream) — *"Quality is good but volume is quite low even at maximum volume."*
- [Asahi audio docs](https://asahilinux.org/docs/sw/audio-userspace/) known issues: the 13″ MBA EQ *"might be a bit harsh on the treble."*

**It distorts when loud, because there is no output limiter.** The Asahi docs
state plainly: *"There is no final limiter/compressor in the current DSP
chains"* (only an input compressor), so *"content in high-gain regions of the EQ
curve might cause distortion or clipping."* They also flag *"the 200 Hz region"*
for distortion risk and note `bankstown` is *"prone to saturation artifacts at
high volumes."*

- [asahi-audio #22](https://github.com/AsahiLinux/asahi-audio/issues/22) — j313 distortion at 100 %; traced to convolver gain being too hot, worked around by dropping it to ~0.6.
- [asahi-audio #42](https://github.com/AsahiLinux/asahi-audio/issues/42) — J474 distortion above 72 % volume.
- [asahi-audio #91](https://github.com/AsahiLinux/asahi-audio/issues/91) — j313 *"severe speaker distortion"* at 55 %; `speakersafetyd` logs nothing, i.e. it's in the signal processing, not the protection model.

This fork's answers, point by point:

| Upstream complaint | Change here |
|---|---|
| flat / thin / "not warm enough" | EQ bass tilt (≈ +3 dB/octave per-Hz) ahead of the dynamics |
| no final limiter → clipping in high-gain EQ regions | `limiter` + post-FIR `wlim` / `tlim` on the real driver signal |
| 200 Hz distortion risk | fine multiband split through the low-mids |
| `bankstown` saturates at volume | EQ `g_in 0.5` pad + `sat_second` / `sat_third` reduced |
| convolver gain too hot at 100 % (#22) | FIR kept near unity; drive lives in the dynamically-governed EQ |
| "volume too low at max" (#21) | `g_out` makeup + loudness maximisation into the limiters |

## Signal chain

```
in ─▶ user_eq ─▶ equalizer ─▶ virtualbass ─▶ multiband_compressor ─▶ limiter ─▶ ell/elr ─▶ copyL/R ─┬▶ convLT/convRT ─▶ tlim ─▶ out
     (LSP x16)   (LSP x16)    (bankstown)   (LSP mb_comp x8)      (fastLookahead) (loud_comp)        │  (tweeter FIR)   (limit)
     user prefs  voicing                                                                             └▶ convLW/convRW ─▶ wlim ─▶ out
                                                                                                        (woofer FIR)    (limit)
```

## Changes vs. upstream `15_1/graph.json`

| Stage | Upstream | This fork | Purpose |
|---|---|---|---|
| Pre-EQ | *none* | LSP `para_equalizer_x16_stereo`, `g_in 0.5` | Warm/bass-forward voicing curve |
| Gain staging | n/a | EQ `g_in` padded to 0.5 (≈ −6 dB); the ~3 dB net loss restored at `multiband_compressor.g_out 1.4`, with band thresholds `al_*` scaled to match | Run the EQ + `virtualbass` cooler; recover level only after the compressor detectors, right before the limiter |
| EQ band 0 | n/a | 48 dB/oct **high-pass @ 60 Hz** (`ft_0 2`, `s_0 3`) | Kill everything below the woofer's usable range — −3 dB at 60 Hz, ≈ −30 dB by 40 Hz |
| Dynamics | single-band `compressor_stereo` | `mb_compressor_stereo`, **8 bands** (xover 60/80/100/130/160/200/500 Hz), Modern mode | Per-band peak control that doesn't duck the mids on a bass beat; the woofer range is split finely (five bands 60–200 Hz) so the 60–80 and 80–100 Hz octaves can be clamped harder than the rest |
| Woofer FIR gain | `1.0` | `1.15` (`convLW` / `convRW`) | Small trim only; the low-end drive now lives in the EQ bass bells (upstream, so it passes through the compressor + limiters instead of being an uncontrolled post-gain) |
| Bass EQ bells | n/a | 31.5–200 Hz boosted ~+2.3 dB above the base warm tilt to offset the FIR gain reduction | Same woofer output level, but dynamically governed |
| Post-FIR limiters | *none* | `wlim` (−2 dB) after woofer FIR, `tlim` (−1 dB) after tweeter FIR | Hard ceiling on the *actual* driver signal — excursion / clip backstop |

Everything else is byte-identical to upstream.

## Design rationale

**Goal:** mild-volume music should sound warm and full; bass-heavy material
should not distort the woofers or duck the midrange.

### Why the voicing curve exists — and why upstream sounds thin

Music is mastered for systems with a roughly **equal-energy-per-octave** (pink)
balance and the headroom to reproduce it. The forked FIR filters (`asahi-audio` /
`t2-apple-audio-dsp`) correct the drivers to **flat magnitude = equal energy per
_Hz_** — measurement-correct, but each octave down then carries the same per-Hz
energy across half the bandwidth, so it lands **bass-light** ("not warm enough").
Matching the per-octave balance needs ≈ **+3 dB/octave** of per-Hz lift toward the
lows — that is what the EQ bass bells are for.

That tilt can't be static. The two things it can break are different above and
below **~150 Hz**:

| Region | Failure mode | Scaling | Guarded by |
|---|---|---|---|
| **< ~150 Hz** | woofer **over-excursion** — cone bottoms out | displacement ∝ 1/f² ≈ **+12 dB/octave** for constant SPL | fine multiband split (one limiter per bass octave, held release) + the 20 Hz subsonic HPF; `virtualbass` supplies deep sub as harmonics so the cone never has to move for it |
| **> ~150 Hz** | **over-voltage** — demanded level exceeds the amp's max swing to the cone | ≈ flat (voltage/thermal, not displacement) | multiband peak control per band, then `limiter` / `wlim` / `tlim` as backstop |

The `fastLookaheadLimiter` stages are a *second* line of defence only, because
they are **broadband**: when one triggers it ducks every frequency at once, so a
loud trombone transient pulls the violins down with it. The multiband compressor
is the *first* line precisely because its gain reduction stays inside the
offending band — the more work it does, the less the broadband limiters engage
and the cleaner the result. Net: full warmth at low level, graceful flattening
toward the FIR's flat-per-Hz curve as it gets loud, with cheap pitch-reinforcing
harmonic distortion traded for ugly (and mechanically risky) excursion
distortion.

### Warm at low volume

- **Warm at low volume** is handled two ways:
  - `ell` / `elr` (`loud_comp_mono`) is a true ISO-226 equal-loudness
    compensator. The sink volume slider feeds `ell:volume` / `elr:volume`
    (cubic, −65→0 dB), so bass/treble lift automatically increases as you turn
    the volume down and recedes as you turn it up.
  - The static EQ bells (31.5–125 Hz) add a fixed warmth tilt. Note LSP's `g_*`
    ports are **linear amplitude, not dB** — `g_3 = 3.26` is ≈ +10 dB, offset by
    `g_in 0.5` (≈ −6 dB). This is a hot bass shelf on purpose; the dynamics
    stages below exist to keep it safe when loud. The bass boost lives here
    rather than in the woofer FIR gain (kept near unity at 1.15) so it passes
    through the compressor and limiters and is dynamically controlled, instead
    of being a fixed post-everything gain that only `wlim` can catch.

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
  loud bass can shut the woofers down across all frequencies. The 8-band
  multiband keeps each band responding only to its own energy. The seven bands
  below ~500 Hz — where over-excursion and boom live — are effectively limiters:

  | Band | Range | `cr` | `kn` | `al` (≈ dB) | Note |
  |---|---|---|---|---|---|
  | 0 | < 60 Hz | 50 | 0.10 | 0.093 (−21) | catch band — mostly empty now that the EQ HPFs hard at 60 Hz |
  | 1 | 60–80 Hz | 50 | 0.06 | 0.078 (−22) | hardest clamp — lowest ceiling, highest ratio, widest (softest) knee so the 50:1 eases in |
  | 2 | 80–100 Hz | 30 | 0.12 | 0.095 (−20) | clamped harder than the rest, a step gentler than 60–80 |
  | 3 | 100–130 Hz | 20 | 0.20 | 0.120 (−18) | midbass, as the old 90–200 band |
  | 4 | 130–160 Hz | 18 | 0.24 | 0.130 (−18) | |
  | 5 | 160–200 Hz | 16 | 0.28 | 0.140 (−17) | |
  | 6 | 200–500 Hz | 15 | 0.30 | 0.159 (−16) | low-mid body, as the old 200–500 band |
  | 7 | 500 Hz+ | 5 | 0.40 | 0.284 (−11) | single gentle band above 500 Hz (was three: 500/1500/5000) |

  (Every `mb_compressor` port is documented in
  [mb-compressor-params.md](mb-compressor-params.md).)

  Band 1 (60–80 Hz) and band 2 (80–100 Hz) carry the lowest ceilings and the
  highest ratios, so the two octaves that drive woofer excursion hardest are
  clamped ahead of everything else — their wide knees (`kn` down at `0.06` /
  `0.12`, i.e. −24 / −18 dB) make that heavy ratio ramp in gradually rather than
  snap. Band 7 limits gently (`cr 5`) and does not
  move because of a kick drum. The EQ is left untouched, so anything below the
  thresholds — i.e. quiet listening — passes with its full warm tilt intact;
  only loud peaks are clamped.

- **Woofers can't bottom out.** The woofer FIR is near unity now (`1.15`), but
  `loud_comp` still adds bass gain after the main limiter, so the very last
  stage is unguarded. `wlim` / `tlim` are `fastLookaheadLimiter` instances placed
  *after* the convolvers, so they clamp the real signal the drivers see
  regardless of upstream gain. `wlim` at −2 dB is the mechanical-excursion
  backstop; `tlim` at −1 dB protects the tweeters and keeps the two paths
  time-aligned (equal lookahead latency — no comb filtering at the crossover).

- **`virtualbass` (bankstown)** synthesizes harmonics of the bass in the
  60–150 Hz window, so the ear perceives low end the driver never has to
  physically produce — the psychoacoustic counterpart to the 60 Hz high-pass.

## User preference EQ

`user_eq` is the **first node in the graph** and the only block meant for
hand-editing — a plain 8-band tone control for matching the sound to content
type. It defaults **flat** (every `g_*` = `1.0`), which *is* the reference
voicing; editing it never touches the calibrated `equalizer` / dynamics below.
Because it sits ahead of the compressor and limiters, even an aggressive preset
is dynamically governed — it can't clip or over-excurse, it just gets
compressed if pushed hard.

| Band | `f` | Type | Region |
|---|---|---|---|
| 0 | 70 Hz | low shelf | sub weight / rumble |
| 1 | 110 Hz | bell | bass punch |
| 2 | 220 Hz | bell | warmth / boom |
| 3 | 450 Hz | bell | body / mud |
| 4 | 1 kHz | bell | mids / nasal |
| 5 | 2.5 kHz | bell | presence / attack |
| 6 | 6 kHz | bell | detail / sibilance |
| 7 | 10 kHz | high shelf | air |

Values are **linear, not dB** (`+3 dB ≈ 1.41`, `−3 dB ≈ 0.71`). Keep each `g_*`
between `0.5` (−6 dB) and `2.0` (+6 dB).

Two ways to set it, both followed by `./apply.sh`:

- **Override file (recommended, survives `git pull`).** Copy the template and
  edit it:
  ```sh
  cp user_eq.example.json user_eq.json
  $EDITOR user_eq.json
  ```
  `user_eq.json` is git-ignored. When present, `apply.sh` splices its contents
  into the `user_eq` node's `control` block with `jq`, writes the result to
  `~/.audiograph.json`, and installs that. Delete `user_eq.json` to go back to
  the committed default.
- **Edit `graph.json` directly** — change the `g_*` in the `user_eq` `control`
  block. Simple, but a `git pull` will conflict.

### Presets — the 8 `g_*` values, `g_0`…`g_7`

| Preset | 70 | 110 | 220 | 450 | 1k | 2.5k | 6k | 10k |
|---|---|---|---|---|---|---|---|---|
| **Reference** (flat) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| Rock / Pop | 1.00 | 1.26 | 1.00 | 0.94 | 1.00 | 1.12 | 1.19 | 1.12 |
| Classical / Acoustic | 1.00 | 1.00 | 1.06 | 1.00 | 1.00 | 1.00 | 1.12 | 1.12 |
| Electronic / Hip-Hop | 1.26 | 1.19 | 1.00 | 0.94 | 1.00 | 1.00 | 1.06 | 1.00 |
| Movie — dialogue | 0.84 | 0.94 | 1.00 | 1.06 | 1.19 | 1.19 | 1.06 | 1.00 |
| Movie — action | 1.41 | 1.12 | 1.00 | 1.00 | 1.00 | 1.06 | 1.12 | 1.12 |
| Late-night (low level) | 0.63 | 0.79 | 1.00 | 1.00 | 1.06 | 1.12 | 1.00 | 0.94 |

## Tuning knobs

If the woofers still bottom out or anything distorts, in order of preference:

| Where | Key | Now | Effect |
|---|---|---|---|
| `wlim.control` | `limit` | `-2` | Lower to `-3` / `-4` — hard woofer ceiling, dB |
| `equalizer.control` | `g_1`–`g_5` | `1.82 / 2.48 / 3.26 / 2.61 / 1.75` | The bass boost — lower all five proportionally for less low-end drive overall |
| `convLW` / `convRW` `config` | `gain` | `1.15` | FIR trim; leave it — adjust the EQ bells instead |
| `multiband_compressor.control` | `al_0` | `0.093` (≈ −21 dB) | Lower = < 60 Hz band clamps sooner |
| `multiband_compressor.control` | `al_1` / `al_2` | `0.078` / `0.095` | The 60–80 / 80–100 Hz ceilings — lower these two to pull the peak down further in those octaves |
| `multiband_compressor.control` | `cr_1` / `kn_1` | `50.0` / `0.06` | 60–80 Hz clamp — highest ratio, widest knee. Less aggressive: lower `cr_1` toward `20`. Sharper corner / less low-level squash: raise `kn_1` toward `1.0` |
| `multiband_compressor.control` | `cr_2` / `kn_2` | `30.0` / `0.12` | 80–100 Hz clamp — a step gentler than 60–80 |
| `multiband_compressor.control` | `cr_0` | `50.0` | Already near brick-wall; leave it |
| `multiband_compressor.control` | `at_0` | `4.0` ms | Lower toward ~3 ms if kick transients poke through (adds some LF harmonic distortion) |

If the midrange sounds over-controlled / lifeless, raise `al_3`–`al_7` (higher =
those bands stay out of the way longer) or lower their ratios `cr_3`–`cr_7`
toward `2.0`. Band 6 (200–500 Hz) at `cr 15` reaches into low-mid body — if male
vocals / snare sound boxy or thin, drop `cr_6` back toward `8`.

**Gain staging.** To run the EQ / `virtualbass` even cooler, lower
`equalizer.g_in` further (e.g. `0.4`, `0.35`) and put the same factor back into
`multiband_compressor.g_out`, then scale `al_0`–`al_7` by that factor so the
compressor keeps the same behaviour. If bass feels thinner after the pad, nudge
`virtualbass.amt` up (`1.0` → `1.2`) rather than raising `g_in` back.

`tlim.control` `limit` (`-1`) is the tweeter ceiling — rarely needs touching, but
**keep `tlim` present even if you disable it** (`limit` high), because it also
holds the tweeter/woofer time alignment.

## Install

Full instructions — prerequisites, the LV2 plugin dependencies (LSP, SWH, and a
source build of Bankstown), the FIR files, verification and troubleshooting —
are in **[INSTALL.md](INSTALL.md)**.

Short version, with the `t2-linux-audio` / `t2-apple-audio-dsp` package already
installed (it provides the FIR `.wav` files, `51-t2-dsp.conf` and `mic.json`):

```sh
./install-deps.sh   # LSP + SWH plugins, builds Bankstown from source
./apply.sh          # preflights, then copies the graph in and reloads WirePlumber
```

`apply.sh` refuses to install if a referenced FIR file or plugin URI is missing
(`-f` skips those checks).

## Revert

```sh
sudo cp /path/to/t2-apple-audio-dsp/configs/15_1/graph.json \
        /usr/share/t2-linux-audio/15_1/graph.json
systemctl --user restart wireplumber
```

Note: a `t2-linux-audio` package update will overwrite the installed file and
silently revert these changes — re-run `./apply.sh` afterward. See
[INSTALL.md § 8](INSTALL.md#8-after-a-system-update).
