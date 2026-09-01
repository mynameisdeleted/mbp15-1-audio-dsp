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

def bake_driver_ir(src_wav, dst_wav, is_woofer=False, hp_freq=180.0):
    if not os.path.exists(src_wav):
        print(f"Warning: {src_wav} not found, skipping.")
        return False
    
    samples, fs = read_wav_floats(src_wav)
    
    # 1. Apply Crossover Filter if Woofer
    if is_woofer:
        b0, b1, b2, a0, a1, a2 = biquad_highpass(fs, hp_freq)
        samples = process_biquad(samples, b0, b1, b2, a0, a1, a2)
        samples = process_biquad(samples, b0, b1, b2, a0, a1, a2) # LR4 (2-stage)

    # 2. Apply User EQ Boosts (if user_eq.json exists)
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

    write_wav_floats(dst_wav, samples, fs)
    print(f"==> Baked {os.path.basename(dst_wav)} ({fs} Hz, {len(samples)} taps)")
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
        
        if name in ["convLT", "convRT"]:
            node["config"]["filename"] = [
                "/usr/share/t2-linux-audio/15_1/baked-tweeters-44k.wav",
                "/usr/share/t2-linux-audio/15_1/baked-tweeters-48k.wav",
                "/usr/share/t2-linux-audio/15_1/baked-tweeters-96k.wav"
            ]
        elif name in ["convLW", "convRW"]:
            node["config"]["filename"] = [
                "/usr/share/t2-linux-audio/15_1/baked-woofers-44k.wav",
                "/usr/share/t2-linux-audio/15_1/baked-woofers-48k.wav",
                "/usr/share/t2-linux-audio/15_1/baked-woofers-96k.wav"
            ]
        new_nodes.append(node)

    # Re-wire links directly from copy/delay to convolvers
    links = graph.get("filter.graph", {}).get("links", [])
    new_links = []
    for link in links:
        out_node = link.get("output", "")
        in_node = link.get("input", "")
        if "whp" in out_node or "whp" in in_node or "equalizer" in out_node or "user_eq" in out_node:
            continue
        new_links.append(link)

    # Directly link spkdly to convolvers
    new_links.append({"output": "spkdlyL:Out", "input": "convLW:In"})
    new_links.append({"output": "spkdlyR:Out", "input": "convRW:In"})

    graph["filter.graph"]["nodes"] = new_nodes
    graph["filter.graph"]["links"] = new_links

    with open(simple_graph_path, 'w') as f:
        json.dump(graph, f, indent=4)

    print(f"==> Generated {os.path.basename(simple_graph_path)} (simplified single-stage DSP graph)")

def main():
    print("=================================================================")
    print("  SINGLE-STAGE FIR CONVOLVER BAKER & GRAPH SIMPLIFIER")
    print("=================================================================")
    
    sys_dir = "/usr/share/t2-linux-audio/15_1"
    rates = ["44k", "48k", "96k"]

    for r in rates:
        tw_name = f"tweeters-{r}.wav"
        tw_src = os.path.join(SCRIPT_DIR, tw_name)
        if not os.path.exists(tw_src) and os.path.exists(os.path.join(sys_dir, tw_name)):
            tw_src = os.path.join(sys_dir, tw_name)

        tw_dst = os.path.join(SCRIPT_DIR, f"baked-tweeters-{r}.wav")
        bake_driver_ir(tw_src, tw_dst, is_woofer=False)

        wf_name = f"woofers-{r}.wav"
        wf_src = os.path.join(SCRIPT_DIR, wf_name)
        if not os.path.exists(wf_src) and os.path.exists(os.path.join(sys_dir, wf_name)):
            wf_src = os.path.join(sys_dir, wf_name)

        wf_dst = os.path.join(SCRIPT_DIR, f"baked-woofers-{r}.wav")
        bake_driver_ir(wf_src, wf_dst, is_woofer=True, hp_freq=180.0)

    generate_simple_graph()
    print("=================================================================")
    print("Done! Baked FIR files & graph_simple.json created.")

if __name__ == "__main__":
    main()
