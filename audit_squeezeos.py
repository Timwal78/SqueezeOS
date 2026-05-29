import os
import re
from pathlib import Path

BASE_DIR = os.getcwd()
IGNORE_DIRS = {".git", ".gitnexus", "__pycache__", "node_modules", ".claude"}

def run_audit():
    results = {
        "under_5kb": [],
        "duplicate_sizes": {},
        "hardcoded_secrets": [],
        "synthetic_logic": [],
        "data_limits": []
    }
    
    all_files = []
    
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            path = Path(root) / file
            try:
                size = path.stat().st_size
                all_files.append((path, size))
                
                # 5KB Check for technical files
                if size < 5120 and path.suffix in ['.py', '.js', '.html']:
                    # Only flag if it's a source file, not a config or log
                    if not any(x in path.name.lower() for x in ['requirements', 'env', 'gitignore', 'pm2', 'log', 'bat', 'ps1', 'json']):
                        results["under_5kb"].append(f"{path.relative_to(BASE_DIR)} ({size} bytes)")
                
                # Hardcoded Secrets & Logic
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                    # Secrets (Basic regex)
                    if re.search(r'(api_key|api_secret|token|password|secret)\s*=\s*[\'"][a-zA-Z0-9]{10,}[\'"]', content, re.I):
                        # Filter out common placeholders
                        if not any(x in content for x in ["YOUR_", "API_KEY"]):
                            results["hardcoded_secrets"].append(str(path.relative_to(BASE_DIR)))
                    
                    # Synthetic Logic Check
                    if any(x in content.lower() for x in ["mock_", "fake_data", "placeholder", "simulated_"]):
                        results["synthetic_logic"].append(str(path.relative_to(BASE_DIR)))
                        
                    # Data Limits
                    if re.search(r'\[\s*:\s*(20|50|100)\s*\]', content):
                        results["data_limits"].append(str(path.relative_to(BASE_DIR)))
            except Exception as e:
                pass

    # Duplicate Sizes
    size_map = {}
    for p, s in all_files:
        if s > 0:
            size_map.setdefault(s, []).append(str(p.relative_to(BASE_DIR)))
    
    results["duplicate_sizes"] = {s: names for s, names in size_map.items() if len(names) > 1 and s > 500} # Only >500 bytes to avoid trivial matches

    return results

if __name__ == "__main__":
    report = run_audit()
    print("--- SqueezeOS Audit Report ---")
    for key, val in report.items():
        print(f"\n[{key.upper()}]")
        if isinstance(val, list):
            unique_vals = sorted(list(set(val)))
            for item in unique_vals: print(f" - {item}")
        else:
            for s, names in val.items(): 
                if len(names) > 1:
                    print(f" - {s} bytes: {', '.join(names)}")
