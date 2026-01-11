// Smart Home Remote + Chat UI

class RemoteChatApp {
    constructor() {
        this.ws = null;
        this.messagesContainer = document.getElementById('messages');
        this.messageInput = document.getElementById('message-input');
        this.chatForm = document.getElementById('chat-form');
        this.statusEl = document.getElementById('status');
        this.statusDot = document.getElementById('status-dot');
        this.typingEl = document.getElementById('typing');
        this.statusMessage = null;
        this.selectedDevice = null;
        this.devices = [];
        this.isProcessing = false;
        this.prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

        this.init();
    }

    init() {
        this.loadDevices();  // Load devices first
        this.connect();
        this.chatForm.addEventListener('submit', (e) => this.handleSubmit(e));
        this.setupRemoteButtons();
        this.setupKeyboardShortcuts();

        // Listen for reduced motion preference changes
        window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (e) => {
            this.prefersReducedMotion = e.matches;
        });
    }

    async loadDevices() {
        try {
            const response = await fetch('/api/devices');
            const data = await response.json();
            this.devices = data.devices || [];
            this.renderDeviceSelector();

            // Select first online device
            const firstOnline = this.devices.find(d => d.online);
            if (firstOnline) {
                this.selectedDevice = firstOnline.id;
                this.loadApps();
                this.loadTVStatus();
            }
        } catch (err) {
            console.error('Failed to load devices:', err);
            this.renderDeviceSelector();
        }
    }

    renderDeviceSelector() {
        const container = document.getElementById('device-selector');
        if (!container) return;

        if (!this.devices.length) {
            container.innerHTML = `
                <div class="flex-1 text-xs text-zinc-500 py-2.5 px-3">No TVs found</div>
                <button id="scan-btn" class="text-xs text-zinc-400 hover:text-zinc-200 px-3 py-2" title="Scan for TVs">↻</button>
            `;
            document.getElementById('scan-btn')?.addEventListener('click', () => this.scanDevices());
            return;
        }

        container.innerHTML = this.devices.map((dev, i) => `
            <button class="tv-btn flex-1 py-2.5 px-3 rounded-lg text-xs font-semibold transition-colors duration-150 
                          ${i === 0 ? 'text-zinc-50 bg-blue-500' : 'text-zinc-400 bg-transparent hover:text-zinc-50'}
                          ${!dev.online ? 'opacity-50' : ''}
                          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                    data-device="${dev.id}" 
                    role="tab" 
                    aria-selected="${i === 0}"
                    ${!dev.online ? 'disabled' : ''}>
                ${dev.name}
            </button>
        `).join('');

        this.setupTVSelector();
    }

    async scanDevices() {
        const btn = document.getElementById('scan-btn');
        if (btn) btn.textContent = '...';

        try {
            await fetch('/api/devices/scan', { method: 'POST' });
            await this.loadDevices();
        } catch (err) {
            console.error('Scan failed:', err);
        }

        if (btn) btn.textContent = '↻';
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Don't intercept when typing in input
            if (document.activeElement === this.messageInput) {
                return;
            }

            const keyMap = {
                'ArrowUp': 'up',
                'ArrowDown': 'down',
                'ArrowLeft': 'left',
                'ArrowRight': 'right',
                'Enter': 'select',
                'Backspace': 'back',
                'Escape': 'home',
                ' ': 'play_pause',  // Spacebar
            };

            const action = keyMap[e.key];
            if (action) {
                e.preventDefault();
                this.sendRemoteCommand(action);

                // Visual feedback on corresponding button (only if motion allowed)
                const btn = document.querySelector(`[data-action="${action}"]`);
                if (btn && !this.prefersReducedMotion) {
                    btn.classList.add('scale-95');
                    setTimeout(() => btn.classList.remove('scale-95'), 100);
                }
            }
        });
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.statusEl.textContent = 'Connected';
            this.statusDot.classList.add('connected');
        };

        this.ws.onclose = () => {
            this.statusEl.textContent = 'Disconnected';
            this.statusDot.classList.remove('connected');
            setTimeout(() => this.connect(), 3000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.statusEl.textContent = 'Error';
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };
    }

    setupTVSelector() {
        document.querySelectorAll('.tv-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.disabled) return;

                document.querySelectorAll('.tv-btn').forEach(b => {
                    b.classList.remove('active');
                    b.classList.add('text-zinc-400', 'bg-transparent');
                    b.classList.remove('text-zinc-50', 'bg-blue-500');
                    b.setAttribute('aria-selected', 'false');
                });
                btn.classList.add('active');
                btn.classList.remove('text-zinc-400', 'bg-transparent');
                btn.classList.add('text-zinc-50', 'bg-blue-500');
                btn.setAttribute('aria-selected', 'true');
                this.selectedDevice = btn.dataset.device;
                this.loadApps();
                this.loadTVStatus();
            });
        });
    }

    async loadTVStatus() {
        // Don't fetch status while processing a message
        if (this.isProcessing) return;

        try {
            const response = await fetch(`/api/remote/status/${this.selectedDevice}`);
            const data = await response.json();
            if (data.status) {
                // Clear existing messages and show new status
                this.messagesContainer.innerHTML = '';
                this.addMessage('assistant', data.status);
            }
        } catch (err) {
            console.error('Failed to load TV status:', err);
        }
    }

    async loadApps() {
        const grid = document.getElementById('apps-grid');
        grid.innerHTML = '<div class="col-span-full text-center text-xs text-zinc-500 py-3">Loading...</div>';

        try {
            const response = await fetch(`/api/remote/apps/${this.selectedDevice}`);
            const data = await response.json();

            if (data.configured === false) {
                grid.innerHTML = '<div class="col-span-full text-center text-xs text-zinc-500 py-3">Configure TV in .env</div>';
            } else if (data.apps && data.apps.length > 0) {
                grid.innerHTML = data.apps.map(app => {
                    const icon = app.logo
                        ? `<img class="app-logo" src="${app.logo}" alt="${app.name}">`
                        : `<span class="app-icon" style="background:${app.color}">${app.name[0]}</span>`;
                    return `
                        <button class="app-btn" data-package="${app.package}" title="${app.name}" aria-label="Open ${app.name}">
                            ${icon}
                            <span class="app-name">${app.name}</span>
                        </button>
                    `;
                }).join('');

                // Add click handlers
                grid.querySelectorAll('.app-btn').forEach(btn => {
                    btn.addEventListener('click', () => this.launchApp(btn.dataset.package));
                });
            } else {
                grid.innerHTML = '<div class="col-span-full text-center text-xs text-zinc-500 py-3">No apps found</div>';
            }
        } catch (err) {
            console.error('Failed to load apps:', err);
            grid.innerHTML = '<div class="col-span-full text-center text-xs text-zinc-500 py-3">Error loading</div>';
        }
    }

    async launchApp(packageName) {
        try {
            await fetch('/api/remote/launch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ device: this.selectedDevice, action: packageName })
            });
        } catch (err) {
            console.error('Failed to launch app:', err);
        }
    }

    setupRemoteButtons() {
        // D-pad and other remote buttons
        document.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                this.sendRemoteCommand(action);

                // Visual feedback via CSS class (respects prefers-reduced-motion via CSS)
                btn.classList.add('scale-95');
                setTimeout(() => btn.classList.remove('scale-95'), 100);
            });
        });
    }

    async sendRemoteCommand(action) {
        // Map button actions to API calls
        const actionMap = {
            'up': { endpoint: 'navigate', params: { action: 'up' } },
            'down': { endpoint: 'navigate', params: { action: 'down' } },
            'left': { endpoint: 'navigate', params: { action: 'left' } },
            'right': { endpoint: 'navigate', params: { action: 'right' } },
            'select': { endpoint: 'navigate', params: { action: 'select' } },
            'back': { endpoint: 'navigate', params: { action: 'back' } },
            'home': { endpoint: 'navigate', params: { action: 'home' } },
            'play_pause': { endpoint: 'play_pause', params: {} },
            'power': { endpoint: 'power', params: {} },
            'vol_up': { endpoint: 'volume', params: { action: 'up' } },
            'vol_down': { endpoint: 'volume', params: { action: 'down' } },
            'mute': { endpoint: 'volume', params: { action: 'mute' } },
        };

        const cmd = actionMap[action];
        if (!cmd) return;

        try {
            const response = await fetch(`/api/remote/${cmd.endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    device: this.selectedDevice,
                    ...cmd.params
                })
            });

            if (!response.ok) {
                console.error('Remote command failed:', await response.text());
            }
        } catch (err) {
            console.error('Remote command error:', err);
        }
    }

    handleMessage(data) {
        switch (data.type) {
            case 'assistant':
                this.clearStatus();
                this.addMessage('assistant', data.content);
                this.setProcessing(false);
                break;

            case 'status':
                this.showStatus(data.content);
                break;

            case 'typing':
                if (data.content) {
                    this.typingEl.classList.remove('hidden');
                    this.typingEl.classList.add('flex');
                } else {
                    this.typingEl.classList.add('hidden');
                    this.typingEl.classList.remove('flex');
                }
                break;

            case 'error':
                this.clearStatus();
                this.addMessage('error', data.content);
                this.setProcessing(false);
                break;
        }
    }

    showStatus(status) {
        if (!this.statusMessage) {
            this.statusMessage = document.createElement('div');
            this.statusMessage.className = 'message status-message';
            this.statusMessage.innerHTML = '<div class="status-content"></div>';
            this.messagesContainer.appendChild(this.statusMessage);
        }
        this.statusMessage.querySelector('.status-content').textContent = status;
        this.scrollToBottom();
    }

    clearStatus() {
        if (this.statusMessage) {
            this.statusMessage.remove();
            this.statusMessage = null;
        }
    }

    handleSubmit(e) {
        e.preventDefault();
        const message = this.messageInput.value.trim();

        if (!message || this.ws.readyState !== WebSocket.OPEN || this.isProcessing) {
            return;
        }

        this.addMessage('user', message);
        this.ws.send(JSON.stringify({ content: message, device: this.selectedDevice }));
        this.messageInput.value = '';
        this.setProcessing(true);
    }

    setProcessing(processing) {
        this.isProcessing = processing;
        this.messageInput.disabled = processing;
        document.querySelector('.chat-form button, #chat-form button').disabled = processing;
        if (processing) {
            this.messageInput.placeholder = 'Working...';
        } else {
            this.messageInput.placeholder = 'Play Peppa Pig, open Netflix...';
            this.messageInput.focus();
        }
    }

    addMessage(type, content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}`;

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content text-pretty';
        contentDiv.textContent = content;

        // Only show avatar for user messages
        if (type === 'user') {
            const avatar = document.createElement('div');
            avatar.className = 'message-avatar';
            avatar.textContent = 'You';
            messageDiv.appendChild(avatar);
        }

        messageDiv.appendChild(contentDiv);

        this.messagesContainer.appendChild(messageDiv);
        this.scrollToBottom();

        return messageDiv;
    }

    scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new RemoteChatApp();
});
