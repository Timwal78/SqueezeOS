# encoding-safe patcher
import os

# Get path from environment variable or use a reasonable default
path = os.environ.get(
    "SQUEEZE_OS_PATH",
    "analytical-engine.js"
)

if not os.path.exists(path):
    print(f"❌ ERROR: File not found at {path}")
    print("Set SQUEEZE_OS_PATH environment variable to the correct location.")
    exit(1)

with open(path, 'rb') as f:
    data = f.read()

# Replace the renderPerformance function hook
old_hook = b'renderPerformance() {'
new_hook = b'renderPerformance() {\n        if (typeof this.updatePerfBadge === \'function\') this.updatePerfBadge();'

if old_hook in data:
    data = data.replace(old_hook, new_hook)
    
# Add the updatePerfBadge function at the end of the object (before the last };)
# This is a bit tricky with bytes, but we can look for the last 'AnalyticalEngine.init();' and work back
marker = b'AnalyticalEngine.init();'
if marker in data:
    # Finding the end of the object is hard without a parser, but we can try to append it before the window assignment
    obj_end_marker = b'window.AnalyticalEngine = AnalyticalEngine;'
    func_code = b"""
    updatePerfBadge() {
        if (!this.perfData) return;
        const d = this.perfData;
        const badgePnl = document.getElementById('badge-pnl');
        const badgeWr = document.getElementById('badge-wr');
        const badgePf = document.getElementById('badge-pf');
        if (badgePnl) {
            badgePnl.innerText = `$${d.total_pnl.toFixed(2)}`;
            badgePnl.className = `perf-val ${d.total_pnl >= 0 ? 'pos' : 'neg'}`;
        }
        if (badgeWr) badgeWr.innerText = `${d.win_rate.toFixed(1)}%`;
        if (badgePf) badgePf.innerText = d.profit_factor.toFixed(2);
    },
"""
    # Insert before 'window.AnalyticalEngine ='
    data = data.replace(obj_end_marker, func_code + b'\n' + obj_end_marker)

with open(path, 'wb') as f:
    f.write(data)
print("✅ Patch applied successfully.")
