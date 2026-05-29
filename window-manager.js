const WindowManager = {
    windows: [],
    zIndexCounter: 100,
    container: null,
    cascade: 0,

    init() {
        this.container = document.body; // Use body for overlays in tiled mode
        document.addEventListener('mousemove', (e) => this.onMove(e));
        document.addEventListener('mouseup', () => this.onUp());
    },

    openSettings() {
        this.createWindow('settings', { width: '400px', height: '500px', left: '50%', top: '50%', transform: 'translate(-50%, -50%)' });
    },

    createWindow(type, opts = {}) {
        const id = `win-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
        const cfg = this.getConfig(type);

        const win = document.createElement('div');
        win.id = id;
        win.className = 'mdi-window focused';
        win.style.width = opts.width || cfg.width;
        win.style.height = opts.height || cfg.height;
        win.style.left = opts.left || '100px';
        win.style.top = opts.top || '100px';
        if (opts.transform) win.style.transform = opts.transform;
        win.style.zIndex = ++this.zIndexCounter;

        win.innerHTML = `
            <div class="mdi-window-header">
                <div class="window-title">${cfg.title}</div>
                <div class="window-controls">
                    <button class="control-btn btn-close" onclick="WindowManager.closeWindow('${id}')"></button>
                </div>
            </div>
            <div class="mdi-window-content" id="content-${id}">
                <div class="loading-msg"><div class="spinner"></div>INITIALIZING...</div>
            </div>
            <div class="resize-handle"></div>
        `;

        this.container.appendChild(win);
        const obj = { id, el: win, isDragging: false, isResizing: false, offsetX: 0, offsetY: 0, type };
        this.bindEvents(obj);
        this.windows.push(obj);
        this.focus(id);

        requestAnimationFrame(() => {
            if (type === 'settings' && window.SettingsPanel) SettingsPanel.init(id);
            if (type === 'schwab-hub' && window.SchwabIntegration) window.SchwabIntegration.initTokenHub(id);
        });
        return id;
    },

    getConfig(type) {
        return {
            'settings': { title: '⚙️ SYSTEM SETTINGS', width: '400px', height: '500px' },
            'schwab-hub': { title: '🔑 SCHWAB TOKEN HUB', width: '420px', height: '320px' },
        }[type] || { title: 'Window', width: '400px', height: '300px' };
    },

    bindEvents(obj) {
        const hdr = obj.el.querySelector('.mdi-window-header');
        const rsz = obj.el.querySelector('.resize-handle');
        hdr.addEventListener('mousedown', (e) => {
            if (e.target.classList.contains('control-btn')) return;
            this.focus(obj.id);
            obj.isDragging = true;
            obj.offsetX = e.clientX - obj.el.offsetLeft;
            obj.offsetY = e.clientY - obj.el.offsetTop;
            obj.el.style.transition = 'none';
        });
        if (rsz) {
            rsz.addEventListener('mousedown', (e) => {
                this.focus(obj.id);
                obj.isResizing = true;
                obj.startW = obj.el.offsetWidth; obj.startH = obj.el.offsetHeight;
                obj.startX = e.clientX; obj.startY = e.clientY;
                obj.el.style.transition = 'none';
                e.stopPropagation();
            });
        }
        obj.el.addEventListener('mousedown', () => this.focus(obj.id));
    },

    onMove(e) {
        this.windows.forEach(w => {
            if (w.isDragging) { w.el.style.left = `${e.clientX - w.offsetX}px`; w.el.style.top = `${e.clientY - w.offsetY}px`; }
            else if (w.isResizing) { w.el.style.width = `${w.startW + (e.clientX - w.startX)}px`; w.el.style.height = `${w.startH + (e.clientY - w.startY)}px`; }
        });
    },

    onUp() { this.windows.forEach(w => { w.isDragging = false; w.isResizing = false; w.el.style.transition = ''; }); },

    focus(id) {
        this.windows.forEach(w => {
            if (w.id === id) { w.el.style.zIndex = ++this.zIndexCounter; w.el.classList.add('focused'); }
            else w.el.classList.remove('focused');
        });
    },

    closeWindow(id) {
        const i = this.windows.findIndex(w => w.id === id);
        if (i > -1) { this.windows[i].el.remove(); this.windows.splice(i, 1); }
    }
};
window.WindowManager = WindowManager;
