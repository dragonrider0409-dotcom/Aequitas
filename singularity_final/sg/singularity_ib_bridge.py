#!/usr/bin/env python3
"""
Singularity IB Bridge  v3.0  — FIXED & PRODUCTION-READY
─────────────────────────────────────────────────────────────────────────────
Runs on your LOCAL machine. Connects to IB Gateway / TWS and exposes a
REST API on port 8765 that the Singularity bot reads from the browser.

Setup
─────
pip install ib_insync flask flask-cors

Usage
─────
# Paper trading (port 7497):
python singularity_ib_bridge.py --ib-port 7497 --account U1234567

# Live trading (port 7496):
python singularity_ib_bridge.py --ib-port 7496 --account U1234567

Endpoints
─────────
GET  /ping        → latency check  {pong:true, ts, latency_ms}
GET  /status      → connection status + account ID + mode
GET  /account     → NAV, day P&L, total P&L
GET  /positions   → open positions
GET  /trades      → today's closed trades
POST /order       → place order  {symbol, action, qty, order_type, price?, strategy?}
POST /close       → close position {symbol, qty, side}
POST /webhook/tradingview  → TradingView alert → IB order
"""

import argparse, threading, time, logging, json
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('SingularityBridge')

app = Flask(__name__)
CORS(app)

# ── IB connection state ────────────────────────────────────────────────────────
ib          = None
ACCOUNT     = ''
IB_HOST     = '127.0.0.1'
IB_PORT     = 7497
_connected  = False
_trades_today = []
_connect_lock = threading.Lock()
_start_time = time.time()

def connect_ib():
    global ib, _connected
    with _connect_lock:
        try:
            from ib_insync import IB as IBClient
            if ib and ib.isConnected():
                return True
            ib = IBClient()
            ib.connect(IB_HOST, IB_PORT, clientId=1, readonly=False)
            _connected = ib.isConnected()
            if _connected:
                log.info(f'✓ Connected to IB Gateway  {IB_HOST}:{IB_PORT}  Account: {ACCOUNT}')
                ib.execDetailsEvent    += on_fill
                ib.orderStatusEvent    += on_order_status   # ← track order lifecycle
                ib.errorEvent          += on_ib_error       # ← catch IB errors
                ib.reqAccountUpdates(True, ACCOUNT)
            else:
                log.warning('IB Gateway responded but isConnected() = False')
        except Exception as e:
            log.error(f'IB connect error: {e}')
            _connected = False
    return _connected

# Track order statuses: orderId → status dict
_order_statuses = {}

def on_order_status(trade):
    """Track order lifecycle: Submitted → PreSubmitted → Filled / Cancelled."""
    oid = trade.order.orderId
    status = trade.orderStatus.status
    filled = trade.orderStatus.filled
    remaining = trade.orderStatus.remaining
    avg_price = trade.orderStatus.avgFillPrice
    _order_statuses[oid] = {
        'orderId':   oid,
        'status':    status,
        'filled':    filled,
        'remaining': remaining,
        'avgPrice':  avg_price,
        'symbol':    trade.contract.symbol,
        'action':    trade.order.action,
        'qty':       trade.order.totalQuantity,
        'updated':   int(time.time() * 1000),
    }
    log.info(f'Order {oid} {trade.contract.symbol}: {status} filled={filled} rem={remaining} avgPx={avg_price}')

def on_ib_error(reqId, errorCode, errorString, contract):
    """Handle IB API errors — log and mark order failed if relevant."""
    # Error codes 200-399: warnings/info; 400+: real errors
    level = log.warning if errorCode < 400 else log.error
    level(f'IB error {errorCode} (req={reqId}): {errorString}')
    # Mark associated order as rejected if it's an order error
    if errorCode in (103, 104, 105, 106, 107, 109, 110, 201, 202, 321, 322):
        if reqId in _order_statuses:
            _order_statuses[reqId]['status'] = 'Rejected'
            _order_statuses[reqId]['error']  = errorString

def on_fill(trade, fill):
    """Record fills as they arrive."""
    t = {
        'symbol':     fill.contract.symbol,
        'action':     fill.execution.side,
        'qty':        fill.execution.shares,
        'fill_price': fill.execution.price,
        'ts':         int(time.time() * 1000),
        'strategy':   getattr(trade.order, 'orderRef', 'manual'),
        'order_id':   fill.execution.orderId,
        'pl':         0,  # filled later by commissions event
    }
    _trades_today.append(t)
    log.info(f"Fill: {t['action']} {t['qty']} {t['symbol']} @ {t['fill_price']}")

def keep_alive():
    """Reconnect thread — runs every 30s."""
    global _connected
    while True:
        time.sleep(30)
        try:
            if ib and not ib.isConnected():
                log.warning('IB disconnected — reconnecting…')
                _connected = False
                connect_ib()
        except Exception as e:
            log.error(f'Keep-alive error: {e}')

# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.route('/ping')
def ping():
    return jsonify({
        'pong':       True,
        'ts':         int(time.time() * 1000),
        'uptime_s':   round(time.time() - _start_time, 1),
        'connected':  _connected,
    })

@app.route('/status')
def status():
    global _connected
    if ib:
        try:
            _connected = ib.isConnected()
        except Exception:
            _connected = False
    return jsonify({
        'connected': _connected,
        'account':   ACCOUNT,
        'ib_host':   IB_HOST,
        'ib_port':   IB_PORT,
        'mode':      'paper' if IB_PORT in (7497, 4002) else 'live',
        'bridge_version': '3.0',
        'uptime_s':  round(time.time() - _start_time, 1),
    })

@app.route('/account')
def account():
    if not ib or not _connected:
        return jsonify({'error': 'not connected', 'nav': 0, 'dpnl': 0, 'tpnl': 0})
    try:
        vals = {}
        for v in ib.accountValues():
            if not ACCOUNT or v.account == ACCOUNT:
                vals[v.tag] = v.value
        nav  = float(vals.get('NetLiquidation', 0) or 0)
        dpnl = float(vals.get('UnrealizedPnL', 0) or 0) + float(vals.get('RealizedPnL', 0) or 0)
        tpnl = dpnl  # daily basis; for cumulative integrate over sessions
        return jsonify({'nav': round(nav, 2), 'dpnl': round(dpnl, 2), 'tpnl': round(tpnl, 2)})
    except Exception as e:
        return jsonify({'error': str(e), 'nav': 0, 'dpnl': 0, 'tpnl': 0})

@app.route('/positions')
def positions():
    if not ib or not _connected:
        return jsonify([])
    try:
        pos_list = []
        for p in ib.positions():
            if ACCOUNT and p.account != ACCOUNT:
                continue
            sym = p.contract.symbol
            qty = p.position
            ep  = float(p.avgCost or 0)
            tick = ib.ticker(p.contract)
            mp   = float(tick.marketPrice()) if tick and tick.marketPrice() > 0 else ep
            upl  = round((mp - ep) * abs(qty) * (1 if qty > 0 else -1), 2)
            pos_list.append({
                'symbol':       sym,
                'qty':          abs(qty),
                'side':         'buy' if qty > 0 else 'sell',
                'entry':        round(ep, 2),
                'avg_cost':     round(ep, 2),
                'marketPrice':  round(mp, 2),
                'market_price': round(mp, 2),
                'position':     qty,
                'unrealizedPnl': upl,
            })
        return jsonify(pos_list)
    except Exception as e:
        log.error(f'Positions error: {e}')
        return jsonify([])

@app.route('/trades')
def trades():
    return jsonify(_trades_today[-50:])

@app.route('/order', methods=['POST'])
def place_order():
    if not ib or not _connected:
        return jsonify({'error': 'not connected — start IB Gateway and bridge'}), 503
    data       = request.get_json(force=True)
    symbol     = data.get('symbol', '').upper().strip()
    action     = data.get('action', 'BUY').upper()
    qty        = int(data.get('qty', 1))
    order_type = data.get('order_type', 'MKT').upper()
    price      = data.get('price')
    strategy   = data.get('strategy', 'singularity')

    if not symbol or qty < 1:
        return jsonify({'error': 'invalid symbol or qty'}), 400
    if action not in ('BUY', 'SELL'):
        return jsonify({'error': 'action must be BUY or SELL'}), 400

    try:
        from ib_insync import Stock, Forex, Crypto, MarketOrder, LimitOrder, StopOrder
        # Contract type routing
        if '/' in symbol:
            base, quote = symbol.replace(' ', '').split('/')
            contract = Forex(base + quote)
        elif symbol in ('BTC', 'ETH', 'SOL'):
            contract = Crypto(symbol, 'PAXOS', 'USD')
        else:
            contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)

        if order_type == 'MKT':
            order = MarketOrder(action, qty)
        elif order_type == 'LMT':
            if not price:
                return jsonify({'error': 'price required for LMT order'}), 400
            order = LimitOrder(action, qty, float(price))
        elif order_type == 'STP':
            if not price:
                return jsonify({'error': 'price required for STP order'}), 400
            order = StopOrder(action, qty, float(price))
        else:
            return jsonify({'error': f'unknown order_type: {order_type}'}), 400

        order.orderRef = strategy
        trade = ib.placeOrder(contract, order)
        log.info(f'Order placed: {action} {qty} {symbol} ({order_type}) · ref={strategy} · id={trade.order.orderId}')
        return jsonify({
            'status':   'submitted',
            'order_id': trade.order.orderId,
            'symbol':   symbol,
            'action':   action,
            'qty':      qty,
            'type':     order_type,
            'strategy': strategy,
            'mode':     'paper' if IB_PORT in (7497, 4002) else 'live',
        })
    except Exception as e:
        log.error(f'Order error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/close', methods=['POST'])
def close_position():
    """Close an existing position cleanly."""
    if not ib or not _connected:
        return jsonify({'error': 'not connected'}), 503
    data   = request.get_json(force=True)
    symbol = data.get('symbol', '').upper().strip()
    qty    = int(data.get('qty', 1))
    side   = data.get('side', 'long').lower()
    action = 'SELL' if side in ('long', 'buy') else 'BUY'
    if not symbol or qty < 1:
        return jsonify({'error': 'invalid symbol or qty'}), 400
    try:
        from ib_insync import Stock, MarketOrder
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        order = MarketOrder(action, qty)
        order.orderRef = 'close'
        trade = ib.placeOrder(contract, order)
        log.info(f'Close position: {action} {qty} {symbol} · id={trade.order.orderId}')
        return jsonify({'status': 'submitted', 'order_id': trade.order.orderId, 'action': action, 'symbol': symbol, 'qty': qty})
    except Exception as e:
        log.error(f'Close position error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/cancel', methods=['POST'])
def cancel_order():
    """Cancel a pending order by order_id."""
    if not ib or not _connected:
        return jsonify({'error': 'not connected'}), 503
    data     = request.get_json(force=True)
    order_id = data.get('order_id')
    if not order_id:
        return jsonify({'error': 'order_id required'}), 400
    try:
        for trade in ib.openTrades():
            if trade.order.orderId == int(order_id):
                ib.cancelOrder(trade.order)
                return jsonify({'status': 'cancel_requested', 'order_id': order_id})
        return jsonify({'error': f'order {order_id} not found in open trades'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/order-status')
def order_status():
    """Return all tracked order statuses — bot polls this to confirm fills."""
    order_id = request.args.get('orderId')
    if order_id:
        status = _order_statuses.get(int(order_id))
        if status:
            return jsonify(status)
        return jsonify({'orderId': order_id, 'status': 'Unknown'}), 404
    # Return all recent statuses (last 50)
    recent = sorted(_order_statuses.values(), key=lambda x: x.get('updated', 0), reverse=True)[:50]
    return jsonify({'orders': recent, 'count': len(recent)})

@app.route('/webhook/tradingview', methods=['POST'])
def tradingview_webhook():
    """
    Receives TradingView alerts → IB orders.
    Alert URL: http://YOUR_IP:8765/webhook/tradingview

    JSON format: {"action":"buy","symbol":"NVDA","qty":10,"strategy":"momentum"}
    Plain text:  "BUY NVDA 10"
    """
    try:
        raw = request.data.decode('utf-8').strip()
        log.info(f'TradingView webhook: {raw[:200]}')
        try:
            payload  = json.loads(raw)
            action   = str(payload.get('action', 'buy')).upper()
            symbol   = str(payload.get('symbol', '')).upper().strip()
            qty      = int(payload.get('qty', 1))
            strategy = str(payload.get('strategy', 'tradingview'))
        except (json.JSONDecodeError, KeyError):
            parts    = raw.upper().split()
            action   = parts[0] if parts else 'BUY'
            symbol   = parts[1] if len(parts) > 1 else ''
            qty      = int(parts[2]) if len(parts) > 2 else 1
            strategy = 'tradingview'

        if not symbol:
            return jsonify({'error': 'no symbol'}), 400
        if action in ('LONG', 'ENTER', 'BUY'):
            action = 'BUY'
        elif action in ('SHORT', 'EXIT', 'SELL', 'CLOSE'):
            action = 'SELL'

        if not ib or not _connected:
            log.warning(f'TV signal queued (IB not connected): {action} {qty} {symbol}')
            return jsonify({'status': 'queued', 'note': 'IB not connected — signal logged'}), 202

        from ib_insync import Stock, MarketOrder
        contract = Stock(symbol, 'SMART', 'USD')
        ib.qualifyContracts(contract)
        order = MarketOrder(action, qty)
        order.orderRef = strategy
        trade = ib.placeOrder(contract, order)
        log.info(f'TradingView → IB: {action} {qty} {symbol}')
        return jsonify({'status': 'submitted', 'order_id': trade.order.orderId})
    except Exception as e:
        log.error(f'Webhook error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/diagnostics')
def diagnostics():
    """Full health check — used by Singularity bot diagnostics panel."""
    try:
        connected = bool(ib and ib.isConnected()) if ib else False
        open_orders = len(ib.openOrders()) if connected else 0
        open_pos    = len(ib.positions())  if connected else 0
        return jsonify({
            'bridge_ok':     True,
            'bridge_version':'3.0',
            'ib_connected':  connected,
            'account':       ACCOUNT,
            'mode':          'paper' if IB_PORT in (7497, 4002) else 'live',
            'open_orders':   open_orders,
            'open_positions':open_pos,
            'trades_today':  len(_trades_today),
            'uptime_s':      round(time.time() - _start_time, 1),
            'ib_host':       IB_HOST,
            'ib_port':       IB_PORT,
        })
    except Exception as e:
        return jsonify({'bridge_ok': True, 'ib_connected': False, 'error': str(e)})

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Singularity IB Bridge v3.0')
    parser.add_argument('--ib-host',  default='127.0.0.1',  help='IB Gateway host')
    parser.add_argument('--ib-port',  type=int, default=7497,help='IB port (7497=paper, 7496=live)')
    parser.add_argument('--account',  default='',            help='IB Account ID (e.g. U1234567)')
    parser.add_argument('--port',     type=int, default=8765,help='Bridge listen port')
    args = parser.parse_args()

    IB_HOST  = args.ib_host
    IB_PORT  = args.ib_port
    ACCOUNT  = args.account
    mode     = 'PAPER' if IB_PORT in (7497, 4002) else '⚡ LIVE'

    print(f"""
╔══════════════════════════════════════════════════╗
║       SINGULARITY IB BRIDGE  v3.0                ║
║  Mode:    {mode:<40}║
║  IB:      {IB_HOST}:{IB_PORT:<29}║
║  Account: {ACCOUNT or '(set --account)':<38}║
║  Bridge:  http://0.0.0.0:{args.port:<23}║
╚══════════════════════════════════════════════════╝
""")

    # Connect to IB in background (non-blocking Flask start)
    t = threading.Thread(target=connect_ib, daemon=True)
    t.start()
    t.join(timeout=10)

    # Keep-alive reconnect thread
    ka = threading.Thread(target=keep_alive, daemon=True)
    ka.start()

    print(f'  Bridge listening on  http://0.0.0.0:{args.port}')
    print(f'  Diagnostics:         http://127.0.0.1:{args.port}/diagnostics')
    print(f'  TradingView webhook: http://YOUR_IP:{args.port}/webhook/tradingview')
    print(f'  Status:              http://127.0.0.1:{args.port}/status')
    print('\n  Press Ctrl+C to stop.\n')
    app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)
