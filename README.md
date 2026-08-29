# MacBook Pro 15,1 — Warm, Natural Audio DSP for t2linux

[![GitHub Repository](https://img.shields.io/badge/Repository-GitHub-181717.svg?logo=github)](https://github.com/mynameisdeleted/mbp15-1-audio-dsp) [![Fairfax Media Git](https://img.shields.io/badge/Repository-Fairfax%20Media-003366.svg)](https://git.fairfaxmedia.net/t2linux/mbp15-1-audio-dsp.git) [![t2linux](https://img.shields.io/badge/Platform-t2linux-blue.svg)](https://wiki.t2linux.org/) [![Asahi Audio Ecosystem](https://img.shields.io/badge/Ecosystem-Asahi%20Audio-orange.svg)](https://github.com/AsahiLinux/asahi-audio) [![PipeWire](https://img.shields.io/badge/Audio-PipeWire%20%2F%20WirePlumber-red.svg)](https://pipewire.org/) [![Target Hardware](https://img.shields.io/badge/Hardware-MacBook%20Pro%2015%2C1-black.svg)]()

A custom PipeWire `filter-chain` DSP graph engineered to deliver warm, natural audio to **t2linux** on the **MacBook Pro 15,1** (2018/2019 Intel T2)—aimed at matching or beating macOS (OS X) audio quality both subjectively and objectively.

> [!NOTE]
> **Architecture:** This is **not a kernel driver**. The Linux T2 kernel/ALSA stack exposes raw speaker PCM. WirePlumber hides the raw device and splices this graph in front of it (`alsa_output.platform-sound.RawSpeakers`), executing warm voicing EQ, psychoacoustic sub-bass, 8-band dynamic control, driver crossover, FIR correction, and hard driver protection limiters.

---

## ⚡ Key Improvements Over Upstream

Upstream graphs (`asahi-audio` / `t2-apple-audio-dsp`) target a measurement-flat response that can sound thin, treble-heavy, and distort at high volumes due to missing driver limiters.

| Upstream Limitation | Solution in This Graph | Real-World Result |
|---|---|---|
| ❄️ **Thin / Cold Sound** | Equal-energy warm voicing curve (+3 dB/octave tilt) | Rich, full, balanced audio across all genres |
| 💥 **Distortion at High Volume** | Post-FIR driver limiters (`wlim` @ -2dB, `tlim` @ -1dB) | Crystal clean output at 100% volume with zero amp clipping |
| 🔊 **Woofer Over-Excursion** | 60 Hz high-pass + 8-band multiband compressor | Woofers don't bottom out or rattle on heavy bass beats |
| 🔇 **No Deep Sub-Bass** | Psychoacoustic sub-bass (`virtualbass` via Bankstown) | Extended perceived low-end without physical cone strain |
| 🎚️ **Fixed / Rigid EQ** | Isolated 8-band `user_eq` preference node | Custom tone presets that survive git updates |

---

## 🎛️ Signal Processing Chain

Audio flows through tone controls, dynamic management, ISO-226 equal loudness tracking, FIR driver correction, and physical driver protection limiters:

```mermaid
flowchart TD
    subgraph Stage1 ["1. Input & Voicing"]
        In["🔊 Audio Input"]:::input --> UserEQ["🎚️ User EQ (8-Band Tone Control)"]:::eq
        UserEQ --> EQ["🎼 Voicing EQ (+3dB/oct Warmth & 60Hz HPF)"]:::eq
    end

    subgraph Stage2 ["2. Dynamics & Headroom Management"]
        EQ --> VB["🔊 Virtual Bass (Bankstown Sub-Harmonics)"]:::dynamics
        VB --> MBComp["📊 Multiband Compressor (8-Band LSP)"]:::dynamics
        MBComp --> Limiter["🛡️ Main Limiter (Broadband Lookahead)"]:::limiter
        Limiter --> LoudComp["👂 Loudness Comp (ISO-226 Equal Loudness)"]:::dynamics
    end

    subgraph Stage3 ["3. Crossover & Driver FIR Correction"]
        LoudComp --> Copy["🔀 4-Channel Crossover Splitter"]:::input
        
        subgraph Tweeters ["Tweeter Channels"]
            Copy --> ConvLT["🔊 Tweeter L FIR (convLT)"]:::fir
            Copy --> ConvRT["🔊 Tweeter R FIR (convRT)"]:::fir
        end
        
        subgraph Woofers ["Woofer Channels"]
            Copy --> ConvLW["🔊 Woofer L FIR (convLW)"]:::fir
            Copy --> ConvRW["🔊 Woofer R FIR (convRW)"]:::fir
        end
    end

    subgraph Stage4 ["4. Driver Safety Backstops & Output"]
        ConvLT --> TLim["🛡️ Tweeter Limiter (-1 dB Ceiling)"]:::limiter
        ConvRT --> TLim
        ConvLW --> WLim["🛡️ Woofer Limiter (-2 dB Ceiling)"]:::limiter
        ConvRW --> WLim

        TLim --> Out["🔈 RawSpeakers Sink"]:::input
        WLim --> Out
    end

    classDef input fill:#2d3748,stroke:#4a5568,color:#fff;
    classDef eq fill:#2b6cb0,stroke:#3182ce,color:#fff;
    classDef dynamics fill:#d69e2e,stroke:#d69e2e,color:#000;
    classDef fir fill:#805ad5,stroke:#9f7aea,color:#fff;
    classDef limiter fill:#c53030,stroke:#e53e3e,color:#fff;
```

---

## 🚀 Quick Start

### 1. Install Dependencies
Installs required LSP & SWH plugins via your package manager (`dnf`, `pacman`, `apt`, `zypper`) and builds Bankstown from source:
```bash
./install-deps.sh
```

### 2. Apply Graph
Preflights FIR paths and plugin URIs, merges user EQ overrides, copies the configuration to WirePlumber, and reloads:
```bash
./apply.sh
```

> [!TIP]
> Ensure **"MacBook Pro 15,1 DSP Speakers"** is selected as the default output in your desktop sound settings.

---

## 🎚️ Sound Profiles & User EQ

Customize tone settings without touching calibrated internal DSP nodes. `user_eq` sits at the front of the chain, so even aggressive boosts are safely governed by downstream multiband limiters.

### Quick Preset Setup

1. **Create your override file:**
   ```bash
   cp user_eq.example.json user_eq.json
   ```
2. **Edit `user_eq.json`** with your preferred gain multipliers (`g_0` to `g_7`) and apply:
   ```bash
   ./apply.sh
   ```

### Recommended Tone Presets

| Profile | 70 Hz (`g_0`) | 110 Hz (`g_1`) | 220 Hz (`g_2`) | 450 Hz (`g_3`) | 1 kHz (`g_4`) | 2.5 kHz (`g_5`) | 6 kHz (`g_6`) | 10 kHz (`g_7`) |
|---|---|---|---|---|---|---|---|---|
| **Reference (Flat)** | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` |
| **Rock / Pop** | `1.00` | `1.26` | `1.00` | `0.94` | `1.00` | `1.12` | `1.19` | `1.12` |
| **Classical / Acoustic** | `1.00` | `1.00` | `1.06` | `1.00` | `1.00` | `1.00` | `1.12` | `1.12` |
| **Electronic / Hip-Hop** | `1.26` | `1.19` | `1.00` | `0.94` | `1.00` | `1.00` | `1.06` | `1.00` |
| **Movie (Dialogue Focus)**| `0.84` | `0.94` | `1.00` | `1.06` | `1.19` | `1.19` | `1.06` | `1.00` |
| **Movie (Action / Bass)** | `1.41` | `1.12` | `1.00` | `1.00` | `1.00` | `1.06` | `1.12` | `1.12` |
| **Late-Night (Low Level)** | `0.63` | `0.79` | `1.00` | `1.00` | `1.06` | `1.12` | `1.00` | `0.94` |

*(Note: Gain values are linear multipliers: `1.0` = 0 dB, `1.41` ≈ +3 dB boost, `0.71` ≈ -3 dB cut)*

---

## 🛠️ Fine-Tuning Guide

If your specific physical unit requires custom acoustic tuning:

* **Woofer Ceiling:** Edit `wlim.control.limit` in `graph.json` (Default: `-2` dB. Lower to `-3` / `-4` dB for stricter mechanical protection).
* **Bass Drive:** Adjust `equalizer.control` (`g_1` through `g_5`).
* **Sub-Bass Synthesis:** Adjust `virtualbass.control.amt` (Default: `1.0`).

---

## 📚 Documentation & Repository Links

### 🔗 Repositories & Mirrors
* 🐙 **GitHub Repository:** [github.com/mynameisdeleted/mbp15-1-audio-dsp](https://github.com/mynameisdeleted/mbp15-1-audio-dsp)
* 🏢 **Fairfax Media Git Server:** [git.fairfaxmedia.net/t2linux/mbp15-1-audio-dsp](https://git.fairfaxmedia.net/t2linux/mbp15-1-audio-dsp.git)

### 📖 Guides & Deep Dives
* 📖 **[INSTALL.md](INSTALL.md)** — Full prerequisites, manual plugin build steps, package manager lookup, and troubleshooting.
* 🎓 **[README.advanced.md](README.advanced.md)** — Comprehensive electroacoustic design rationale, magnitude-vs-power physics, gain staging equations, issue tracebacks, and complete parameter reference.
* 📊 **[mb-compressor-params.md](mb-compressor-params.md)** — Detailed parameter guide for the 8-band LSP multiband compressor.

---

## 🔄 Reverting to Stock

To return to the stock PipeWire graph provided by `t2-apple-audio-dsp`:
```bash
sudo cp /path/to/t2-apple-audio-dsp/configs/15_1/graph.json \
        /usr/share/t2-linux-audio/15_1/graph.json
systemctl --user restart wireplumber
```
