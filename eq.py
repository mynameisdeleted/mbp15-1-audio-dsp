#!/usr/bin/env python3
"""
eq.py — Terminal EQ Preset & Tuning Utility for mbp15-1-audio-dsp

Allows quick EQ tuning, gain adjustment, preset selection, and status inspection.
Automatically applies changes to user_eq.json and hot-reloads into PipeWire via ./apply.sh --bake.
"""

import sys
import os
import json
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
USER_EQ_PATH = os.path.join(SCRIPT_DIR, "user_eq.json")

PRESETS = {
    "flat": {
        "g_out": 1.5,
        "f_0": 70.0, "g_0": 1.0, "q_0": 0.7071, "ft_0": 5,
        "f_1": 110.0, "g_1": 1.0, "q_1": 1.0, "ft_1": 1,
        "f_2": 315.0, "g_2": 1.0, "q_2": 1.0, "ft_2": 1,
        "f_3": 1000.0, "g_3": 1.0, "q_3": 1.0, "ft_3": 1,
        "f_4": 2500.0, "g_4": 1.0, "q_4": 1.0, "ft_4": 1,
        "f_5": 6000.0, "g_5": 1.0, "q_5": 1.0, "ft_5": 1,
        "f_6": 10000.0, "g_6": 1.0, "q_6": 0.7071, "ft_6": 3,
        "f_7": 16000.0, "g_7": 1.0, "q_7": 0.7071, "ft_7": 3,
        "enabled": 1
    },
    "bass-boost": {
        "g_out": 1.8,
        "f_0": 70.0, "g_0": 1.35, "q_0": 0.7071, "ft_0": 5,  # +2.6 dB Low Shelf
        "f_1": 110.0, "g_1": 1.2, "q_1": 1.0, "ft_1": 1,    # +1.6 dB @ 110Hz
        "f_2": 315.0, "g_2": 1.0, "q_2": 1.0, "ft_2": 1,
        "f_3": 1000.0, "g_3": 1.0, "q_3": 1.0, "ft_3": 1,
        "f_4": 2500.0, "g_4": 1.0, "q_4": 1.0, "ft_4": 1,
        "f_5": 6000.0, "g_5": 1.0, "q_5": 1.0, "ft_5": 1,
        "f_6": 10000.0, "g_6": 1.0, "q_6": 0.7071, "ft_6": 3,
        "f_7": 16000.0, "g_7": 1.0, "q_7": 0.7071, "ft_7": 3,
        "enabled": 1
    },
    "vocal": {
        "g_out": 1.6,
        "f_0": 70.0, "g_0": 0.9, "q_0": 0.7071, "ft_0": 5,   # Slightly reduced sub bass
        "f_1": 110.0, "g_1": 1.0, "q_1": 1.0, "ft_1": 1,
        "f_2": 315.0, "g_2": 1.0, "q_2": 1.0, "ft_2": 1,
        "f_3": 1000.0, "g_3": 1.25, "q_3": 1.0, "ft_3": 1,  # +1.9 dB @ 1kHz Vocal clarity
        "f_4": 2500.0, "g_4": 1.2, "q_4": 1.0, "ft_4": 1,   # +1.6 dB Presence
        "f_5": 6000.0, "g_5": 1.1, "q_5": 1.0, "ft_5": 1,
        "f_6": 10000.0, "g_6": 1.0, "q_6": 0.7071, "ft_6": 3,
        "f_7": 16000.0, "g_7": 1.0, "q_7": 0.7071, "ft_7": 3,
        "enabled": 1
    },
    "warm": {
        "g_out": 1.7,
        "f_0": 70.0, "g_0": 1.25, "q_0": 0.7071, "ft_0": 5,  # +1.9 dB Low Shelf
        "f_1": 110.0, "g_1": 1.15, "q_1": 1.0, "ft_1": 1,
        "f_2": 315.0, "g_2": 1.05, "q_2": 1.0, "ft_2": 1,
        "f_3": 1000.0, "g_3": 1.0, "q_3": 1.0, "ft_3": 1,
        "f_4": 2500.0, "g_4": 1.0, "q_4": 1.0, "ft_4": 1,
        "f_5": 6000.0, "g_5": 0.9, "q_5": 1.0, "ft_5": 1,   # Softened high end
        "f_6": 10000.0, "g_6": 0.85, "q_6": 0.7071, "ft_6": 3,
        "f_7": 16000.0, "g_7": 0.8, "q_7": 0.7071, "ft_7": 3,
        "enabled": 1
    },
    "treble-boost": {
        "g_out": 1.6,
        "f_0": 70.0, "g_0": 1.0, "q_0": 0.7071, "ft_0": 5,
        "f_1": 110.0, "g_1": 1.0, "q_1": 1.0, "ft_1": 1,
        "f_2": 315.0, "g_2": 1.0, "q_2": 1.0, "ft_2": 1,
        "f_3": 1000.0, "g_3": 1.0, "q_3": 1.0, "ft_3": 1,
        "f_4": 2500.0, "g_4": 1.15, "q_4": 1.0, "ft_4": 1,
        "f_5": 6000.0, "g_5": 1.25, "q_5": 1.0, "ft_5": 1,
        "f_6": 10000.0, "g_6": 1.3, "q_6": 0.7071, "ft_6": 3, # High Shelf Boost
        "f_7": 16000.0, "g_7": 1.3, "q_7": 0.7071, "ft_7": 3,
        "enabled": 1
    }
}

def load_user_eq():
    if os.path.exists(USER_EQ_PATH):
        try:
            with open(USER_EQ_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return dict(PRESETS["flat"])

def format_user_eq_json(eq_data):
    enabled = eq_data.get("enabled", 1)
    mode = eq_data.get("mode", 0)
    g_in = eq_data.get("g_in", 1.0)
    g_out = eq_data.get("g_out", 1.0)

    lines = [
        "{",
        f'    "enabled": {enabled}, "mode": {mode}, "g_in": {g_in:.1f}, "g_out": {g_out:.2f},'
    ]

    for i in range(8):
        ft = eq_data.get(f"ft_{i}", 1)
        freq = eq_data.get(f"f_{i}", 1000.0)
        gain = eq_data.get(f"g_{i}", 1.0)
        q = eq_data.get(f"q_{i}", 1.0)
        
        freq_str = f"{freq:.1f}"
        band_line = f'    "ft_{i}": {ft}, "f_{i}": {freq_str:<7}, "g_{i}": {gain:<4.2f}, "q_{i}": {q:.1f}'
        if i == 0 or i == 7:
            s_val = eq_data.get(f"s_{i}", 0)
            band_line += f', "s_{i}": {s_val}'
        if i < 7:
            band_line += ","
        lines.append(band_line)

    lines.append("}")
    return "\n".join(lines) + "\n"

def save_and_apply(eq_data):
    formatted = format_user_eq_json(eq_data)
    with open(USER_EQ_PATH, 'w') as f:
        f.write(formatted)
    print(f"Saved {USER_EQ_PATH}")
    print("Baking FIR filters & applying to PipeWire...")
    subprocess.run([os.path.join(SCRIPT_DIR, "apply.sh"), "--bake"])

def show_status(eq_data):
    print("=================================================================")
    print("  MACBOOK PRO 15,1 DSP USER EQ STATUS")
    print("=================================================================")
    g_out = eq_data.get("g_out", 1.0)
    enabled = "ENABLED" if eq_data.get("enabled", 1) == 1 else "DISABLED"
    print(f"Master Output Gain: {g_out:.2f}x ({20.0*math.log10(max(g_out, 0.001)):+.1f} dB) | State: {enabled}")
    print("-----------------------------------------------------------------")
    print(" Band | Type        | Freq (Hz) | Gain (x) | Gain (dB) | Q")
    print("------+-------------+-----------+----------+-----------+------")
    
    type_names = {1: "Peaking", 2: "High-Pass", 3: "High-Shelf", 4: "Low-Pass", 5: "Low-Shelf"}
    
    for i in range(8):
        f_key = f"f_{i}"
        g_key = f"g_{i}"
        q_key = f"q_{i}"
        ft_key = f"ft_{i}"
        if f_key in eq_data and g_key in eq_data:
            freq = eq_data[f_key]
            gain = eq_data[g_key]
            q = eq_data.get(q_key, 1.0)
            ft = eq_data.get(ft_key, 1)
            gain_db = 20.0 * math.log10(max(gain, 0.001))
            typeName = type_names.get(ft, "Peaking")
            print(f"  {i:<3} | {typeName:<11} | {freq:<9.1f} | {gain:<8.2f} | {gain_db:<+9.1f} | {q:.2f}")
    print("=================================================================")

import math

def print_help():
    print("""
Usage: ./eq.py [command] [args]

Commands:
  status / show         Display current EQ settings and gains
  preset <name>         Apply preset: flat, bass-boost, vocal, warm, treble-boost
  bass <+dB / -dB>      Adjust bass shelf gain (e.g., ./eq.py bass +2.0)
  treble <+dB / -dB>    Adjust treble shelf gain (e.g., ./eq.py treble +1.5)
  gain <multiplier>     Set master output gain multiplier (e.g., ./eq.py gain 2.0)
  enable / disable      Enable or disable user EQ

Examples:
  ./eq.py preset bass-boost
  ./eq.py bass +3
  ./eq.py status
""")

def main():
    args = sys.argv[1:]
    if not args or args[0] in ["-h", "--help", "help"]:
        print_help()
        sys.exit(0)

    cmd = args[0].lower()
    eq = load_user_eq()

    if cmd in ["status", "show"]:
        show_status(eq)
    elif cmd == "preset":
        if len(args) < 2:
            print(f"Available presets: {', '.join(PRESETS.keys())}")
            sys.exit(1)
        name = args[1].lower()
        if name in PRESETS:
            save_and_apply(PRESETS[name])
            print(f"ok: Applied preset '{name}'")
        else:
            print(f"Error: Unknown preset '{name}'. Choose from: {', '.join(PRESETS.keys())}")
            sys.exit(1)
    elif cmd == "bass":
        if len(args) < 2:
            print("Usage: ./eq.py bass <+dB or -dB>  (e.g., ./eq.py bass +2)")
            sys.exit(1)
        val_db = float(args[1].replace("+", ""))
        gain_mult = 10.0 ** (val_db / 20.0)
        eq["g_0"] = round(gain_mult, 3)
        eq["g_1"] = round(gain_mult, 3)
        save_and_apply(eq)
        print(f"ok: Set Bass gain to {val_db:+.1f} dB ({gain_mult:.3f}x)")
    elif cmd == "treble":
        if len(args) < 2:
            print("Usage: ./eq.py treble <+dB or -dB>  (e.g., ./eq.py treble +1.5)")
            sys.exit(1)
        val_db = float(args[1].replace("+", ""))
        gain_mult = 10.0 ** (val_db / 20.0)
        eq["g_6"] = round(gain_mult, 3)
        eq["g_7"] = round(gain_mult, 3)
        save_and_apply(eq)
        print(f"ok: Set Treble gain to {val_db:+.1f} dB ({gain_mult:.3f}x)")
    elif cmd == "gain":
        if len(args) < 2:
            print("Usage: ./eq.py gain <+dB / -dB or multiplier>  (e.g., ./eq.py gain -20 or ./eq.py gain 1.5)")
            sys.exit(1)
        raw_val = args[1].lower().replace("x", "").replace("db", "")
        val = float(raw_val)
        if val <= 0 and not raw_val.startswith("+"):
            # Negative number passed (e.g. -20 or -100) -> Treat as dB attenuation
            gain_mult = 10.0 ** (val / 20.0)
            eq["g_out"] = round(gain_mult, 5)
            save_and_apply(eq)
            print(f"ok: Set Master Output Gain to {val:+.1f} dB ({gain_mult:.5f}x multiplier)")
        else:
            # Positive linear multiplier or positive dB
            if "+" in raw_val:
                gain_mult = 10.0 ** (val / 20.0)
                eq["g_out"] = round(gain_mult, 3)
                print(f"ok: Set Master Output Gain to {val:+.1f} dB ({gain_mult:.3f}x multiplier)")
            else:
                eq["g_out"] = round(val, 3)
                print(f"ok: Set Master Output Gain to {eq['g_out']:.2f}x multiplier")
            save_and_apply(eq)
    elif cmd in ["enable", "disable"]:
        eq["enabled"] = 1 if cmd == "enable" else 0
        save_and_apply(eq)
        print(f"ok: User EQ {cmd}d")
    else:
        print(f"Error: Unknown command '{cmd}'")
        print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
