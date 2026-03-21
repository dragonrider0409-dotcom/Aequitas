"""
api/ai.py — AEQUITAS AI Assistant
Handles all AI chat, trade generation, and quant analysis requests.
Powered by Claude claude-sonnet-4-20250514 via Anthropic API.
"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from helpers import send_json, send_err, send_cors, read_body
from http.server import BaseHTTPRequestHandler

# ── DEV KEYS (bypass all auth + metering) ───────────────────────────────
DEV_KEYS = {
    "DEV-AEQUITAS-MASTER-2025",   # primary dev key
    "DEV-AEQUITAS-SECONDARY-2025", # second dev key for team
}

SYSTEM_PROMPT = """You are the AEQUITAS AI — an institutional-grade quantitative finance assistant embedded in the AEQUITAS platform.

You have access to eight production quant engines:
1. Monte Carlo Suite — GBM, Heston, Jump-Diffusion, SABR; options pricing, VaR, CVaR, stress testing
2. IV Surface — SABR Hagan (2002), Heston CF exact pricing, live options chain calibration
3. Portfolio Optimizer — Markowitz, Black-Litterman, Risk Parity (ERC), Min-CVaR (Rockafellar-Uryasev)
4. Fixed Income — Nelson-Siegel, Svensson, zero bootstrap, swap DV01, live Treasury rates
5. Pairs Trading — Engle-Granger, Johansen multivariate cointegration, OU process, backtesting
6. Vol & Regime — GARCH(1,1), GJR-GARCH, HAR-RV, Baum-Welch HMM, Kalman filter
7. Alpha & Execution — Fama-French 3-factor, PCA, alpha decay, Almgren-Chriss optimal execution
8. Credit Risk — Merton structural model, CDS par spread, CVA, Gaussian copula portfolio MC

When asked for a stock recommendation:
- State clearly this is NOT financial advice
- Use our quant methodology to frame the analysis
- Reference specific metrics (Sharpe ratio, VaR, distance-to-default etc)
- Give a structured recommendation: thesis, entry, risk, exit

When asked to generate an Interactive Brokers trade:
- Produce a precise JSON order block
- Include risk management (stop loss, position size as % of portfolio)
- Flag any model-based concerns (high vol regime, poor liquidity etc)
- Always recommend paper trading first

Keep responses concise and data-driven. Use quant terminology correctly.
When you don't know current prices, say so and suggest the user runs the relevant engine.
Never fabricate specific numbers you don't have access to.
Format trade orders as valid JSON in a code block."""

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self): send_cors(self)

    def do_POST(self):
        try:
            b       = read_body(self)
            messages = b.get('messages', [])
            context  = b.get('context', {})   # current ticker, last sim result, etc.
            api_key  = b.get('api_key', '')    # Anthropic API key from user/plan
            user_key = b.get('user_key', '')   # AEQUITAS plan key or dev key

            # ── Validate access ───────────────────────────────────────
            is_dev = user_key in DEV_KEYS
            if not api_key and not is_dev:
                return send_err(self, 'API key required. Add your Anthropic API key in settings.', 403)

            if not messages:
                return send_err(self, 'No messages provided', 400)

            # ── Build system prompt with live context ─────────────────
            sys_prompt = SYSTEM_PROMPT
            if context:
                ctx_parts = []
                if context.get('ticker'):
                    ctx_parts.append(f"Current ticker: {context['ticker']}")
                if context.get('spot'):
                    ctx_parts.append(f"Current price: ${context['spot']:.2f}")
                if context.get('sigma'):
                    ctx_parts.append(f"Annualised vol: {context['sigma']*100:.1f}%")
                if context.get('module'):
                    ctx_parts.append(f"Active module: {context['module']}")
                if context.get('last_result'):
                    # Summarise last simulation result
                    r = context['last_result']
                    if r.get('sharpe'):
                        ctx_parts.append(f"Last MC result — Sharpe: {r['sharpe']:.3f}, VaR95: ${abs(r.get('var_95',0)):.0f}, P(loss): {r.get('p_loss',0)*100:.1f}%")
                if ctx_parts:
                    sys_prompt += '\n\nCURRENT SESSION CONTEXT:\n' + '\n'.join(ctx_parts)

            # ── Call Claude API ───────────────────────────────────────
            import urllib.request
            payload = json.dumps({
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 1024,
                'system': sys_prompt,
                'messages': messages[-20:],  # last 20 messages for context
            }).encode()

            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=payload,
                headers={
                    'x-api-key':         api_key,
                    'anthropic-version': '2023-06-01',
                    'content-type':      'application/json',
                },
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())

            text = result['content'][0]['text'] if result.get('content') else ''
            usage = result.get('usage', {})

            send_json(self, {
                'reply':        text,
                'model':        result.get('model', ''),
                'input_tokens': usage.get('input_tokens', 0),
                'output_tokens':usage.get('output_tokens', 0),
                'is_dev':       is_dev,
            })

        except Exception as e:
            import traceback
            send_err(self, str(e))

    def log_message(self, *a): pass
