#!/usr/bin/env python3
import os
import sys
import json
import glob

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIGS_DIR = os.path.join(SCRIPT_DIR, "laptop-configs")

def print_help():
    print("""=================================================================
  LAPTOP AUDIO DSP HARDWARE DETECTION TOOL
=================================================================
Usage:
  ./detect_hardware.py [options]

Options:
  -h, --help              Show this help message
  -l, --list-configs      List all available laptop hardware profiles
  -m, --model <name>      Manually specify model/profile ID (e.g., apple_mbp15_1)
  --manual <name>         Same as --model
  -p, --profile <path>    Path to custom profile directory
  --json                  Output detection details in JSON format
  --quiet                 Suppress warning messages on fallback

Examples:
  ./detect_hardware.py
  ./detect_hardware.py --list-configs
  ./detect_hardware.py --model apple_mbp15_1
  ./detect_hardware.py --json
=================================================================
""")

def read_dmi_file(filename):
    path = os.path.join("/sys/class/dmi/id", filename)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except Exception:
            pass
    return ""

def list_all_profiles():
    profile_files = glob.glob(os.path.join(CONFIGS_DIR, "**", "profile.json"), recursive=True)
    profiles = []
    for prof_path in sorted(profile_files):
        try:
            with open(prof_path, 'r') as f:
                prof = json.load(f)
                prof["_path"] = os.path.dirname(prof_path)
                profiles.append(prof)
        except Exception:
            continue
    return profiles

def print_available_configs():
    profiles = list_all_profiles()
    print("=================================================================")
    print("  AVAILABLE LAPTOP AUDIO DSP CONFIGURATIONS")
    print("=================================================================")
    print(f" {'ID':<18} | {'Name':<32} | {'Vendor':<12}")
    print("-------------------+----------------------------------+----------")
    for prof in profiles:
        pid = prof.get("id", os.path.basename(prof["_path"]))
        name = prof.get("name", "Unknown Laptop")
        vendor = prof.get("vendor", "Unknown")
        print(f" {pid:<18} | {name:<32} | {vendor:<12}")
    print("=================================================================")

def detect_profile(manual_target=None):
    profile_files = glob.glob(os.path.join(CONFIGS_DIR, "**", "profile.json"), recursive=True)
    
    # 1. Manual override check (--model, --manual, --profile)
    if manual_target:
        for prof_path in profile_files:
            try:
                with open(prof_path, 'r') as f:
                    prof = json.load(f)
                pid = prof.get("id", os.path.basename(os.path.dirname(prof_path)))
                pdir = os.path.dirname(prof_path)
                if manual_target.lower() in [pid.lower(), pdir.lower(), os.path.basename(pdir).lower()]:
                    return pdir, prof, False
            except Exception:
                continue

    # 2. DMI Hardware Matching
    vendor = read_dmi_file("sys_vendor")
    product = read_dmi_file("product_name")

    if vendor or product:
        for prof_path in profile_files:
            try:
                with open(prof_path, 'r') as f:
                    prof = json.load(f)
                
                dmi_matches = prof.get("dmi_matches", [])
                prof_vendor = prof.get("vendor", "")

                if (not prof_vendor or prof_vendor.lower() in vendor.lower() or vendor.lower() in prof_vendor.lower()):
                    for match in dmi_matches:
                        if match.lower() in product.lower():
                            return os.path.dirname(prof_path), prof, False
            except Exception:
                continue

    # 3. Fallback to default MacBookPro15,1 profile with warning
    fallback_path = os.path.join(CONFIGS_DIR, "apple", "mbp15_1")
    fallback_json = os.path.join(fallback_path, "profile.json")
    if os.path.exists(fallback_json):
        with open(fallback_json, 'r') as f:
            return fallback_path, json.load(f), True
            
    return None, None, True

def main():
    args = sys.argv[1:]

    if any(arg in args for arg in ["-h", "--help", "help"]):
        print_help()
        sys.exit(0)
    
    if any(arg in args for arg in ["--list", "--list-configs", "-l", "list"]):
        print_available_configs()
        sys.exit(0)

    manual_target = None
    for i, arg in enumerate(args):
        if arg in ["--profile", "-p", "--model", "-m", "--manual"] and i + 1 < len(args):
            manual_target = args[i+1]

    path, prof, is_fallback = detect_profile(manual_target=manual_target)
    
    if is_fallback and "--quiet" not in args:
        vendor = read_dmi_file("sys_vendor") or "Unknown Vendor"
        product = read_dmi_file("product_name") or "Unknown Model"
        print(f"Warning: Hardware '{vendor} / {product}' not found in laptop-configs/.", file=sys.stderr)
        print("Falling back to default 'apple_mbp15_1' profile.", file=sys.stderr)
        print("Use './detect_hardware.py --list-configs' to view all available profiles.", file=sys.stderr)

    if "--json" in args:
        print(json.dumps({"path": path, "profile": prof, "is_fallback": is_fallback}, indent=2))
    else:
        if path:
            print(path)
        else:
            sys.exit(1)

if __name__ == "__main__":
    main()
