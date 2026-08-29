# LSP `mb_compressor_stereo` — parameter reference

Every key in the `multiband_compressor` node of [graph.json](graph.json), with the
LSP port name in **bold** and the JSON symbol in `code`. Values shown are the
ones currently in the graph (8-band split, `split-limiting` branch).

Source of truth: `mb_compressor_stereo.ttl` from lsp-plugins 25.08.

## Global (once, not per band)

| Key | LSP name | Value | Meaning |
|---|---|---|---|
| `enabled` | Enabled | 1 | plugin active |
| `mode` | Compressor mode | 1 = **Modern** | band-split topology. `0` Classic = analog-style tree of crossovers; `1` Modern = flat per-band summation (cleaner, used here); `2` Linear Phase = FIR, high latency |
| `g_in` / `g_out` | Input / Output gain | 1.0 / 1.4 | linear. `g_out 1.4` ≈ +3 dB — where the EQ's `g_in 0.5` pad is restored, *after* the band detectors |
| `g_dry` / `g_wet` | Dry / Wet gain | 0.0001 / 1.0 | parallel mix — effectively 100 % wet |

## Crossover (index 1–7)

| Key | LSP name | Meaning |
|---|---|---|
| `cbe_N` | **Compression band enable N** | turns split point N on → creates that band boundary. All 7 = `1` → 8 bands |
| `sf_N` | **Split frequency N** (Hz) | the crossover frequency. Currently `60 / 80 / 100 / 130 / 160 / 200 / 500` |

## Per band (index 0–7)

| Key | LSP name | Units | Meaning |
|---|---|---|---|
| `ce_N` | **Compressor enable N** | toggle | band compresses (`0` = passes flat) |
| `al_N` | **Attack threshold N** | linear gain (0.001–1.0) | the threshold — level above this is compressed. dB = 20·log₁₀(g); `0.093` ≈ −21 dB |
| `at_N` | **Attack time N** | ms | how fast gain reduction engages once over threshold |
| `rt_N` | **Release time N** | ms | how fast gain recovers once back under threshold |
| `cr_N` | **Ratio N** | x:1 (1–100) | dB in per dB out above threshold. `1` = off, `2` = gentle, `50` ≈ brick-wall limiter |
| `kn_N` | **Knee N** | linear gain (0.063–1.0) | width of the soft transition **around** the threshold. `1.0` = hard corner; **lower = wider / softer** (`0.063` ≈ ±24 dB — ratio ramps in over a huge range). Plugin default `0.5` (−6 dB) |
| `mk_N` | **Makeup gain N** | linear (0.001–1000) | post-compression level trim for the band. `1.5` ≈ +3.5 dB, `2.0` = +6 dB |
| `scm_N` | **Sidechain mode N** | enum | detector: `0` = **Peak**, `1` RMS, `2` LPF, `3` SMA. Peak is used on every band (right for limiting; plugin default is RMS) |
| `bth_N` | **Boost threshold N** | linear gain (1e-6–1e-3) | only used when band compression mode = Up / Boost. **Inert here** — see note below |
| `bsa_N` | **Boost signal amount N** | linear gain (2.5e-4–3981) | ditto — inert |

Other per-band ports exist in the plugin but are left at default and not written
to the graph: `cm_N` (compression mode: Down/Up/Boost — default Down),
`bs_N`/`bm_N` (band solo/mute), `rrl_N`/`rl_N` (release threshold/level — `0` =
track the attack threshold), and the `sc*_N` sidechain family
(`sce_/scs_/sscs_/sla_/scr_/scp_/sclc_…`).

## Current bands, in plain English

| Band | Range | `al` (thr) | `at` / `rt` | `cr` | `kn` | `mk` | reads as |
|---|---|---|---|---|---|---|---|
| 0 | < 60 Hz | 0.093 (−21 dB) | 2 / 120 ms | 50 | 0.10 (−20 dB) | 1.5 (+3.5 dB) | fast brick-wall; near-empty behind the 60 Hz EQ high-pass |
| 1 | 60–80 Hz | 0.078 (−22 dB) | 5 / 120 ms | 50 | 0.06 (−24 dB, clamped) | 1.5 (+3.5 dB) | lowest ceiling, 50:1, softest knee → heavy but gradual |
| 2 | 80–100 Hz | 0.095 (−20 dB) | 6 / 130 ms | 30 | 0.12 (−18 dB) | 1.7 (+4.6 dB) | one notch gentler than band 1 |
| 3 | 100–130 Hz | 0.120 (−18 dB) | 8 / 150 ms | 20 | 0.20 (−14 dB) | 2.0 (+6 dB) | old "90–200" midbass character |
| 4 | 130–160 Hz | 0.130 (−18 dB) | 8 / 150 ms | 18 | 0.24 (−12 dB) | 2.0 (+6 dB) | " |
| 5 | 160–200 Hz | 0.140 (−17 dB) | 9 / 150 ms | 16 | 0.28 (−11 dB) | 2.0 (+6 dB) | eases toward the body band |
| 6 | 200–500 Hz | 0.159 (−16 dB) | 10 / 150 ms | 15 | 0.30 (−10 dB) | 2.0 (+6 dB) | low-mid body (snare / male vocal) |
| 7 | 500 Hz+ | 0.284 (−11 dB) | 8 / 150 ms | 5 | 0.40 (−8 dB) | 1.3 (+2.3 dB) | single gentle catch-all above 500 Hz |

## Notes / gotchas

- **Knee direction.** Lower `kn` = **wider / softer** knee, not harder. `kn_1 =
  0.06` on the 60–80 Hz band is the softest the plugin allows (it clamps `0.06`
  → `0.063`). That band still pulls peaks down hard because of the low threshold
  + 50:1 ratio; the wide knee just means the ratio ramps in gradually starting
  well below −22 dB (so there is some low-level gain reduction too). To clamp
  those octaves only near the ceiling and keep them cleaner below it, *raise*
  `kn_1` / `kn_2` toward `0.3`–`0.5`.

- **`bth_N` / `bsa_N` are dead config.** Set to `1.0` in the graph (inherited
  from upstream) but their valid ranges are ~`1e-6`–`1e-3` and
  `2.5e-4`–`3981` — the host clamps them. They only apply to upward / boost
  compression, which is not enabled (`cm_N` is never set, so every band is
  downward), so it is harmless.

- **`al_N` is linear, not dB.** Same for `kn_N`, `mk_N`, `g_*`. Convert with
  `dB = 20·log₁₀(value)`.
