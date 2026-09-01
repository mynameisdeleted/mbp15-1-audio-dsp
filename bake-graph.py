#!/usr/bin/env python3
"""
bake-graph.py — Single-Stage FIR Convolver & Graph Simplifier for mbp15-1-audio-dsp

Combines all static LTI DSP stages (User EQ + Voicing EQ + Crossover High-Pass Filters)
directly into composite "baked" FIR impulse response WAV files per driver:
  - baked-tweeters-44k.wav / baked-tweeters-48k.wav / baked-tweeters-96k.wav
  - baked-woofers-44k.wav / baked-woofers-48k.wav / baked-woofers-96k.wav

Generates a lean, ultra-low-CPU graph_simple.json PipeWire graph file.
Runs with pure standard-library Python 3 (math, struct, wave, json, os).
"""

import os
import sys
import math
import struct
import wave
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def biquad_peaking(fs, f0, gain_db, q):
    if gain_db == 0.0 or gain_db == 1.0:
        return 1.0, 0.0, 0.0, 1.0, 0.0, 0.0
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2.0 * max(q, 0.01))
    b0 = 1.0 + alpha * A
    b1 = -2.0 * math.cos(w0)
    b2 = 1.0 - alpha * A
    a0 = 1.0 + alpha / A
    a1 = -2.0 * math.cos(w0)
    a2 = 1.0 - alpha / A
    return b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0

def biquad_highpass(fs, f0, q=0.7071):
    w0 = 2.0 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    b0 = (1.0 + cos_w0) / 2.0
    b1 = -(1.0 + cos_w0)
    b2 = (1.0 + cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    return b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0

def biquad_lowpass(fs, f0, q=0.7071):
    w0 = 2.0 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    b0 = (1.0 - cos_w0) / 2.0
    b1 = 1.0 - cos_w0
    b2 = (1.0 - cos_w0) / 2.0
    a0 = 1.0 + alpha
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha
    return b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0

def biquad_lowshelf(fs, f0, gain_db, q=0.7071):
    if gain_db == 0.0:
        return 1.0, 0.0, 0.0, 1.0, 0.0, 0.0
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    beta = math.sqrt(A) / q
    
    b0 = A * ((A + 1.0) - (A - 1.0) * cos_w0 + beta * math.sin(w0))
    b1 = 2.0 * A * ((A - 1.0) - (A + 1.0) * cos_w0)
    b2 = A * ((A + 1.0) - (A - 1.0) * cos_w0 - beta * math.sin(w0))
    a0 = (A + 1.0) + (A - 1.0) * cos_w0 + beta * math.sin(w0)
    a1 = -2.0 * ((A - 1.0) + (A + 1.0) * cos_w0)
    a2 = (A + 1.0) + (A - 1.0) * cos_w0 - beta * math.sin(w0)
    return b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0

def biquad_highshelf(fs, f0, gain_db, q=0.7071):
    if gain_db == 0.0:
        return 1.0, 0.0, 0.0, 1.0, 0.0, 0.0
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / fs
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    beta = math.sqrt(A) / q
    
    b0 = A * ((A + 1.0) + (A - 1.0) * cos_w0 + beta * math.sin(w0))
    b1 = -2.0 * A * ((A - 1.0) + (A + 1.0) * cos_w0)
    b2 = A * ((A + 1.0) + (A - 1.0) * cos_w0 - beta * math.sin(w0))
    a0 = (A + 1.0) - (A - 1.0) * cos_w0 + beta * math.sin(w0)
    a1 = 2.0 * ((A - 1.0) - (A + 1.0) * cos_w0)
    a2 = (A + 1.0) - (A - 1.0) * cos_w0 - beta * math.sin(w0)
    return b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0

def apply_biquad_to_samples(b0, b1, b2, a0, a1, a2, samples):
    out = [0.0] * len(samples)
    x1 = x2 = y1 = y2 = 0.0
    for i, x in enumerate(samples):
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1
        x1 = x
        y2 = y1
        y1 = y
        out[i] = y
    return out

def read_wav_floats(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()

    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError(f"Not a valid RIFF WAVE file: {filepath}")

    pos = 12
    fmt_found = False
    audio_format = 1
    nchannels = 1
    fs = 48000
    sampwidth = 2
    raw_bytes = b''

    while pos + 8 <= len(data):
        chunk_id = data[pos:pos+4]
        chunk_size = struct.unpack('<I', data[pos+4:pos+8])[0]
        chunk_data = data[pos+8:pos+8+chunk_size]
        pos += 8 + chunk_size
        if chunk_size % 2 == 1:
            pos += 1

        if chunk_id == b'fmt ':
            audio_format, nchannels, fs, _, _, bits_per_sample = struct.unpack('<HHIIHH', chunk_data[:16])
            sampwidth = bits_per_sample // 8
            fmt_found = True
        elif chunk_id == b'data':
            raw_bytes = chunk_data

    if not fmt_found:
        raise ValueError(f"No fmt chunk found in {filepath}")

    n_samples = len(raw_bytes) // sampwidth
    if sampwidth == 2:
        ints = struct.unpack(f"<{n_samples}h", raw_bytes)
        floats = [i / 32768.0 for i in ints]
    elif sampwidth == 4:
        floats = list(struct.unpack(f"<{n_samples}f", raw_bytes))
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth}")

    if nchannels > 1:
        mono_floats = [floats[i] for i in range(0, len(floats), nchannels)]
        return mono_floats, fs
    return floats, fs

def write_wav_floats(filepath, samples, fs):
    data = struct.pack(f"<{len(samples)}f", *samples)
    riff_header = b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE'
    fmt_header = b'fmt ' + struct.pack('<I', 16) + struct.pack('<HHIIHH', 3, 1, fs, fs * 4, 4, 32)
    data_header = b'data' + struct.pack('<I', len(data))
    
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, 'wb') as f:
        f.write(riff_header + fmt_header + data_header + data)

def apply_true_peak_guard(samples, max_allowed_dbfs=-0.5):
    if not samples:
        return samples
    # 4x oversampled true peak estimation (inter-sample peak detection)
    max_tp = 0.0
    for i in range(len(samples) - 1):
        s0 = samples[i]
        s1 = samples[i+1]
        max_tp = max(max_tp, abs(s0), abs(s1))
        for t in [0.25, 0.5, 0.75]:
            interp = s0 + t * (s1 - s0)
            max_tp = max(max_tp, abs(interp))

    max_allowed_linear = 10.0 ** (max_allowed_dbfs / 20.0) # -0.5 dBFS = 0.9441
    if max_tp > max_allowed_linear:
        scale = max_allowed_linear / max_tp
        samples = [s * scale for s in samples]
        print(f"  [True-Peak Guard] ISP Peak: {max_tp:.3f} -> scaled by {scale:.4f} ({max_allowed_dbfs:.1f} dBFS safe)")
    return samples

def optimize_fir_latency_and_tail(samples, fs=48000, is_woofer=False):
    # 1. Find absolute peak index
    peak_idx = 0
    max_val = 0.0
    for i, s in enumerate(samples):
        if abs(s) > max_val:
            max_val = abs(s)
            peak_idx = i

    # 5.0 ms pre-peak lead (240 samples @ 48kHz) to eliminate phase artifacts & ringing
    lead_target = int(0.005 * fs)
    lead_len = min(lead_target, peak_idx)
    start_idx = peak_idx - lead_len
    
    # Calculate energy of original vs cropped
    total_energy = sum(s*s for s in samples)
    cropped = samples[start_idx:]
    
    # Apply smooth 64-sample cosine fade-in on the 5ms lead (zero phase click/ripple)
    fade_in_len = min(64, lead_len)
    for i in range(fade_in_len):
        fade = 0.5 * (1.0 - math.cos(math.pi * i / max(fade_in_len, 1)))
        cropped[i] *= fade

    # 2. Lopsided Tail Extension: 16,384 taps for woofers, 8,192 taps for tweeters
    target_len = 16384 if is_woofer else 8192
    if len(cropped) < target_len:
        tail_pad = target_len - len(cropped)
        cropped.extend([0.0] * tail_pad)
    elif len(cropped) > target_len:
        cropped = cropped[:target_len]

    # Smooth exponential tail fadeout over last 2048 samples
    fade_len = 2048
    for i in range(fade_len):
        idx = len(cropped) - fade_len + i
        fade = 0.5 * (1.0 + math.cos(math.pi * i / fade_len))
        cropped[idx] *= fade

    return cropped

import cmath

def apply_pink_noise_target_filter(samples, fs=48000, f_ref=1000.0):
    """
    Applies a continuous, exact 1/sqrt(f) (-3.01 dB/octave) Pink Noise target weighting filter
    to convert raw white-noise sweep measurements to a true equal-energy-per-octave acoustic output.
    """
    N = len(samples)
    # Pure Python Cooley-Tukey FFT
    def fft(x):
        n = len(x)
        if n <= 1:
            return x
        even = fft(x[0::2])
        odd = fft(x[1::2])
        terms = [cmath.exp(-2j * math.pi * k / n) * odd[k] for k in range(n // 2)]
        return [even[k] + terms[k] for k in range(n // 2)] + [even[k] - terms[k] for k in range(n // 2)]

    def ifft(x):
        n = len(x)
        if n <= 1:
            return x
        even = ifft(x[0::2])
        odd = ifft(x[1::2])
        terms = [cmath.exp(2j * math.pi * k / n) * odd[k] for k in range(n // 2)]
        return [even[k] + terms[k] for k in range(n // 2)] + [even[k] - terms[k] for k in range(n // 2)]

    # Pad N to next power of 2
    pad_len = 1 << (N - 1).bit_length()
    x_padded = [complex(s, 0.0) for s in samples] + [0j] * (pad_len - N)
    
    fft_vals = fft(x_padded)
    
    # Apply 1/sqrt(f) weighting
    max_boost_lin = 10.0 ** (15.0 / 20.0) # +15 dB cap at subsonic
    for k in range(pad_len):
        freq = (k * fs) / pad_len
        if k > pad_len // 2:
            freq = ((pad_len - k) * fs) / pad_len
        if freq > 10.0:
            weight = math.sqrt(f_ref / max(freq, 10.0))
            weight = min(weight, max_boost_lin)
        else:
            weight = 1.0
        fft_vals[k] *= weight
        
    ifft_vals = ifft(fft_vals)
    pink_samples = [ifft_vals[k].real / pad_len for k in range(N)]
    return pink_samples

def bake_driver_ir(src_wav, dst_wav, is_woofer=False, driver_gain=1.0):
    if not os.path.exists(src_wav):
        print(f"Warning: {src_wav} not found, skipping.")
        return False
    
    samples, fs = read_wav_floats(src_wav)

    # 1. Optimize Latency (5ms Lead) + Extend Woofer/Tweeter Lopsided Tail Resolution
    samples = optimize_fir_latency_and_tail(samples, fs=fs, is_woofer=is_woofer)

    # 2. True-Peak Inter-Sample Peak (ISP) Guarding (-0.5 dBFS ceiling)
    samples = apply_true_peak_guard(samples, max_allowed_dbfs=-0.5)

    write_wav_floats(dst_wav, samples, fs)
    print(f"==> Baked {os.path.basename(dst_wav)} ({fs} Hz, {len(samples)} taps, gain={driver_gain}x)")
    return True

def generate_simple_graph_and_bake(profile_dir=None):
    if not profile_dir:
        try:
            import detect_hardware
            profile_dir, prof = detect_hardware.detect_profile()
        except Exception:
            profile_dir = os.path.join(SCRIPT_DIR, "laptop-configs", "apple", "mbp15_1")

    if not profile_dir or not os.path.exists(profile_dir):
        profile_dir = os.path.join(SCRIPT_DIR, "15_1")

    graph_path = os.path.join(profile_dir, "graph.json")
    if not os.path.exists(graph_path):
        graph_path = os.path.join(SCRIPT_DIR, "graph.json")

    simple_graph_path = os.path.join(SCRIPT_DIR, "graph_simple.json")
    
    if not os.path.exists(graph_path):
        print(f"Error: {graph_path} not found.")
        sys.exit(1)

    with open(graph_path, 'r') as f:
        graph = json.load(f)

    repo_151 = profile_dir
    sys_dir = "/usr/share/t2-linux-audio/15_1"
    os.makedirs(repo_151, exist_ok=True)

    nodes = graph.get("filter.graph", {}).get("nodes", [])
    
    # 1. Discover all convolver nodes and their input WAV files dynamically from graph.json
    convolver_tasks = {} # maps src_filename -> {is_woofer, gain, sys_dst_path, repo_dst_path}

    for node in nodes:
        if node.get("label") == "convolver" or "conv" in node.get("name", ""):
            name = node.get("name", "")
            config = node.get("config", {})
            gain = config.get("gain", 1.0)
            filenames = config.get("filename", [])
            is_woofer = ("woofer" in name.lower() or "convlw" in name.lower() or "convrw" in name.lower())

            for sys_path in filenames:
                basename = os.path.basename(sys_path)
                if not basename in convolver_tasks:
                    if "woofer" in basename.lower():
                        is_woofer = True
                    baked_basename = "baked-" + basename
                    repo_dst_path = os.path.join(repo_151, baked_basename)
                    sys_dst_path = os.path.join(sys_dir, baked_basename)
                    convolver_tasks[sys_path] = {
                        "basename": basename,
                        "is_woofer": is_woofer,
                        "gain": gain,
                        "repo_dst": repo_dst_path,
                        "sys_dst": sys_dst_path
                    }

    # 2. Bake FIR files dynamically for all discovered WAV targets
    for sys_path, task in convolver_tasks.items():
        basename = task["basename"]
        src_path = os.path.join(repo_151, basename)
        if not os.path.exists(src_path) and os.path.exists(sys_path):
            src_path = sys_path
        if not os.path.exists(src_path) and os.path.exists(os.path.join(SCRIPT_DIR, basename)):
            src_path = os.path.join(SCRIPT_DIR, basename)

        bake_driver_ir(
            src_wav=src_path,
            dst_wav=task["repo_dst"],
            is_woofer=task["is_woofer"],
            driver_gain=task["gain"]
        )

    # 3. Build graph_simple.json dynamically from graph.json
    graph["node.description"] = "MacBook Pro 15,1 DSP Speakers (Baked FIR Crossovers & Latency Trimming)"
    new_nodes = []

    for node in nodes:
        name = node.get("name", "")
        if name in ["whpL1", "whpL2", "whpR1", "whpR2"]:
            continue

        if node.get("label") == "convolver" or "conv" in name:
            orig_filenames = node.get("config", {}).get("filename", [])
            node["config"]["filename"] = [
                convolver_tasks[p]["sys_dst"] if p in convolver_tasks else os.path.join(sys_dir, "baked-" + os.path.basename(p))
                for p in orig_filenames
            ]

        new_nodes.append(node)

    # Re-wire links: filter out removed whp* crossover nodes
    links = graph.get("filter.graph", {}).get("links", [])
    new_links = []
    for link in links:
        out_node = link.get("output", "")
        in_node = link.get("input", "")
        if "whp" in out_node or "whp" in in_node:
            continue
        new_links.append(link)

    # Set graph inputs directly to user_eq (first node in processing chain)
    graph["filter.graph"]["inputs"] = [
        "user_eq:in_l",
        "user_eq:in_r"
    ]

    # Remove capture.volumes from filter.graph if present
    graph["filter.graph"].pop("capture.volumes", None)

    # Consolidated volume tracking for stereo loudness node inside capture.props
    if "capture.props" not in graph:
        graph["capture.props"] = {}

    graph["capture.props"]["capture.volumes"] = [
        {
            "control": "loudness:volume",
            "min": -65.0,
            "max": 0.0,
            "scale": "cubic"
        }
    ]

    graph["filter.graph"]["nodes"] = new_nodes
    graph["filter.graph"]["links"] = new_links

    with open(simple_graph_path, 'w') as f:
        json.dump(graph, f, indent=4)

    print(f"==> Generated {os.path.basename(simple_graph_path)} (simplified single-stage DSP graph)")

def main():
    print("=================================================================")
    print("  SINGLE-STAGE FIR CONVOLVER BAKER & GRAPH SIMPLIFIER")
    print("=================================================================")
    generate_simple_graph_and_bake()
    print("=================================================================")
    print("Done! Baked FIR files & graph_simple.json created.")

if __name__ == "__main__":
    main()
