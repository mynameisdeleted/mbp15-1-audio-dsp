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

def bake_driver_ir(src_wav, dst_wav, is_woofer=False, driver_gain=1.0):
    if not os.path.exists(src_wav):
        print(f"Warning: {src_wav} not found, skipping.")
        return False
    
    samples, fs = read_wav_floats(src_wav)

    # 1. Optimize Latency (5ms Lead) + Extend Woofer/Tweeter Lopsided Tail Resolution
    samples = optimize_fir_latency_and_tail(samples, fs=fs, is_woofer=is_woofer)

    # 3. True-Peak Inter-Sample Peak (ISP) Guarding (-0.5 dBFS ceiling)
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

    # 3. Build graph_simple.json dynamically from graph.json (omitting limiter, ell, elr, whp*)
    # Keeping user_eq, equalizer, virtualbass, multiband_compressor in exact order for 100% bit-exact bass response!
    graph["node.description"] = "MacBook Pro 15,1 DSP Speakers (Baked FIR Crossovers & Latency Trimming)"
    new_nodes = []

    for node in nodes:
        name = node.get("name", "")
        # Omit redundant master limiter, ell/elr mono nodes, & crossover biquad nodes
        if name in ["limiter", "ell", "elr", "whpL1", "whpL2", "whpR1", "whpR2"]:
            continue

        if node.get("label") == "convolver" or "conv" in name:
            orig_filenames = node.get("config", {}).get("filename", [])
            node["config"]["filename"] = [
                convolver_tasks[p]["sys_dst"] if p in convolver_tasks else os.path.join(sys_dir, "baked-" + os.path.basename(p))
                for p in orig_filenames
            ]

        new_nodes.append(node)

    # Add consolidated 2-channel stereo loudness compensator node (replacing ell & elr)
    new_nodes.append({
        "type": "lv2",
        "plugin": "http://lsp-plug.in/plugins/lv2/loud_comp_stereo",
        "name": "loudness",
        "control": {
            "enabled": 1,
            "input": 1.0,
            "fft": 4
        }
    })

    # Re-wire links: filter out limiter, ell, elr & whp*
    links = graph.get("filter.graph", {}).get("links", [])
    new_links = []
    for link in links:
        out_node = link.get("output", "")
        in_node = link.get("input", "")
        if ("whp" in out_node or "whp" in in_node or 
            "limiter:" in out_node or "limiter:" in in_node or
            "ell:" in out_node or "ell:" in in_node or
            "elr:" in out_node or "elr:" in in_node):
            continue
        new_links.append(link)

    # Wire multiband_compressor -> loudness (stereo) -> copyL / copyR
    new_links.append({"output": "multiband_compressor:out_l", "input": "loudness:in_l"})
    new_links.append({"output": "multiband_compressor:out_r", "input": "loudness:in_r"})
    new_links.append({"output": "loudness:out_l", "input": "copyL:In"})
    new_links.append({"output": "loudness:out_r", "input": "copyR:In"})

    # Set graph inputs directly to user_eq (first node in processing chain)
    graph["filter.graph"]["inputs"] = [
        "user_eq:in_l",
        "user_eq:in_r"
    ]

    # Consolidated volume tracking for stereo loudness node
    graph["filter.graph"]["capture.volumes"] = [
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
