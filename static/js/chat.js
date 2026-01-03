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
        this.selectedDevice = 'fire_tv';
        this.isProcessing = false;

        this.init();
    }

    init() {
        this.connect();
        this.chatForm.addEventListener('submit', (e) => this.handleSubmit(e));
        this.setupRemoteButtons();
        this.setupTVSelector();
        this.setupKeyboardShortcuts();
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

                // Visual feedback on corresponding button
                const btn = document.querySelector(`[data-action="${action}"]`);
                if (btn) {
                    btn.style.transform = 'scale(0.9)';
                    setTimeout(() => btn.style.transform = '', 100);
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
                document.querySelectorAll('.tv-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.selectedDevice = btn.dataset.device;
                this.loadApps();
            });
        });
        // Load apps for default device
        this.loadApps();
    }

    async loadApps() {
        const grid = document.getElementById('apps-grid');
        grid.innerHTML = '<div class="apps-loading">Loading...</div>';

        try {
            const response = await fetch(`/api/remote/apps/${this.selectedDevice}`);
            const data = await response.json();

            if (data.apps && data.apps.length > 0) {
                grid.innerHTML = data.apps.map(app => {
                    const icon = app.logo
                        ? `<img class="app-logo" src="${app.logo}" alt="${app.name}">`
                        : `<span class="app-icon" style="background:${app.color}">${app.name[0]}</span>`;
                    return `
                        <button class="app-btn" data-package="${app.package}" title="${app.name}">
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
                grid.innerHTML = '<div class="apps-empty">No apps found</div>';
            }
        } catch (err) {
            console.error('Failed to load apps:', err);
            grid.innerHTML = '<div class="apps-empty">Error loading</div>';
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

                // Visual feedback
                btn.style.transform = 'scale(0.9)';
                setTimeout(() => btn.style.transform = '', 100);
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
                this.typingEl.style.display = data.content ? 'flex' : 'none';
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
        this.ws.send(JSON.stringify({ content: message }));
        this.messageInput.value = '';
        this.setProcessing(true);
    }

    setProcessing(processing) {
        this.isProcessing = processing;
        this.messageInput.disabled = processing;
        document.querySelector('.chat-form button').disabled = processing;
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

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.textContent = type === 'user' ? 'You' : 'AI';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.textContent = content;

        messageDiv.appendChild(avatar);
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
