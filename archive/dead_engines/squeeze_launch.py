#!/usr/bin/env python3
"""
squeeze_launch.py — SqueezeOS Pro Single-Instance Launcher
============================================================
Kills any process on port 8182, then starts server_v5.py cleanly.
Usage: python squeeze_launch.py
"""
import subprocess, sys, time, os, signal

PORT = 8182
LOG_OUT = "squeeze_stdout.log"
LOG_ERR  = "squeeze_stderr.log"
SERVER   = "-m"
MODULE   = "core.app"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def kill_port(port):
    """Kill any process listening on the given port."""
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue "
             f"| Select-Object -ExpandProperty OwningProcess"],
            capture_output=True, text=True, timeout=10
        )
        pids = [int(p.strip()) for p in result.stdout.splitlines() if p.strip().isdigit()]
        for pid in set(pids):
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                print(f"  [OK] Killed PID {pid}")
            except Exception as e:
                print(f"  [!] Could not kill PID {pid}: {e}")
        if pids:
            time.sleep(2)
    except Exception as e:
        print(f"  Port kill error: {e}")


def main():
    print("[SqueezeOS Pro Launcher]")
    print(f"   Working dir : {BASE_DIR}")
    print(f"   Server      : {SERVER}")
    print(f"   Port        : {PORT}")
    print()

    print(f"[1] Clearing port {PORT}...")
    kill_port(PORT)

    print(f"[2] Starting {SERVER}...")
    with open(os.path.join(BASE_DIR, LOG_OUT), "w") as fout, \
         open(os.path.join(BASE_DIR, LOG_ERR),  "w") as ferr:
        proc = subprocess.Popen(
            [sys.executable, SERVER, MODULE],
            cwd=BASE_DIR,
            stdout=fout,
            stderr=ferr
        )

    print(f"   PID: {proc.pid}")
    print(f"   Logs: {LOG_ERR}")
    print()
    print("[3] Waiting 15s for startup...")
    time.sleep(15)

    # Quick health check
    try:
        import requests, urllib3
        urllib3.disable_warnings()
        r = requests.get(f"http://localhost:{PORT}/api/status", timeout=6)
        d = r.json()
        print(f"[OK] ONLINE -- {d.get('status')} | mode={d.get('trading_mode')} | broker={d.get('broker')} | uptime={d.get('uptime_sec')}s")
    except Exception as e:
        print(f"[!] Health check failed (server may still be starting): {e}")

    print()
    print("Tail logs with:  Get-Content squeeze_stderr.log -Wait -Tail 20")
    print(f"Stop with:       Stop-Process -Id {proc.pid} -Force")


if __name__ == "__main__":
    main()
