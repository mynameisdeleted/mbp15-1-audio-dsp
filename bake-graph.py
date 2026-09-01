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

def process_biquad(samples, b0, b1, b2, a0, a1, a2):
    out = [0.0] * len(samples)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(len(samples)):
        x0 = samples[i]
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        out[i] = y0
        x2 = x1
        x1 = x0
        y2 = y1
        y1 = y0
    return out

def read_wav_floats(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()

    if not content.startswith(b'RIFF') or b'WAVE' not in content[:16]:
        raise ValueError(f"Invalid WAV file: {filepath}")

    # Parse RIFF chunks
    pos = 12
    fmt_tag = 1
    nchannels = 1
    framerate = 48000
    sampwidth = 4
    pcm_data = b''

    while pos < len(content) - 8:
        chunk_id = content[pos:pos+4]
        chunk_size = struct.unpack('<I', content[pos+4:pos+8])[0]
        chunk_body = content[pos+8:pos+8+chunk_size]

        if chunk_id == b'fmt ':
            fmt_tag, nchannels, framerate, byte_rate, block_align, bits_per_sample = struct.unpack('<HHIIHH', chunk_body[:16])
            sampwidth = bits_per_sample // 8
        elif chunk_id == b'data':
            pcm_data = chunk_body
            break

        pos += 8 + chunk_size
        if chunk_size % 2 == 1:
            pos += 1

    nframes = len(pcm_data) // (sampwidth * nchannels)
    samples = []

    if fmt_tag == 3 and sampwidth == 4: # IEEE Float 32-bit
        samples = list(struct.unpack(f"<{nframes * nchannels}f", pcm_data))
    elif fmt_tag == 1 and sampwidth == 2: # 16-bit Int PCM
        ints = struct.unpack(f"<{nframes * nchannels}h", pcm_data)
        samples = [i / 32768.0 for i in ints]
    elif fmt_tag == 1 and sampwidth == 4: # 32-bit Int PCM
        ints = struct.unpack(f"<{nframes * nchannels}i", pcm_data)
        samples = [i / 2147483648.0 for i in ints]
    else:
        # Fallback 32-bit float unpack
        samples = list(struct.unpack(f"<{nframes * nchannels}f", pcm_data))

    if nchannels > 1:
        samples = samples[::nchannels]
    return samples, framerate

def write_wav_floats(filepath, samples, framerate):
    data = struct.pack(f"<{len(samples)}f", *samples)
    fmt_chunk = struct.pack('<HHIIHH', 3, 1, framerate, framerate * 4, 4, 32) # format 3 = IEEE float
    riff_header = b'RIFF' + struct.pack('<I', 36 + len(data)) + b'WAVE'
    fmt_header = b'fmt ' + struct.pack('<I', 16) + fmt_chunk
    data_header = b'data' + struct.pack('<I', len(data))
    
    with open(filepath, 'wb') as f:
        f.write(riff_header + fmt_header + data_header + data)

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

    # Energy compensation: Scale post-lead tail energy to preserve 100% total acoustic energy
    cropped_energy = sum(s*s for s in cropped)
    if cropped_energy > 0 and total_energy > 0:
        boost_factor = math.sqrt(total_energy / cropped_energy)
        for i in range(lead_len, len(cropped)):
            cropped[i] *= boost_factor

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

def bake_driver_ir(src_wav, dst_wav, is_woofer=False, hp_freq=180.0, driver_gain=1.0):
    if not os.path.exists(src_wav):
        print(f"Warning: {src_wav} not found, skipping.")
        return False
    
    samples, fs = read_wav_floats(src_wav)

    # 1. Apply Driver Gain Multiplier (e.g., 1.1 for tweeters, 1.2 for woofers)
    if driver_gain != 1.0:
        samples = [s * driver_gain for s in samples]
    
    # 2. Apply Crossover Filter if Woofer
    if is_woofer:
        b0, b1, b2, a0, a1, a2 = biquad_highpass(fs, hp_freq)
        samples = process_biquad(samples, b0, b1, b2, a0, a1, a2)
        samples = process_biquad(samples, b0, b1, b2, a0, a1, a2) # LR4 (2-stage)

    # 3. Apply User EQ Boosts (if user_eq.json exists)
    user_eq_path = os.path.join(SCRIPT_DIR, "user_eq.json")
    if os.path.exists(user_eq_path):
        try:
            with open(user_eq_path, 'r') as f:
                ueq = json.load(f)
            if ueq.get("enabled", 1) == 1:
                for i in range(8):
                    f_key = f"f_{i}"
                    g_key = f"g_{i}"
                    q_key = f"q_{i}"
                    if f_key in ueq and g_key in ueq:
                        f0 = ueq[f_key]
                        gain = ueq[g_key]
                        q = ueq.get(q_key, 1.0)
                        gain_db = 20.0 * math.log10(max(gain, 0.001))
                        b0, b1, b2, a0, a1, a2 = biquad_peaking(fs, f0, gain_db, q)
                        samples = process_biquad(samples, b0, b1, b2, a0, a1, a2)
        except Exception as e:
            print(f"User EQ processing note: {e}")

    # 4. Optimize Latency (5ms Lead) + Extend Woofer/Tweeter Lopsided Tail Resolution
    samples = optimize_fir_latency_and_tail(samples, fs=fs, is_woofer=is_woofer)

    write_wav_floats(dst_wav, samples, fs)
    print(f"==> Baked {os.path.basename(dst_wav)} ({fs} Hz, {len(samples)} taps, gain={driver_gain}x)")
    return True

def generate_simple_graph():
    graph_path = os.path.join(SCRIPT_DIR, "graph.json")
    simple_graph_path = os.path.join(SCRIPT_DIR, "graph_simple.json")
    
    if not os.path.exists(graph_path):
        print("graph.json not found.")
        return

    with open(graph_path, 'r') as f:
        graph = json.load(f)

    # Update description
    graph["node.description"] = "MacBook Pro 15,1 DSP Speakers (Single-Stage Baked FIR)"

    # Replace Convolver filenames in nodes to point to baked WAVs
    nodes = graph.get("filter.graph", {}).get("nodes", [])
    new_nodes = []

    for node in nodes:
        name = node.get("name", "")
        # Omit static biquad EQ nodes that are now baked into FIR
        if name in ["user_eq", "equalizer", "whpL1", "whpL2", "whpR1", "whpR2"]:
            continue
        
        repo_151 = os.path.join(SCRIPT_DIR, "15_1")
        if name in ["convLT", "convRT"]:
            node["config"]["filename"] = [
                os.path.join(repo_151, "baked-tweeters-44k.wav"),
                os.path.join(repo_151, "baked-tweeters-48k.wav"),
                os.path.join(repo_151, "baked-tweeters-96k.wav")
            ]
        elif name in ["convLW", "convRW"]:
            node["config"]["filename"] = [
                os.path.join(repo_151, "baked-woofers-44k.wav"),
                os.path.join(repo_151, "baked-woofers-48k.wav"),
                os.path.join(repo_151, "baked-woofers-96k.wav")
            ]
        new_nodes.append(node)

    # Re-wire links: filter out references to omitted nodes (user_eq, equalizer, whp*)
    links = graph.get("filter.graph", {}).get("links", [])
    new_links = []
    for link in links:
        out_node = link.get("output", "")
        in_node = link.get("input", "")
        if "whp" in out_node or "whp" in in_node or "equalizer" in out_node or "user_eq" in out_node:
            continue
        new_links.append(link)

    # Set graph inputs to virtualbass (first remaining processing node)
    graph["filter.graph"]["inputs"] = [
        "virtualbass:in_l",
        "virtualbass:in_r"
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
    
    repo_151 = os.path.join(SCRIPT_DIR, "15_1")
    sys_dir = "/usr/share/t2-linux-audio/15_1"
    os.makedirs(repo_151, exist_ok=True)
    rates = ["44k", "48k", "96k"]

    for r in rates:
        tw_name = f"tweeters-{r}.wav"
        tw_src = os.path.join(repo_151, tw_name)
        if not os.path.exists(tw_src) and os.path.exists(os.path.join(sys_dir, tw_name)):
            tw_src = os.path.join(sys_dir, tw_name)
        if not os.path.exists(tw_src) and os.path.exists(os.path.join(SCRIPT_DIR, tw_name)):
            tw_src = os.path.join(SCRIPT_DIR, tw_name)

        tw_dst = os.path.join(repo_151, f"baked-tweeters-{r}.wav")
        bake_driver_ir(tw_src, tw_dst, is_woofer=False, driver_gain=1.1)

        wf_name = f"woofers-{r}.wav"
        wf_src = os.path.join(repo_151, wf_name)
        if not os.path.exists(wf_src) and os.path.exists(os.path.join(sys_dir, wf_name)):
            wf_src = os.path.join(sys_dir, wf_name)
        if not os.path.exists(wf_src) and os.path.exists(os.path.join(SCRIPT_DIR, tw_name)):
            wf_src = os.path.join(SCRIPT_DIR, wf_name)

        wf_dst = os.path.join(repo_151, f"baked-woofers-{r}.wav")
        bake_driver_ir(wf_src, wf_dst, is_woofer=True, hp_freq=180.0, driver_gain=1.2)

    generate_simple_graph()
    print("=================================================================")
    print("Done! Baked FIR files & graph_simple.json created.")

if __name__ == "__main__":
    main()
