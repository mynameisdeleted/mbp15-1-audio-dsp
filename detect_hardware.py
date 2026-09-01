#!/usr/bin/env python3
import os
import sys
import json
import glob

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
CONFIGS_DIR = os.path.join(SCRIPT_DIR, "laptop-configs")

def read_dmi_file(filename):
    path = os.path.join("/sys/class/dmi/id", filename)
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except Exception:
            pass
    return ""

def detect_profile():
    vendor = read_dmi_file("sys_vendor")
    product = read_dmi_file("product_name")

    profile_files = glob.glob(os.path.join(CONFIGS_DIR, "**", "profile.json"), recursive=True)
    
    for prof_path in profile_files:
        try:
            with open(prof_path, 'r') as f:
                prof = json.load(f)
            
            dmi_matches = prof.get("dmi_matches", [])
            prof_vendor = prof.get("vendor", "")

            # Match vendor and product
            if (not prof_vendor or prof_vendor.lower() in vendor.lower() or vendor.lower() in prof_vendor.lower()):
                for match in dmi_matches:
                    if match.lower() in product.lower():
                        return os.path.dirname(prof_path), prof
        except Exception as e:
            continue

    # Fallback to default MacBookPro15,1 profile
    fallback_path = os.path.join(CONFIGS_DIR, "apple", "mbp15_1")
    fallback_json = os.path.join(fallback_path, "profile.json")
    if os.path.exists(fallback_json):
        with open(fallback_json, 'r') as f:
            return fallback_path, json.load(f)
            
    return None, None

def main():
    path, prof = detect_profile()
    if "--json" in sys.argv:
        print(json.dumps({"path": path, "profile": prof}, indent=2))
    else:
        if path:
            print(path)
        else:
            sys.exit(1)

if __name__ == "__main__":
    main()
