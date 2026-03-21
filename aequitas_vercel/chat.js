/**
 * AEQUITAS AI Chat Sidebar
 * Inject into any page with: <script src="/chat.js"></script>
 * Requires: window.AEQUITAS_CONTEXT = { ticker, spot, sigma, module, last_result }
 */
(function(){
'use strict';

const ACCENT   = '#00c8b0';
const DEV_KEYS = new Set(['DEV-AEQUITAS-MASTER-2025','DEV-AEQUITAS-SECONDARY-2025']);

// ── INJECT CSS ──────────────────────────────────────────────────────────
const css = `
#aeq-chat-btn{position:fixed;bottom:24px;right:24px;z-index:9000;
  width:48px;height:48px;border-radius:50%;background:${ACCENT};
  border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;
  box-shadow:0 4px 20px rgba(0,200,176,.3);transition:all .2s;font-size:1.2rem}
#aeq-chat-btn:hover{transform:scale(1.08);box-shadow:0 6px 28px rgba(0,200,176,.45)}
#aeq-chat-btn .badge{position:absolute;top:-3px;right:-3px;width:16px;height:16px;
  background:#f04060;border-radius:50%;font-size:.52rem;font-weight:700;
  color:#fff;display:flex;align-items:center;justify-content:center;display:none}

#aeq-chat-panel{position:fixed;bottom:84px;right:24px;z-index:9000;
  width:380px;height:560px;background:#060d1a;
  border:1px solid #102030;border-radius:6px;
  display:none;flex-direction:column;overflow:hidden;
  box-shadow:0 8px 40px rgba(0,0,0,.6);
  font-family:"DM Mono",monospace;font-size:12.5px}
#aeq-chat-panel.open{display:flex}

.aeq-chat-hdr{display:flex;align-items:center;justify-content:space-between;
  padding:11px 14px;background:#040810;border-bottom:1px solid #102030;flex-shrink:0}
.aeq-chat-hdr-left{display:flex;align-items:center;gap:8px}
.aeq-chat-dot{width:8px;height:8px;border-radius:50%;background:${ACCENT};
  animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.aeq-chat-title{font-family:"Syne",sans-serif;font-size:.72rem;font-weight:800;
  letter-spacing:.06em;color:#f0ede6}
.aeq-chat-sub{font-size:.55rem;color:#2a4060;letter-spacing:.06em}
.aeq-chat-close{background:none;border:none;color:#2a4060;cursor:pointer;
  font-size:.9rem;padding:2px 6px;transition:color .14s;line-height:1}
.aeq-chat-close:hover{color:#f04060}

.aeq-chat-setup{padding:16px;display:none;flex-direction:column;gap:10px;
  border-bottom:1px solid #102030;background:#040810;flex-shrink:0}
.aeq-chat-setup.show{display:flex}
.aeq-chat-setup label{font-size:.58rem;color:#2a4060;letter-spacing:.1em;text-transform:uppercase;margin-bottom:2px;display:block}
.aeq-chat-setup input{width:100%;background:#091220;border:1px solid #163040;
  color:${ACCENT};font-family:"DM Mono",monospace;font-size:.72rem;
  padding:7px 10px;border-radius:3px;outline:none;letter-spacing:.04em}
.aeq-chat-setup input:focus{border-color:${ACCENT}}
.aeq-chat-setup small{font-size:.58rem;color:#2a4060;line-height:1.5}
.aeq-setup-btn{background:${ACCENT};border:none;color:#040810;font-family:"DM Mono",monospace;
  font-size:.65rem;font-weight:700;padding:7px;border-radius:3px;cursor:pointer;
  letter-spacing:.08em;width:100%}

.aeq-msgs{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
.aeq-msgs::-webkit-scrollbar{width:3px}.aeq-msgs::-webkit-scrollbar-thumb{background:#163040}

.aeq-msg{display:flex;flex-direction:column;gap:3px;animation:msgIn .2s ease}
@keyframes msgIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.aeq-msg.user{align-items:flex-end}
.aeq-msg.ai{align-items:flex-start}
.aeq-bubble{max-width:88%;padding:9px 12px;border-radius:3px;line-height:1.55;font-size:.7rem;word-break:break-word}
.aeq-msg.user .aeq-bubble{background:#0c1a30;color:#b8cce0;border:1px solid #163040}
.aeq-msg.ai   .aeq-bubble{background:#040c1a;color:#b8cce0;border:1px solid #0d2030}
.aeq-bubble code{background:#091220;padding:1px 4px;border-radius:2px;font-size:.68rem;color:${ACCENT}}
.aeq-bubble pre{background:#040810;border:1px solid #102030;border-radius:3px;
  padding:8px 10px;margin:6px 0;overflow-x:auto;font-size:.65rem;color:#c8a96e;line-height:1.5}
.aeq-bubble strong{color:#f0ede6}
.aeq-role{font-size:.52rem;color:#2a4060;letter-spacing:.08em;padding:0 2px}

.aeq-typing{display:flex;align-items:center;gap:4px;padding:10px 12px}
.aeq-typing span{width:5px;height:5px;background:${ACCENT};border-radius:50%;
  animation:typing .9s ease-in-out infinite}
.aeq-typing span:nth-child(2){animation-delay:.15s}
.aeq-typing span:nth-child(3){animation-delay:.3s}
@keyframes typing{0%,80%,100%{opacity:.2;transform:scale(.8)}40%{opacity:1;transform:scale(1)}}

.aeq-suggestions{display:flex;flex-wrap:wrap;gap:4px;padding:0 14px 10px;flex-shrink:0}
.aeq-sug{background:#091220;border:1px solid #163040;color:#2a4060;
  font-family:"DM Mono",monospace;font-size:.58rem;padding:4px 8px;
  border-radius:2px;cursor:pointer;transition:all .14s;line-height:1.3;text-align:left}
.aeq-sug:hover{border-color:${ACCENT};color:${ACCENT}}

.aeq-input-row{display:flex;gap:6px;padding:10px 14px;border-top:1px solid #102030;flex-shrink:0}
.aeq-input{flex:1;background:#040810;border:1px solid #102030;color:#b8cce0;
  font-family:"DM Mono",monospace;font-size:.72rem;padding:8px 10px;
  border-radius:3px;outline:none;resize:none;line-height:1.5;min-height:36px;max-height:100px}
.aeq-input:focus{border-color:${ACCENT}}
.aeq-send{background:${ACCENT};border:none;color:#040810;border-radius:3px;
  width:36px;height:36px;cursor:pointer;font-size:.9rem;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;transition:all .14s}
.aeq-send:hover:not(:disabled){filter:brightness(1.15)}
.aeq-send:disabled{opacity:.4;cursor:not-allowed}
.aeq-tokens{font-size:.52rem;color:#1a3050;text-align:right;padding:3px 14px;flex-shrink:0}

.aeq-trade-block{margin:8px 0;background:#040c1a;border:1px solid #c8a96e30;
  border-radius:3px;overflow:hidden}
.aeq-trade-hdr{background:#0a150a;padding:7px 10px;font-size:.6rem;
  color:#c8a96e;letter-spacing:.1em;text-transform:uppercase;
  border-bottom:1px solid #c8a96e20}
.aeq-trade-body{padding:10px;font-size:.68rem}
.aeq-trade-field{display:flex;justify-content:space-between;padding:3px 0;
  border-bottom:1px solid #102030}
.aeq-trade-field:last-child{border-bottom:none}
.aeq-trade-field .tk{color:#2a4060}.aeq-trade-field .tv{color:#f0ede6;font-weight:600}
.aeq-trade-actions{display:flex;gap:6px;padding:10px}
.aeq-ibkr-btn{flex:1;background:#c8a96e;color:#040810;border:none;
  font-family:"DM Mono",monospace;font-size:.6rem;font-weight:700;
  padding:7px;border-radius:3px;cursor:pointer;letter-spacing:.06em;transition:all .14s}
.aeq-ibkr-btn:hover{filter:brightness(1.1)}
.aeq-ibkr-btn.paper{background:#091220;color:#2a4060;border:1px solid #163040}
.aeq-ibkr-btn.paper:hover{border-color:${ACCENT};color:${ACCENT}}
`;
const style = document.createElement('style');
style.textContent = css;
document.head.appendChild(style);

// ── INJECT HTML ────────────────────────────────────────────────────────
const btn = document.createElement('button');
btn.id = 'aeq-chat-btn';
btn.title = 'AEQUITAS AI';
btn.innerHTML = '◈<span class="badge" id="aeq-badge">1</span>';
document.body.appendChild(btn);

const panel = document.createElement('div');
panel.id = 'aeq-chat-panel';
panel.innerHTML = `
<div class="aeq-chat-hdr">
  <div class="aeq-chat-hdr-left">
    <div class="aeq-chat-dot"></div>
    <div>
      <div class="aeq-chat-title">AEQUITAS AI</div>
      <div class="aeq-chat-sub">Quant Analysis · Trade Generation</div>
    </div>
  </div>
  <button class="aeq-chat-close" onclick="aeqChat.toggle()">✕</button>
</div>

<div class="aeq-chat-setup" id="aeq-setup">
  <div>
    <label>Anthropic API Key</label>
    <input type="password" id="aeq-apikey" placeholder="sk-ant-..." autocomplete="off"/>
    <small>Your key is stored locally and never sent to our servers except to call Claude directly.</small>
  </div>
  <div>
    <label>Dev / Plan Key (optional)</label>
    <input type="text" id="aeq-plankey" placeholder="DEV-AEQUITAS-..." autocomplete="off"/>
    <small>Pro/Institutional plan key or developer key — bypasses API key requirement.</small>
  </div>
  <button class="aeq-setup-btn" onclick="aeqChat.saveSetup()">Save & Start Chatting →</button>
</div>

<div class="aeq-msgs" id="aeq-msgs"></div>

<div class="aeq-suggestions" id="aeq-sugs">
  <button class="aeq-sug" onclick="aeqChat.send('Analyse AAPL and give me a trade recommendation')">Analyse AAPL →</button>
  <button class="aeq-sug" onclick="aeqChat.send('What does the current volatility regime mean for my portfolio?')">Vol regime impact</button>
  <button class="aeq-sug" onclick="aeqChat.send('Generate an Interactive Brokers order for SPY with 2% portfolio risk')">Generate IBKR order</button>
  <button class="aeq-sug" onclick="aeqChat.send('Explain the Monte Carlo results in plain English')">Explain MC results</button>
</div>

<div class="aeq-input-row">
  <textarea class="aeq-input" id="aeq-input" placeholder="Ask anything… or request an IBKR trade" rows="1"></textarea>
  <button class="aeq-send" id="aeq-send" onclick="aeqChat.sendInput()">▶</button>
</div>
<div class="aeq-tokens" id="aeq-tokens"></div>
`;
document.body.appendChild(panel);

// ── CHAT LOGIC ─────────────────────────────────────────────────────────
window.aeqChat = {
  messages:    [],
  totalIn:     0,
  totalOut:    0,
  isOpen:      false,

  init(){
    const apiKey  = localStorage.getItem('aeq_openai_key') || '';
    const planKey = localStorage.getItem('aeq_plan_key') || '';
    const setup   = document.getElementById('aeq-setup');
    if(!apiKey && !DEV_KEYS.has(planKey)){
      setup.classList.add('show');
    }
    // Auto-fill from storage
    if(apiKey) document.getElementById('aeq-apikey').value = apiKey;
    if(planKey) document.getElementById('aeq-plankey').value = planKey;

    // Add welcome message
    if(this.messages.length === 0){
      this.addMsg('ai', "Hi — I'm the AEQUITAS AI. I can analyse stocks using our quant engines, explain any result in plain English, and generate Interactive Brokers orders backed by real quantitative analysis.\n\nWhat would you like to explore?");
    }

    // Input auto-resize
    const inp = document.getElementById('aeq-input');
    inp.addEventListener('keydown', e => {
      if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); this.sendInput(); }
    });
    inp.addEventListener('input', () => {
      inp.style.height = 'auto';
      inp.style.height = Math.min(inp.scrollHeight, 100) + 'px';
    });
  },

  toggle(){
    this.isOpen = !this.isOpen;
    panel.classList.toggle('open', this.isOpen);
    if(this.isOpen) document.getElementById('aeq-input').focus();
    document.getElementById('aeq-badge').style.display = 'none';
  },

  saveSetup(){
    const apiKey  = document.getElementById('aeq-apikey').value.trim();
    const planKey = document.getElementById('aeq-plankey').value.trim();
    if(apiKey)  localStorage.setItem('aeq_openai_key', apiKey);
    if(planKey) localStorage.setItem('aeq_plan_key', planKey);
    if(!apiKey && !DEV_KEYS.has(planKey)){
      alert('Please enter your Anthropic API key or a valid plan key.');
      return;
    }
    document.getElementById('aeq-setup').classList.remove('show');
    this.addMsg('ai', 'API key saved. Ready to analyse! Ask me anything about a stock, your portfolio, or request an IBKR trade.');
  },

  sendInput(){
    const inp = document.getElementById('aeq-input');
    const text = inp.value.trim();
    if(!text) return;
    inp.value = '';
    inp.style.height = 'auto';
    this.send(text);
  },

  async send(text){
    const apiKey  = localStorage.getItem('aeq_openai_key') || '';
    const planKey = localStorage.getItem('aeq_plan_key') || '';

    if(!apiKey && !DEV_KEYS.has(planKey)){
      document.getElementById('aeq-setup').classList.add('show');
      return;
    }

    // Hide suggestions after first real message
    document.getElementById('aeq-sugs').style.display = 'none';

    this.addMsg('user', text);
    this.messages.push({ role: 'user', content: text });
    this.setLoading(true);

    // Build context from current page state
    const ctx = {
      module:      document.title || '',
      ...(window.AEQUITAS_CONTEXT || {}),
    };

    try{
      const res = await fetch('/api/ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages:  this.messages,
          context:   ctx,
          api_key:   apiKey,
          user_key:  planKey,
        })
      });
      const data = await res.json();
      if(data.error) throw new Error(data.error);

      this.messages.push({ role: 'assistant', content: data.reply });
      this.totalIn  += data.input_tokens  || 0;
      this.totalOut += data.output_tokens || 0;

      // Check if the reply contains a trade order
      const tradeMatch = data.reply.match(/```json\s*(\{[\s\S]*?\})\s*```/);
      if(tradeMatch){
        try{
          const order = JSON.parse(tradeMatch[1]);
          if(order.action && order.ticker){
            this.addMsg('ai', data.reply.replace(/```json[\s\S]*?```/, ''));
            this.addTradeBlock(order);
            this.setLoading(false);
            this.updateTokens();
            return;
          }
        }catch(e){}
      }

      this.addMsg('ai', data.reply);
      this.updateTokens();

    }catch(e){
      this.addMsg('ai', '⚠ Error: ' + e.message + '\n\nCheck your API key in settings.');
    }finally{
      this.setLoading(false);
    }
  },

  addMsg(role, text){
    const msgs = document.getElementById('aeq-msgs');
    const div  = document.createElement('div');
    div.className = 'aeq-msg ' + role;
    const label = role === 'user' ? 'You' : 'AEQUITAS AI';
    const formatted = this.format(text);
    div.innerHTML = `<div class="aeq-role">${label}</div><div class="aeq-bubble">${formatted}</div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  },

  addTradeBlock(order){
    const msgs = document.getElementById('aeq-msgs');
    const fields = Object.entries(order)
      .map(([k,v]) => `<div class="aeq-trade-field"><span class="tk">${k}</span><span class="tv">${v}</span></div>`)
      .join('');
    const div = document.createElement('div');
    div.innerHTML = `
      <div class="aeq-trade-block">
        <div class="aeq-trade-hdr">◈ Interactive Brokers Order</div>
        <div class="aeq-trade-body">${fields}</div>
        <div class="aeq-trade-actions">
          <button class="aeq-ibkr-btn paper" onclick="aeqChat.copyOrder(${JSON.stringify(JSON.stringify(order))})">📋 Copy JSON</button>
          <button class="aeq-ibkr-btn" onclick="aeqChat.openIBKR(${JSON.stringify(JSON.stringify(order))})">Open in IBKR →</button>
        </div>
      </div>`;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  },

  copyOrder(orderStr){
    navigator.clipboard.writeText(orderStr).then(()=>{
      alert('Order JSON copied to clipboard. Paste into your IBKR TWS Order Entry panel.');
    });
  },

  openIBKR(orderStr){
    try{
      const o = JSON.parse(orderStr);
      // IBKR Universal URL scheme — opens TWS if installed
      const url = `ibkr://trade?action=${o.action}&ticker=${o.ticker}&qty=${o.qty||1}&orderType=${o.type||'MKT'}`;
      window.open(url, '_blank');
      alert('If IBKR TWS/app is installed, it should open with this order.\nOtherwise copy the JSON and enter manually.');
    }catch(e){
      alert('Copy the JSON and enter manually in IBKR TWS.');
    }
  },

  setLoading(on){
    const btn = document.getElementById('aeq-send');
    btn.disabled = on;
    const msgs = document.getElementById('aeq-msgs');
    const existing = msgs.querySelector('.aeq-typing');
    if(on && !existing){
      const t = document.createElement('div');
      t.className = 'aeq-typing';
      t.innerHTML = '<span></span><span></span><span></span>';
      msgs.appendChild(t);
      msgs.scrollTop = msgs.scrollHeight;
    } else if(!on && existing){
      existing.remove();
    }
  },

  updateTokens(){
    const el = document.getElementById('aeq-tokens');
    if(el) el.textContent = `${(this.totalIn+this.totalOut).toLocaleString()} tokens used this session`;
  },

  format(text){
    return text
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/```json([\s\S]*?)```/g, '<pre>$1</pre>')
      .replace(/```([\s\S]*?)```/g, '<pre>$1</pre>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
  }
};

btn.addEventListener('click', () => aeqChat.toggle());
document.addEventListener('DOMContentLoaded', () => aeqChat.init());
if(document.readyState !== 'loading') aeqChat.init();

})();
