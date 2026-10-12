// Quant Desk — logica della dashboard (Alpine.js). API_TOKEN è inserito dal template dopo il login.
const CHAT_TIMEOUT_MS = 13000;  // la chat non resta mai bloccata su "penso…" (il server risponde entro ~9 s, contesto compreso)

function dashboard() {
    return {
        connected: true,
        tab: 'command',
        tabs: [
            { id: 'command', label: 'Agenti & Comandi' },
            { id: 'markets', label: 'Mercati' },
            { id: 'portfolio', label: 'Portafoglio' },
            { id: 'audit', label: 'Audit' },
        ],
        // Agent Matrix
        agents: [], blocks: { asset_classes: [], sectors: [], symbols: [] }, blockLabels: [], tuning: null, agentBusy: '',
        brainOpen: false, brainId: '', brain: null, brainTimer: null,
        // Stanza dei Dipendenti AI
        persona: 'coo', chatMessages: [], chatInput: '', chatSending: false, chatPending: {},
        personas: {
            coo: { name: 'COO', short: 'COO', tagline: 'COO: chiedimi qualsiasi cosa su bot, mercati e portafoglio. Posso proporre modifiche (agenti, blocchi, aggressività, modalità): le applico solo dopo la tua conferma.' },
            risk: { name: 'Risk Manager', short: 'Risk Manager', tagline: 'Risk Manager: stesse capacità, con un occhio più severo su rischi, drawdown e protezioni. Nessuna modifica senza la tua conferma.' },
        },
        chatSuggestions: ['Come sta andando il portafoglio?', 'Perché il portafoglio è fermo?', 'Cosa stanno scansionando gli Scout?', 'Come funziona il Guardian?', 'Conviene ridurre il rischio?'],
        account: {}, positions: [], closedPositions: [], bot: { logs: [] },
        radar: {}, channels: {}, macro: {}, perf: {}, cio: {},
        settings: { watchlist: [] }, envLocked: {},
        showSettings: false, saving: false, notice: '', noticeError: false, tickerInput: '',
        showPosition: false, posSymbol: '', posDetail: null, posLoading: false, posError: '', posNotice: '', posNoticeError: false, selling: false,
        deRisking: '',
        showHistory: false, historyRows: [], historyOffline: true, historyLoading: false,
        audit: {}, auditTab: 'rejected', auditStage: '',
        auditTabs: [{ id: 'rejected', label: 'Bocciate (5h)' }, { id: 'executed', label: 'Approvate & Storico' }, { id: 'scorecard', label: 'Pagella Agenti' }],
        localLogs: [], clearedId: 0, clearedTs: 0,
        logs: [], lastLogId: 0, dialogue: [], lastDialogueId: 0, fetching: false, streamPinned: true,
        numberFields: [
            { key: 'stop_loss_pct', label: 'Stop di riserva % (se manca ATR)', step: 0.5, min: -50, max: -0.5 },
            { key: 'scan_interval_min', label: 'Intervallo di scansione (min)', step: 1, min: 1, max: 1440 },
            { key: 'max_allocation_pct', label: 'Soffitto per operazione % (8-25%, fino a 50% solo SUPER_CONVICTION)', step: 0.5, min: 0.5, max: 100 },
            { key: 'max_exposure_pct', label: 'Esposizione massima % (tetto Safety Net 50)', step: 5, min: 10, max: 50 },
        ],

        init() {
            try { const t = localStorage.getItem('jarvis.tab'); if (t && this.tabs.some(x => x.id === t)) this.tab = t; } catch (e) { /* storage non disponibile */ }
            this.fetchStatus();
            this.loadSettings();
            setInterval(() => this.fetchStatus(), 1000);
            this.loadAudit();
            setInterval(() => this.loadAudit(), 15000);
            this.loadAgents();
            setInterval(() => this.loadAgents(), 2000);
            this.loadChat();
            this.$watch('tab', t => { try { localStorage.setItem('jarvis.tab', t); } catch (e) { /* ignora */ } this.icons(); });
            this.icons();
        },
        icons() { this.$nextTick(() => window.lucide && lucide.createIcons()); },

        // ---------- HUD: 4 indicatori leggibili da chiunque ----------
        investedPct() {
            const eq = Number(this.account.portfolio);
            if (!eq || this.account.exposure === undefined) return null;
            return Math.min(100, Math.max(0, this.account.exposure / eq * 100));
        },
        health() {
            if (!this.connected) return { label: 'OFFLINE', pill: 'pill-muted', hint: 'Riconnessione al server in corso' };
            if (!this.bot.active) return { label: 'IN PAUSA', pill: 'pill-muted', hint: 'Agenti fermi: nessuna scansione né acquisto' };
            const pnl = Number(this.account.daily_pnl_pct);
            if (!isNaN(pnl) && pnl <= -3) return { label: 'PROTEZIONE ATTIVA', pill: 'pill-down', hint: `Giornata ${this.pct(pnl)}: priorità alla difesa del capitale` };
            return { label: 'OPERATIVO', pill: 'pill-up', hint: this.settings.auto_execute_trades ? 'Auto-Trading attivo' : 'Advisor: ordini non inviati' };
        },
        pnlPill(v) {
            if (v === null || v === undefined || isNaN(v) || Number(v) === 0) return 'pill-muted';
            return Number(v) > 0 ? 'pill-up' : 'pill-down';
        },
        focusCommand() { this.tab = 'command'; this.$nextTick(() => this.$refs.cmd && this.$refs.cmd.focus()); },
        thoughtColor(t) {
            if (t.level === 'veto' || /❌|Errore|VETO|🚨|🛑|REJECTED/.test(t.text)) return 'text-red-400';
            if (t.level === 'ok' || /✅|APPROVED|ESEGUIT/.test(t.text)) return 'text-emerald-500';
            if (t.level === 'muted') return 'text-zinc-500';
            return 'text-zinc-300';
        },

        // ---------- Agent Matrix ----------
        async loadAgents() {
            try {
                const res = await fetch('/api/agents');
                if (res.status === 401) { window.location.href = '/login'; return; }
                if (!res.ok) return;
                const data = await res.json();
                const firstLoad = !this.agents.length;
                this.agents = data.agents || [];
                this.blocks = data.blocks || this.blocks;
                this.blockLabels = data.block_labels || [];
                if (firstLoad) this.icons();
            } catch (e) { /* riprova al prossimo giro */ }
        },
        statusText(st) {
            return { ACTIVE: 'ATTIVO', PROCESSING: 'ELABORAZIONE IN CORSO', PAUSED: 'IN PAUSA', STANDBY: 'STANDBY' }[st] || st;
        },
        async controlAgent(a, body) {
            this.agentBusy = a.id;
            try {
                const { res, data } = await this.api('/api/agents/' + a.id + '/control', 'POST', body);
                this.addLog(data.message || (res.ok ? 'Comando inviato' : 'Errore'), !res.ok);
                this.toast(data.message || (res.ok ? 'Comando inviato' : 'Errore'), !res.ok);
                await this.loadAgents();
                if (this.brainOpen && this.brainId === a.id) this.loadBrain();
            } finally {
                this.agentBusy = '';
            }
        },
        togglePause(a) {
            if (!a.paused && a.id === '06' && this.positions.length &&
                !confirm(`Il Guardian protegge ${this.positions.length} posizioni aperte. Sospenderlo davvero?`)) return;
            this.controlAgent(a, { paused: !a.paused });
        },
        async removeBlock(kind, value) {
            const { res, data } = await this.api('/api/controls/blocks', 'POST', kind ? { kind, value } : { clear: true });
            if (res.ok) { this.blocks = data.blocks; this.loadAgents(); this.toast('Blocchi aggiornati'); }
        },
        blockChips() {
            const b = this.blocks || {};
            const sectorLabel = { tech: 'Tecnologia', commodities: 'Materie prime', bonds: 'Obbligazioni', energy: 'Energia', finance: 'Finanza', biotech: 'Biotech' };
            return [
                ...(b.asset_classes || []).map(v => ({ kind: 'asset', value: v, label: v === 'crypto' ? 'Crypto' : 'Azioni' })),
                ...(b.sectors || []).map(v => ({ kind: 'sector', value: v, label: sectorLabel[v] || v })),
                ...(b.symbols || []).map(v => ({ kind: 'symbol', value: v, label: v })),
            ];
        },

        // ---------- Ispeziona Cervello (drawer) ----------
        openBrain(a) {
            this.brainId = a.id; this.brain = { agent: a, thoughts: null }; this.brainOpen = true;
            this.loadBrain();
            clearInterval(this.brainTimer);
            this.brainTimer = setInterval(() => this.brainOpen ? this.loadBrain() : clearInterval(this.brainTimer), 2000);
            this.icons();
        },
        closeBrain() { this.brainOpen = false; clearInterval(this.brainTimer); },
        async loadBrain() {
            try {
                const res = await fetch('/api/agents/' + this.brainId + '/brain');
                if (res.ok && this.brainOpen) this.brain = await res.json();
            } catch (e) { /* riprova */ }
        },
        ago(ts) {
            if (!ts) return '';
            const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
            return s < 60 ? s + 's fa' : s < 3600 ? Math.round(s / 60) + ' min fa' : Math.round(s / 3600) + ' h fa';
        },

        // ---------- Stanza dei Dipendenti AI ----------
        async loadChat() {
            try {
                const res = await this.fetchWithTimeout('/api/chat', {}, CHAT_TIMEOUT_MS);
                if (res.ok) { const d = await res.json(); this.chatMessages = d.messages || []; this.chatPending = d.pending || {}; this.scrollChat(); }
            } catch (e) { /* riprova */ }
        },
        personaMessages() { return this.chatMessages.filter(m => m.persona === this.persona); },
        scrollChat() { this.$nextTick(() => { const b = this.$refs.chat; if (b) b.scrollTo({ top: b.scrollHeight, behavior: 'smooth' }); }); },
        async sendChat(text) {
            const message = (text ?? this.chatInput).trim();
            if (!message || this.chatSending) return;
            const fail = (msg) => this.chatMessages.push({ id: 'err' + Date.now(), role: 'agent', persona: this.persona, verdict: 'IMPOSSIBILE',
                                                          author: this.personas[this.persona].name, text: msg });
            this.chatInput = '';
            this.chatSending = true;
            const local = { id: 'tmp' + Date.now(), role: 'user', persona: this.persona, author: 'Comandante', text: message,
                            time: new Date().toLocaleTimeString('it-IT') };
            this.chatMessages.push(local);
            this.scrollChat();
            try {
                const { res, data } = await this.api('/api/chat', 'POST', { persona: this.persona, message }, CHAT_TIMEOUT_MS);
                if (res.ok && data.reply) {
                    this.chatMessages = this.chatMessages.filter(m => m !== local);
                    this.chatMessages.push({ ...local, id: 'sent' + Date.now() }, data.reply);   // risposta subito visibile
                    this.loadChat();   // riallinea storico e proposte in sospeso, senza bloccare l'input
                    if (data.reply.change) { this.loadAgents(); this.loadSettings(); this.fetchStatus(); }
                } else {
                    fail(data.message || 'Errore di comunicazione con il dirigente.');
                }
            } catch (e) {
                fail(e.name === 'AbortError' ? `Nessuna risposta entro ${CHAT_TIMEOUT_MS / 1000} secondi: riprova.` : 'Connessione persa: ' + e.message);
            } finally {
                this.chatSending = false;   // in OGNI caso: "penso…" -> "Invia", input sbloccato
                this.scrollChat();
                this.$nextTick(() => this.$refs.cmd?.focus());
            }
        },
        verdictTone(v) {
            return { ESEGUITO: 'text-emerald-500', SCONSIGLIATO: 'text-amber-500', IMPOSSIBILE: 'text-red-500', PROPOSTA: 'text-sky-400' }[v] || 'text-indigo-400';
        },

        // ---------- toast ----------
        toasts: [],
        toast(text, error = false) {
            const t = { id: Date.now() + Math.random(), text, error };
            this.toasts.push(t);
            setTimeout(() => { this.toasts = this.toasts.filter(x => x !== t); }, 3800);
        },

        // ---------- formattazione ----------
        usd(v, signed = false) {
            if (v === null || v === undefined || isNaN(v)) return '—';
            const n = Number(v);
            const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
            return (signed ? (n > 0 ? '+' : n < 0 ? '−' : '') : (n < 0 ? '−' : '')) + '$' + s;
        },
        pct(v) {
            if (v === null || v === undefined || isNaN(v)) return '—';
            const n = Number(v);
            return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toFixed(2) + '%';
        },
        qty(v) { return Number(v).toLocaleString('en-US', { maximumFractionDigits: 6 }); },
        tone(v) {
            if (v === null || v === undefined || isNaN(v) || Number(v) === 0) return 'text-zinc-300';
            return Number(v) > 0 ? 'text-emerald-500' : 'text-red-500';
        },
        exposurePct() {
            const eq = Number(this.account.portfolio);
            if (!eq || this.account.exposure === undefined) return '—';
            return (this.account.exposure / eq * 100).toFixed(1) + '%';
        },
        duration(min) {
            if (min === null || min === undefined) return '—';
            if (min < 60) return Math.round(min) + ' min';
            if (min < 1440) return (min / 60).toFixed(1) + ' h';
            return (min / 1440).toFixed(1) + ' g';
        },
        weight(p) {
            const eq = Number(this.account.portfolio);
            return eq ? (p.market_value / eq * 100).toFixed(1) + '% (peso)' : '—';
        },
        vetoes() { return (this.radar.recent || []).filter(r => r.status === 'REJECTED_BY_RISK').slice(0, 8); },
        otherRecent() { return (this.radar.recent || []).filter(r => r.status !== 'REJECTED_BY_RISK').slice(0, 5); },
        shortTime(iso) {
            return iso ? String(iso).replace('T', ' ').slice(11, 19) : '';
        },
        mmss(sec) {
            if (sec === null || sec === undefined) return '';
            const s = Math.max(0, Math.floor(sec));
            return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
        },
        statusLabel(st) {
            return { SUBMITTED_PITCH: 'PITCH', UNDER_REVIEW: 'IN REVISIONE', APPROVED_BY_RISK: 'APPROVATA',
                     REJECTED_BY_RISK: 'VETO', EXPIRED: 'SCADUTA', EXECUTED: 'ESEGUITA' }[st] || st;
        },
        statusStyle(st, textOnly = false) {
            const map = {
                APPROVED_BY_RISK: ['border-emerald-500/30 text-emerald-500', 'text-emerald-500'],
                EXECUTED: ['border-indigo-500/40 text-indigo-400', 'text-indigo-400'],
                REJECTED_BY_RISK: ['border-red-500/30 text-red-500', 'text-red-500'],
                EXPIRED: ['border-zinc-700 text-zinc-500', 'text-zinc-500'],
            };
            const v = map[st] || ['border-amber-500/30 text-amber-400', 'text-amber-400'];
            return textOnly ? v[1] : v[0];
        },
        actionStyle(a) {
            return {
                BUY: 'border-emerald-500/30 text-emerald-500 bg-emerald-500/10',
                SELL: 'border-red-500/30 text-red-500 bg-red-500/10',
                ROTATE: 'border-indigo-500/40 text-indigo-400 bg-indigo-500/10',
            }[a] || 'border-zinc-700 text-zinc-300 bg-zinc-800/40';
        },
        verdictStyle(v) {
            return v === 'APPROVATO' ? 'text-emerald-500' : v === 'RESPINTO' ? 'text-red-500' : 'text-zinc-500';
        },
        cioTarget() {
            const c = this.cio;
            if (c.action === 'ROTATE') return `${c.sell_pct || 100}% ${c.sell_symbol} → ${c.buy_symbol}`;
            if (c.action === 'SELL') return `${c.sell_pct || 100}% ${c.sell_symbol}`;
            return c.buy_symbol || c.sell_symbol || '—';
        },
        cioDescription() {
            const c = this.cio;
            if (c.action === 'ROTATE') return `ROTATE ${c.sell_pct || 100}% ${c.sell_symbol} → ${c.buy_symbol}`;
            if (c.action === 'BUY') return `BUY ${c.buy_symbol}`;
            if (c.action === 'SELL') return `SELL ${c.sell_pct || 100}% ${c.sell_symbol}`;
            return 'HOLD';
        },

        // ---------- log ----------
        logClass(text) {
            if (/❌|Errore|🚨|🛑|VETO|BLOCCATI/.test(text)) return 'text-red-500';
            if (/✅|ORDINE ACQUISTO/.test(text)) return 'text-emerald-300/90';
            if (/⚠️|⛔|🌅|🧭/.test(text)) return 'text-amber-400';
            if (/━━━|===/.test(text)) return 'text-zinc-500';
            return 'text-zinc-400';
        },
        visibleLogs() {
            const server = this.logs
                .filter(l => l && l.id > this.clearedId)
                .map(l => ({ key: 's' + l.id, ts: l.ts, text: l.text, cls: this.logClass(l.text) }));
            const local = this.localLogs.filter(l => l.ts > this.clearedTs);
            return server.concat(local).sort((a, b) => a.ts - b.ts);
        },
        addLog(message, error = false) {
            const ts = Date.now() / 1000;
            const time = new Date().toLocaleTimeString('it-IT');
            this.localLogs.push({ key: 'l' + ts, ts, text: `[${time}] ${message}`, cls: error ? 'text-red-500' : 'text-indigo-400' });
            if (this.localLogs.length > 30) this.localLogs.shift();
        },
        clearLogs() {
            this.clearedId = this.lastLogId;
            this.clearedTs = Date.now() / 1000;
            this.localLogs = [];
        },

        // ---------- API ----------
        async fetchWithTimeout(url, options = {}, timeoutMs = 0) {
            if (!timeoutMs) return fetch(url, options);
            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), timeoutMs);
            try {
                return await fetch(url, { ...options, signal: ctrl.signal });
            } finally {
                clearTimeout(timer);
            }
        },
        async api(url, method = 'POST', body, timeoutMs = 0) {
            const headers = { 'X-API-Key': API_TOKEN };
            if (body !== undefined) headers['Content-Type'] = 'application/json';
            const res = await this.fetchWithTimeout(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined }, timeoutMs);
            if (res.status === 401) { window.location.href = '/login'; }
            const data = await res.json().catch(() => ({}));
            return { res, data };
        },
        async fetchStatus() {
            if (this.fetching) return;   // niente richieste sovrapposte con il polling a 1s
            this.fetching = true;
            try {
                const res = await fetch(`/api/data?since_log=${this.lastLogId}&since_dialogue=${this.lastDialogueId}`);
                if (res.status === 401) { window.location.href = '/login'; return; }
                if (!res.ok) throw new Error(res.status);
                const data = await res.json();
                this.account = data.account || {};
                this.positions = Array.isArray(data.positions) ? data.positions : [];
                this.closedPositions = Array.isArray(data.closed_positions) ? data.closed_positions : [];
                this.bot = data.bot || { logs: [] };
                this.radar = data.radar || {};
                this.channels = this.radar.channels || {};
                this.macro = this.channels.macro || {};
                this.perf = this.bot.performance || {};
                this.cio = this.bot.cio || {};
                // Log e dialoghi arrivano in modo incrementale; riallineamento dopo un riavvio del server
                if ((data.log_head || 0) < this.lastLogId) { this.logs = []; this.lastLogId = 0; this.clearedId = 0; }
                if ((data.dialogue_head || 0) < this.lastDialogueId) { this.dialogue = []; this.lastDialogueId = 0; }
                const newLogs = this.bot.logs || [];
                if (newLogs.length) {
                    this.logs = this.logs.concat(newLogs).slice(-300);
                    this.lastLogId = newLogs[newLogs.length - 1].id;
                }
                const newDialogue = data.agent_dialogue || [];
                if (newDialogue.length) {
                    this.dialogue = this.dialogue.concat(newDialogue).slice(-100);
                    this.lastDialogueId = newDialogue[newDialogue.length - 1].id;
                }
                this.connected = true;
            } catch (e) {
                this.connected = false;
            } finally {
                this.fetching = false;
            }
        },
        streamAlive() {
            const last = this.dialogue[this.dialogue.length - 1];
            return last && (Date.now() / 1000 - last.ts) < 30;
        },
        agentColor(agent) { return agent.startsWith('Scout') ? 'text-zinc-500' : 'text-zinc-400'; },
        feed() { return this.dialogue.slice(-40).reverse(); },
        levelColor(level) {
            return { alert: 'text-amber-400', veto: 'text-red-400', ok: 'text-emerald-500', muted: 'text-zinc-500' }[level] || 'text-zinc-300';
        },
        async loadSettings() {
            try {
                const res = await fetch('/api/settings');
                if (res.status === 401) { window.location.href = '/login'; return; }
                const cfg = await res.json();
                this.envLocked = cfg.env_locked || {};
                delete cfg.env_locked;
                this.settings = cfg;
            } catch (e) { /* riprova alla prossima apertura */ }
        },
        locked(key) { return Boolean(this.envLocked[key]); },
        lockTitle(key) { return this.envLocked[key] ? `Fissato dalla variabile d'ambiente ${this.envLocked[key]} su Render` : ''; },
        addTicker() {
            const t = this.tickerInput.trim().toUpperCase();
            if (!/^[A-Z0-9.\-]{1,15}$/.test(t)) { this.flash('Ticker non valido', true); return; }
            if (!this.settings.watchlist.includes(t)) this.settings.watchlist.push(t);
            this.tickerInput = '';
        },
        removeTicker(t) { this.settings.watchlist = this.settings.watchlist.filter(x => x !== t); },
        flash(message, error = false) {
            this.notice = message; this.noticeError = error;
            clearTimeout(this._noticeTimer);
            this._noticeTimer = setTimeout(() => this.notice = '', 4000);
        },
        async saveSettings() {
            const payload = JSON.parse(JSON.stringify(this.settings));
            for (const key of Object.keys(this.envLocked)) delete payload[key];
            this.saving = true;
            try {
                const { res, data } = await this.api('/api/settings', 'POST', payload);
                if (res.ok && data.settings) {
                    this.envLocked = data.settings.env_locked || {};
                    delete data.settings.env_locked;
                    this.settings = data.settings;
                    this.flash('Impostazioni salvate');
                } else {
                    this.flash(data.message || 'Errore nel salvataggio', true);
                }
            } catch (e) {
                this.flash('Errore nel salvataggio: ' + e.message, true);
            } finally {
                this.saving = false;
            }
        },
        async forceCio() {
            this.addLog('⚡ Forza CIO richiesto');
            const { res, data } = await this.api('/api/scan');
            this.addLog(data.message || (res.ok ? 'CIO attivato' : 'Errore'), !res.ok || data.status === 'warning');
            this.toast(data.message || (res.ok ? 'CIO attivato' : 'Errore'), !res.ok || data.status === 'warning');
        },
        async toggleBot() {
            const { res, data } = await this.api('/api/toggle');
            if (res.ok) {
                this.bot.active = Boolean(data.active);
                this.addLog(data.active ? 'Bot riattivato' : 'Bot in pausa');
                this.toast(data.active ? 'Sistema riattivato' : 'Sistema in pausa');
                this.loadAgents();
            }
        },
        // ---------- scheda posizione ----------
        price(v) {
            if (v === null || v === undefined || isNaN(v)) return '—';
            const n = Number(v);
            return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: Math.abs(n) < 10 ? 6 : 2 });
        },
        dateTime(v) {
            if (!v) return '—';
            const d = new Date(v);
            return isNaN(d) ? String(v) : d.toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'medium' });
        },
        agentRows(a) {
            const f = (v, d = 4) => (v === null || v === undefined) ? 'N/D' : Number(v).toFixed(d);
            const q = a.agent_01_quant || {}, m = a.agent_02_micro || {}, r = a.agent_03_risk || {}, mc = a.agent_04_macro || {}, c = a.agent_05_cio || {};
            const qm = q.metrics || {};
            const g = a.agent_06_guardian || {}, ch = a.agent_07_chop || {};
            const lat = ch.latency_ms || {};
            const chopTxt = ((ch.scouts || []).join(' · ') || 'nessuno Scout attivato')
                + (lat.stage1 != null ? ` · latenze S1 ${lat.stage1}ms / S2 ${lat.stage2}ms / S3 ${lat.stage3}ms` : '');
            return [
                { name: '#1 Quant', score: q.score ?? '—', detail: `Hurst ${f(qm.hurst_exponent)} · GARCH ${f(qm.garch_vol_pct)}% · Z ${f(qm.z_score, 2)} · ${q.signal || ''}` },
                { name: '#2 Micro', score: m.score ?? '—', detail: `VPIN ${f(m.vpin)} · OFI ${f(m.ofi)} · ${m.signal || ''}` },
                { name: '#3 Risk', score: r.score ?? '—', detail: `${r.approved ? 'Approvato' : 'Respinto'} · ${r.reason || ''}` },
                { name: '#4 Macro', score: mc.score ?? '—', detail: `Stress ${mc.stress_level || 'N/D'} · ${mc.approved ? 'Approvato' : 'Respinto'}` },
                { name: '#5 CIO', score: c.score ?? '—', detail: `${c.decision || ''} · ${c.reason || ''}` },
                { name: '#6 Guardian', score: g.approved == null ? '—' : (g.approved ? 'OK' : 'VETO'), detail: g.reason || '' },
                { name: '#7 CHOP', score: (ch.scouts || []).length + ' scout', detail: chopTxt },
            ];
        },
        async openPosition(p) {
            this.posSymbol = p.symbol; this.posDetail = null; this.posError = ''; this.posNotice = '';
            this.showPosition = true; this.posLoading = true;
            try {
                const res = await fetch('/api/positions/' + encodeURIComponent(p.symbol));
                if (res.status === 401) { window.location.href = '/login'; return; }
                const data = await res.json().catch(() => ({}));
                if (!res.ok) { this.posError = data.message || ('Errore ' + res.status); return; }
                this.posDetail = data;
            } catch (e) {
                this.posError = 'Errore di rete: ' + e.message;
            } finally {
                this.posLoading = false;
            }
        },
        async sellNow() {
            const sym = this.posDetail?.position?.symbol || this.posSymbol;
            if (!sym || !confirm(`Vendere SUBITO l'intera posizione ${sym} a mercato?`)) return;
            this.selling = true;
            try {
                const { res, data } = await this.api('/api/positions/' + encodeURIComponent(sym) + '/close');
                this.posNotice = data.message || (res.ok ? 'Vendita inviata' : 'Errore'); this.posNoticeError = !res.ok;
                this.addLog(this.posNotice, !res.ok);
                if (res.ok) { this.fetchStatus(); setTimeout(() => { this.showPosition = false; }, 1200); }
            } finally {
                this.selling = false;
            }
        },

        // 🛡️ Rischio Zero: vende il 50% a mercato e porta lo stop del resto a breakeven + commissioni
        canDeRisk(p) { return p && p.unrealized_pl > 0 && !p.scaled_out && !String(p.side || '').includes('SHORT'); },
        async deRisk(p) {
            const sym = p?.symbol;
            if (!sym || this.deRisking) return;
            if (!confirm(`Attivare RISCHIO ZERO su ${sym}?\n\n• vende subito il 50% a mercato\n• porta lo stop del restante 50% a breakeven + commissioni\n• il resto resta gestito dal Guardian con il Trailing ATR Stop`)) return;
            this.deRisking = sym;
            try {
                const { res, data } = await this.api('/api/position/de-risk', 'POST', { symbol: sym });
                const msg = data.message || (res.ok ? 'Rischio Zero attivato' : 'Errore');
                this.addLog('🛡️ ' + msg, !res.ok);
                if (this.showPosition) { this.posNotice = msg; this.posNoticeError = !res.ok; }
                if (res.ok) this.fetchStatus();
            } finally {
                this.deRisking = '';
            }
        },

        // ---------- audit agenti & revisioni ----------
        async loadAudit() {
            try {
                const res = await fetch('/api/audit');
                if (res.ok) this.audit = await res.json();
            } catch (e) { /* riprova al prossimo giro */ }
        },
        auditRejected() {
            const rows = this.audit.rejected?.rows || [];
            return this.auditStage ? rows.filter(r => r.stage === this.auditStage) : rows;
        },
        agentVotes(a) {
            a = a || {};
            const sc = (x, ok = 60) => x?.score == null ? { value: '—', cls: 'text-zinc-500' }
                : { value: Number(x.score).toFixed(1), cls: x.score >= ok ? 'text-emerald-500' : 'text-zinc-300' };
            const ap = (x) => x?.approved == null ? { value: '—', cls: 'text-zinc-500' }
                : { value: x.approved ? 'OK' : 'VETO', cls: x.approved ? 'text-emerald-500' : 'text-red-500' };
            const risk = a.agent_03_risk;
            return [
                { name: '#1 Quant', ...sc(a.agent_01_quant) },
                { name: '#2 Micro', ...sc(a.agent_02_micro, 50) },
                { name: '#3 Risk', ...(risk ? { value: (risk.approved ? 'OK ' : 'VETO ') + (risk.score != null ? Number(risk.score).toFixed(0) : ''), cls: risk.approved ? 'text-emerald-500' : 'text-red-500' } : ap(risk)) },
                { name: '#4 Macro', ...sc(a.agent_04_macro, 50) },
                { name: '#5 CIO', value: a.agent_05_cio ? (a.agent_05_cio.decision + ' ' + (a.agent_05_cio.score ?? '')) : '—', cls: a.agent_05_cio?.decision === 'BUY' ? 'text-emerald-500' : 'text-zinc-300' },
                { name: '#6 Guardian', ...ap(a.agent_06_guardian) },
                { name: '#7 CHOP', value: a.agent_07_chop ? ((a.agent_07_chop.scouts || []).length + ' scout' + (a.agent_07_chop.latency_ms ? ' · ' + a.agent_07_chop.latency_ms.stage3 + 'ms' : '')) : '—', cls: 'text-zinc-300' },
            ];
        },

        // ---------- storico offline ----------
        openHistory() { this.showHistory = true; this.loadHistory(); },
        async loadHistory() {
            this.historyLoading = true;
            try {
                const res = await fetch('/api/history?offline=' + (this.historyOffline ? '1' : '0'));
                if (res.status === 401) { window.location.href = '/login'; return; }
                const data = await res.json().catch(() => ({}));
                this.historyRows = Array.isArray(data.executions) ? data.executions : [];
            } catch (e) {
                this.historyRows = [];
            } finally {
                this.historyLoading = false;
            }
        },
        historySummary() {
            const rows = this.historyRows;
            const pnl = rows.reduce((s, h) => s + (Number(h.realized_pnl) || 0), 0);
            return `${rows.length} operazioni${this.historyOffline ? ' eseguite in tua assenza' : ''} · PnL realizzato ${this.usd(pnl, true)}`;
        },
        rationaleText(h) {
            const r = h.rationale || {};
            const a = r.agents || r.agents_at_exit;
            const parts = [];
            if (a) parts.push(`Q ${a.agent_01_quant?.score ?? '—'} · M ${a.agent_02_micro?.score ?? '—'} · R ${a.agent_03_risk?.score ?? '—'} · Macro ${a.agent_04_macro?.score ?? '—'} · CIO ${a.agent_05_cio?.score ?? '—'}`
                + (a.agent_06_guardian?.approved != null ? ` · Guardian ${a.agent_06_guardian.approved ? 'OK' : 'VETO'}` : '')
                + (a.agent_07_chop?.scouts?.length ? ` · ${a.agent_07_chop.scouts.length} scout` : ''));
            if (r.desk_cio) parts.push(`convinzione ${r.desk_cio.conviction}: ${r.desk_cio.reason || ''}`);
            if (r.exit_reason) parts.push(r.exit_reason);
            return parts.join(' — ') || h.note || '—';
        },
        async liquidate() {
            if (!confirm('🚨 PANIC: annullare gli ordini, chiudere TUTTE le posizioni a mercato e mettere il bot in pausa?')) return;
            const { res, data } = await this.api('/api/liquidate');
            this.addLog(data.message || 'Liquidazione inviata', !res.ok);
            this.toast(data.message || 'Liquidazione inviata', !res.ok);
            this.fetchStatus();
        },
    };
}
