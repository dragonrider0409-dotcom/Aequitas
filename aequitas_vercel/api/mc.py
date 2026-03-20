import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from helpers import send_json, send_err, send_cors, read_body, get_qs
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self): send_cors(self)

    def do_GET(self):
        p = self.path
        try:
            if '/mc_quote' in p or '/quote' in p:
                import yfinance as yf, numpy as np
                ticker = (get_qs(self, 'ticker') or 'AAPL').upper()
                tkr    = yf.Ticker(ticker)
                hist   = tkr.history(period='1y', auto_adjust=True)
                info   = tkr.info or {}
                closes = hist['Close'].dropna()
                spot   = float(closes.iloc[-1])
                rets   = np.log(closes / closes.shift(1)).dropna().values
                ann_sigma = float(rets.std(ddof=1) * 252**0.5)
                ann_mu    = float(rets.mean() * 252)
                return send_json(self, {
                    'ticker':    ticker,
                    'spot':      round(spot, 4),
                    'ann_sigma': round(ann_sigma, 6),
                    'ann_mu':    round(ann_mu, 6),
                    'sigma':     round(ann_sigma, 6),
                    'mu':        round(ann_mu, 6),
                    'beta':      round(float(info.get('beta') or 1.0), 4),
                    'hi52':      round(float(closes.max()), 4),
                    'lo52':      round(float(closes.min()), 4),
                    'wk52_hi':   round(float(closes.max()), 4),
                    'wk52_lo':   round(float(closes.min()), 4),
                    'q':         round(float(info.get('dividendYield') or 0.0), 6),
                    'div_yield': round(float(info.get('dividendYield') or 0.0), 6),
                    'name':      info.get('longName') or ticker,
                })
            # status endpoint — always done (sync compute)
            send_json(self, {'status': 'done', 'progress': 'Complete'})
        except Exception as e:
            send_err(self, str(e))

    def do_POST(self):
        try:
            from engine_mc import SimConfig, run_full_suite
            p = read_body(self)
            cfg = SimConfig(
                S0=float(p.get('S0', 175)), mu=float(p.get('mu', 0.12)),
                sigma=float(p.get('sigma', 0.25)), r=float(p.get('r', 0.05)),
                q=float(p.get('q', 0.0)), T=float(p.get('T', 1.0)),
                n_sims=min(int(float(p.get('n_sims', 50000))), 50000),
                K=float(p.get('K', 180)), barrier=float(p.get('barrier', 140)),
                option_type=str(p.get('option_type', 'call')),
                investment=float(p.get('investment', 10000)),
                v0=float(p.get('v0', 0.04)), theta=float(p.get('theta', 0.04)),
                kappa=float(p.get('kappa', 2.0)), xi=float(p.get('xi', 0.3)),
                rho=float(p.get('rho', -0.7)), lam=float(p.get('lam', 0.75)),
                mu_j=float(p.get('mu_j', -0.05)), sig_j=float(p.get('sig_j', 0.10)),
                alpha=float(p.get('alpha', 0.25)), beta=float(p.get('beta', 0.5)),
                nu=float(p.get('nu', 0.4)), rho_s=float(p.get('rho_s', -0.3)),
            )
            result = run_full_suite(cfg)

            # ── Reshape result for frontend ──────────────────────────
            import numpy as np, math

            def safe(v):
                if v is None: return None
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
                return v

            opts = result.get('options', {})
            # Flatten option prices
            def price(x): return float(x['price']) if isinstance(x, dict) else float(x)
            def se(x):    return float(x.get('se', 0)) if isinstance(x, dict) else 0.0

            barrier_raw = opts.get('barrier', {})
            greeks_bs   = opts.get('greeks_bs', {})
            greeks_mc   = opts.get('greeks_mc', {})
            risk        = result.get('risk', {})

            def flatten_risk(r):
                if not r: return {}
                return {k: safe(float(v)) if isinstance(v,(int,float)) else v
                        for k,v in r.items()}

            # Sample paths for canvas (downsample heavily for JSON size)
            def sample_paths(arr, n_paths=50, n_steps=100):
                if arr is None: return []
                a = np.array(arr)
                if a.ndim < 2: return []
                step = max(1, a.shape[1]//n_steps)
                idx  = np.random.choice(a.shape[0], min(n_paths, a.shape[0]), replace=False)
                return np.round(a[idx, ::step], 4).tolist()

            shaped = {
                'ticker':    result.get('ticker', ''),
                'n_sims':    result.get('n_sims', cfg.n_sims),
                'elapsed_s': result.get('elapsed_s', 0),
                'options': {
                    'bs':           safe(price(opts.get('bs', 0))),
                    'eur_gbm':      safe(price(opts.get('eur_gbm', 0))),
                    'eur_gbm_se':   safe(se(opts.get('eur_gbm', 0))),
                    'eur_heston':   safe(price(opts.get('eur_heston', 0))),
                    'eur_jd':       safe(price(opts.get('eur_jd', 0))),
                    'eur_sabr':     safe(price(opts.get('eur_sabr', 0))),
                    'asian_arith':  safe(price(opts.get('asian_arith', 0))),
                    'asian_geo':    safe(price(opts.get('asian_geo', 0))),
                    'barrier':      safe(price(barrier_raw) if barrier_raw else 0),
                    'ko_pct':       safe(float(barrier_raw.get('knock_out_pct', 0)) if isinstance(barrier_raw, dict) else 0),
                    'lookback':     safe(price(opts.get('lookback', 0))),
                    'digital':      safe(price(opts.get('digital', 0))),
                },
                'greeks_bs': {k: safe(float(v)) for k,v in greeks_bs.items() if isinstance(v,(int,float))},
                'greeks_mc': {k: safe(float(v)) for k,v in greeks_mc.items() if isinstance(v,(int,float))},
                'risk': {
                    'gbm':    flatten_risk(risk.get('gbm', {})),
                    'heston': flatten_risk(risk.get('heston', {})),
                    'jd':     flatten_risk(risk.get('jd', {})),
                    'sabr':   flatten_risk(risk.get('sabr', {})),
                },
                'paths_gbm':    sample_paths(result.get('gbm_rw')),
                'paths_heston': sample_paths(result.get('heston_S')),
                'paths_jd':     sample_paths(result.get('jd_paths')),
                'paths_sabr':   sample_paths(result.get('sabr_paths')),
                'portfolio':    result.get('portfolio', {}),
                'stress':       result.get('stress', {}).to_dict('records') if hasattr(result.get('stress'), 'to_dict') else [],
                'convergence':  result.get('convergence', {}).to_dict('records') if hasattr(result.get('convergence'), 'to_dict') else [],
                'bs_price':     safe(price(opts.get('bs', 0))),
                'mc_mean':      safe(price(opts.get('eur_gbm', 0))),
                'var_95':       safe(float(risk.get('gbm', {}).get('VaR_95', 0))),
                'cvar_99':      safe(float(risk.get('gbm', {}).get('CVaR_99', 0))),
                'sharpe':       safe(float(risk.get('gbm', {}).get('sharpe', 0))),
                'p_loss':       safe(float(risk.get('gbm', {}).get('prob_loss', 0))),
            }
            send_json(self, {'job_id': 'sync', 'status': 'done', 'result': shaped})
        except Exception as e:
            import traceback
            send_err(self, str(e) + ' | ' + traceback.format_exc().splitlines()[-1])

    def log_message(self, *a): pass
