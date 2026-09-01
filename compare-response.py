#!/usr/bin/env python3
"""
compare-response.py — Frequency & Latency Response Comparison Matrix

Compares baseline FIR impulse responses (15_1/woofers-48k.wav & tweeters-48k.wav)
against baked composite FIR filters (15_1/baked-woofers-48k.wav & baked-tweeters-48k.wav).

Prints magnitude (dB) and latency (ms) across key acoustic frequencies.
Runs with pure standard-library Python 3.
"""

import os
import sys
import math
import struct
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def read_wav_floats(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()

    if not content.startswith(b'RIFF') or b'WAVE' not in content[:16]:
        raise ValueError(f"Invalid WAV file: {filepath}")

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
    samples = list(struct.unpack(f"<{nframes * nchannels}f", pcm_data))
    if nchannels > 1:
        samples = samples[::nchannels]
    return samples, framerate

def dft_magnitude_at_freq(samples, fs, freq_hz):
    w = 2.0 * math.pi * freq_hz / fs
    re = sum(s * math.cos(w * n) for n, s in enumerate(samples))
    im = sum(-s * math.sin(w * n) for n, s in enumerate(samples))
    mag = math.sqrt(re * re + im * im)
    db = 20.0 * math.log10(max(mag, 1e-6))
    return db

def find_peak_latency_ms(samples, fs):
    peak_idx = 0
    max_val = 0.0
    for i, s in enumerate(samples):
        if abs(s) > max_val:
            max_val = abs(s)
            peak_idx = i
    return (peak_idx / fs) * 1000.0, peak_idx

def compare_file_pair(name, orig_path, baked_path):
    print(f"\n=================================================================")
    print(f"  FREQUENCY & LATENCY COMPARISON: {name}")
    print(f"=================================================================")

    if not os.path.exists(orig_path) or not os.path.exists(baked_path):
        print(f"Error: Missing {orig_path} or {baked_path}")
        return

    orig_samples, fs = read_wav_floats(orig_path)
    baked_samples, _ = read_wav_floats(baked_path)

    orig_lat_ms, orig_peak = find_peak_latency_ms(orig_samples, fs)
    baked_lat_ms, baked_peak = find_peak_latency_ms(baked_samples, fs)

    print(f"Original IR Taps:  {len(orig_samples)} | Impulse Peak: sample #{orig_peak} ({orig_lat_ms:.2f} ms delay)")
    print(f"Baked IR Taps:     {len(baked_samples)} | Impulse Peak: sample #{baked_peak} ({baked_lat_ms:.2f} ms delay)")
    print(f"Latency Reduction: -{orig_lat_ms - baked_lat_ms:.2f} ms ({((orig_lat_ms - baked_lat_ms)/max(orig_lat_ms, 0.001))*100:.1f}% faster)")

    test_freqs = [40, 60, 100, 180, 500, 1000, 4000, 10000, 16000]
    print(f"\n  {'Frequency (Hz)':<16} | {'Original (dB)':<15} | {'Baked (dB)':<15} | {'Delta (dB)':<12}")
    print(f"  {'-'*16}-+-{'-'*15}-+-{'-'*15}-+-{'-'*12}")

    for f in test_freqs:
        orig_db = dft_magnitude_at_freq(orig_samples, fs, f)
        baked_db = dft_magnitude_at_freq(baked_samples, fs, f)
        delta_db = baked_db - orig_db
        sign = "+" if delta_db >= 0 else ""
        print(f"  {f:<16} | {orig_db:15.2f} | {baked_db:15.2f} | {sign}{delta_db:11.2f} dB")

def main():
    print("=================================================================")
    print("  mbp15-1-audio-dsp FIR RESPONSE COMPARISON ANALYZER")
    print("=================================================================")

    tweeter_orig = os.path.join(SCRIPT_DIR, "15_1", "tweeters-48k.wav")
    tweeter_baked = os.path.join(SCRIPT_DIR, "15_1", "baked-tweeters-48k.wav")
    compare_file_pair("TWEETERS (48 kHz)", tweeter_orig, tweeter_baked)

    woofer_orig = os.path.join(SCRIPT_DIR, "15_1", "woofers-48k.wav")
    woofer_baked = os.path.join(SCRIPT_DIR, "15_1", "baked-woofers-48k.wav")
    compare_file_pair("WOOFERS (48 kHz)", woofer_orig, woofer_baked)

if __name__ == "__main__":
    main()
