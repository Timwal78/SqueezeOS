/**
 * holy-grail.js — SqueezeOS v5.2 Layout Manager
 * 
 * Handles responsive grid adjustments, resize observing, 
 * and tactical UI interactions for the SqueezeOS Pro terminal.
 */

const HolyGrail = {
    initialized: false,
    
    init() {
        if (this.initialized) return;
        this.initialized = true;

        this.adjustLayout();
        
        // Listen to window resize
        window.addEventListener('resize', () => this.adjustLayout());
        
        // Setup ResizeObserver for the main grid
        this.setupResizeObserver();
        
        console.log('[HOLY-GRAIL] v5.2 Layout Engine Engaged.');
    },

    setupResizeObserver() {
        const grid = document.getElementById('desktop-grid');
        if (!grid || !window.ResizeObserver) return;
        
        const ro = new ResizeObserver(() => this.adjustLayout());
        ro.observe(grid);
    },

    adjustLayout() {
        const vw = window.innerWidth;
        const grid = document.getElementById('desktop-grid');
        if (!grid) return;

        // Institution Pro Layout (Wide)
        if (vw > 1600) {
            grid.style.gridTemplateColumns = '320px 1fr 320px 420px';
            grid.style.gridTemplateRows = '1fr 280px';
        }
        // Laptop Pro Layout
        else if (vw > 1200) {
            grid.style.gridTemplateColumns = '280px 1fr 280px 360px';
            grid.style.gridTemplateRows = '1fr 240px';
        }
        // Tablet / Compact Mode
        else if (vw > 1000) {
            grid.style.gridTemplateColumns = '260px 1fr 260px';
            grid.style.gridTemplateRows = '1fr 1fr 220px';
        }
        // Mobile Stacked Mode
        else {
            grid.style.gridTemplateColumns = '1fr';
            grid.style.gridTemplateRows = 'auto';
            grid.style.height = 'auto';
            grid.style.overflowY = 'visible';
        }
    },

    /**
     * Tactical HUD: Flash a panel to indicate new critical data
     */
    flashPanel(id, type = 'blue') {
        const el = document.getElementById(id);
        if (!el) return;
        
        const color = type === 'green' ? 'var(--neon-green-glow)' : 
                      type === 'red' ? 'var(--neon-red-glow)' : 
                      'var(--neon-blue-glow)';
                      
        el.style.boxShadow = `0 0 30px ${color}, 0 0 1px ${color} inset`;
        el.style.borderColor = color;
        
        setTimeout(() => {
            el.style.boxShadow = '';
            el.style.borderColor = '';
        }, 1000);
    },

    /**
     * Auto-scroll terminal feeds
     */
    scrollToBottom(id) {
        const el = document.getElementById(id);
        if (el) {
            el.scrollTo({
                top: el.scrollHeight,
                behavior: 'smooth'
            });
        }
    }
};

// Auto-boot
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => HolyGrail.init());
} else {
    HolyGrail.init();
}

window.HolyGrail = HolyGrail;
