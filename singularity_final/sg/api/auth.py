"""
Singularity Auth + Payments API  v1.1
──────────────────────────────────────────────────────────────────────────────
Endpoints:
  POST /api/auth/signup          → create user in Supabase
  POST /api/auth/signin          → verify credentials, return token
  POST /api/auth/me              → get current user + plan from token
  POST /api/auth/checkout        → create Stripe checkout session
  POST /api/auth/webhook         → Stripe webhook → update plan in Supabase
  POST /api/auth/forgot-password → send password reset email (Supabase Auth)
  POST /api/auth/reset-password  → apply new password from reset token
  POST /api/auth/verify-status   → check email verification status

Setup (one-time):
  1. Create a free Supabase project at supabase.com
     → Get SUPABASE_URL and SUPABASE_SERVICE_KEY from Settings → API
  2. Create a free Stripe account at stripe.com
     → Get STRIPE_SECRET_KEY from Developers → API keys
     → Get STRIPE_WEBHOOK_SECRET from Developers → Webhooks
  3. Add these as Vercel environment variables:
       SUPABASE_URL            = https://xxxx.supabase.co
       SUPABASE_SERVICE_KEY    = eyJ...  (service_role key, NOT anon)
       STRIPE_SECRET_KEY       = sk_live_...  (or sk_test_ for testing)
       STRIPE_WEBHOOK_SECRET   = whsec_...
       STRIPE_PRO_PRICE_ID     = price_... (from Stripe Dashboard)
       STRIPE_INST_PRICE_ID    = price_... (from Stripe Dashboard)

Supabase SQL (run once in SQL editor):
  create table users (
    id          uuid primary key default gen_random_uuid(),
    email       text unique not null,
    name        text not null,
    password    text not null,  -- bcrypt hash
    plan        text not null default 'free',
    stripe_id   text,
    created_at  timestamptz default now()
  );

  create table training_data (
    user_id        uuid references users(id) on delete cascade,
    total_trades   bigint default 0,
    total_patterns bigint default 0,
    sessions       bigint default 0,
    patterns       jsonb  default '[]',
    stats          jsonb  default '{}',
    updated_at     timestamptz default now(),
    primary key (user_id)
  );
"""

import os, json, hashlib, hmac, time
from http.server import BaseHTTPRequestHandler
from helpers import send_json, send_err, send_cors, read_body

# ── ENV (set in Vercel dashboard) ────────────────────────────────────────────
SUPABASE_URL        = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY        = os.environ.get('SUPABASE_SERVICE_KEY', '')
STRIPE_SECRET       = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_WEBHOOK_SEC  = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRO_PRICE    = os.environ.get('STRIPE_PRO_PRICE_ID', '')
STRIPE_INST_PRICE   = os.environ.get('STRIPE_INST_PRICE_ID', '')
APP_URL             = os.environ.get('APP_URL', 'https://your-app.vercel.app')

# ── SUPABASE HELPERS ─────────────────────────────────────────────────────────

def sb_headers():
    return {
        'apikey':        SUPABASE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_KEY,
        'Content-Type':  'application/json',
        'Prefer':        'return=representation',
    }

def sb_get(table, eq_col, eq_val):
    import urllib.request
    url = f"{SUPABASE_URL}/rest/v1/{table}?{eq_col}=eq.{urllib.parse.quote(str(eq_val))}&limit=1"
    req = urllib.request.Request(url, headers=sb_headers())
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            rows = json.loads(r.read())
            return rows[0] if rows else None
    except Exception:
        return None

def sb_post(table, data):
    import urllib.request, urllib.parse
    url  = f"{SUPABASE_URL}/rest/v1/{table}"
    body = json.dumps(data).encode()
    req  = urllib.request.Request(url, data=body, headers=sb_headers(), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            rows = json.loads(r.read())
            return rows[0] if rows else data
    except Exception as e:
        raise RuntimeError(f'Supabase insert failed: {e}')

def sb_patch(table, eq_col, eq_val, data):
    import urllib.request, urllib.parse
    url  = f"{SUPABASE_URL}/rest/v1/{table}?{eq_col}=eq.{urllib.parse.quote(str(eq_val))}"
    body = json.dumps(data).encode()
    req  = urllib.request.Request(url, data=body, headers=sb_headers(), method='PATCH')
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return None

# ── PASSWORD HASHING (no bcrypt dep — use PBKDF2 from stdlib) ───────────────

def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    h    = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000)
    return salt + ':' + h.hex()

def verify_password(password: str, stored: str) -> bool:
    try:
        salt, h = stored.split(':', 1)
        check = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000)
        return hmac.compare_digest(check.hex(), h)
    except Exception:
        return False

# ── SESSION TOKEN (HMAC-signed, no JWT dep) ──────────────────────────────────

TOKEN_SECRET = os.environ.get('TOKEN_SECRET', 'sg_default_secret_change_me_in_vercel')

def make_token(user_id: str, email: str, plan: str) -> str:
    payload  = json.dumps({'uid': user_id, 'email': email, 'plan': plan, 'ts': int(time.time())})
    sig      = hmac.new(TOKEN_SECRET.encode(), payload.encode(), 'sha256').hexdigest()
    import base64
    return base64.b64encode((payload + '.' + sig).encode()).decode()

def verify_token(token: str) -> dict | None:
    try:
        import base64
        raw     = base64.b64decode(token.encode()).decode()
        payload, sig = raw.rsplit('.', 1)
        expected = hmac.new(TOKEN_SECRET.encode(), payload.encode(), 'sha256').hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload)
        if time.time() - data['ts'] > 30 * 24 * 3600:   # 30-day expiry
            return None
        return data
    except Exception:
        return None

# ── STRIPE HELPERS ───────────────────────────────────────────────────────────

def stripe_request(method, path, data=None):
    import urllib.request, urllib.parse, base64
    url  = 'https://api.stripe.com/v1' + path
    auth = base64.b64encode((STRIPE_SECRET + ':').encode()).decode()
    headers = {'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded'}
    body = urllib.parse.urlencode(data).encode() if data else None
    req  = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read())

# ── REQUEST HANDLER ──────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self): send_cors(self)

    def do_POST(self):
        p = self.path

        # ── SIGN UP ──────────────────────────────────────────────────────────
        if '/signup' in p:
            try:
                b     = read_body(self)
                email = b.get('email', '').strip().lower()
                name  = b.get('name',  '').strip()
                pw    = b.get('password', '')
                plan  = b.get('plan', 'free')

                if not email or '@' not in email:
                    return send_err(self, 'Invalid email address', 400)
                if len(pw) < 8:
                    return send_err(self, 'Password must be at least 8 characters', 400)
                if not name:
                    return send_err(self, 'Name is required', 400)
                if plan not in ('free', 'pro', 'institutional'):
                    plan = 'free'

                # Check if email already exists
                existing = sb_get('users', 'email', email)
                if existing:
                    return send_err(self, 'An account with this email already exists', 409)

                # Create user
                user = sb_post('users', {
                    'email':    email,
                    'name':     name,
                    'password': hash_password(pw),
                    'plan':     'free',   # always start free; Stripe upgrades plan
                })

                # Create empty training data record
                try:
                    sb_post('training_data', {
                        'user_id':       user['id'],
                        'total_trades':  0,
                        'total_patterns': 0,
                        'sessions':      0,
                        'patterns':      [],
                        'stats':         {},
                    })
                except Exception:
                    pass   # non-critical

                token = make_token(user['id'], email, 'free')
                return send_json(self, {
                    'token': token,
                    'user':  {'id': user['id'], 'email': email, 'name': name, 'plan': 'free'},
                })
            except RuntimeError as e:
                return send_err(self, str(e), 500)
            except Exception as e:
                return send_err(self, f'Signup failed: {e}', 500)

        # ── SIGN IN ──────────────────────────────────────────────────────────
        elif '/signin' in p:
            try:
                b     = read_body(self)
                email = b.get('email', '').strip().lower()
                pw    = b.get('password', '')

                if not email or not pw:
                    return send_err(self, 'Email and password required', 400)

                user = sb_get('users', 'email', email)
                if not user or not verify_password(pw, user.get('password', '')):
                    return send_err(self, 'Invalid email or password', 401)

                token = make_token(user['id'], email, user.get('plan', 'free'))
                return send_json(self, {
                    'token': token,
                    'user':  {'id': user['id'], 'email': email,
                              'name': user.get('name', ''), 'plan': user.get('plan', 'free')},
                })
            except Exception as e:
                return send_err(self, f'Signin failed: {e}', 500)

        # ── GET CURRENT USER (token verify) ──────────────────────────────────
        elif '/me' in p:
            try:
                b     = read_body(self)
                token = b.get('token', '')
                data  = verify_token(token)
                if not data:
                    return send_err(self, 'Invalid or expired token', 401)

                # Refresh plan from DB (in case it changed via Stripe)
                user = sb_get('users', 'id', data['uid'])
                if not user:
                    return send_err(self, 'User not found', 404)

                # Also pull training data
                td = sb_get('training_data', 'user_id', data['uid'])

                return send_json(self, {
                    'user': {
                        'id':    user['id'],
                        'email': user['email'],
                        'name':  user.get('name', ''),
                        'plan':  user.get('plan', 'free'),
                    },
                    'training': {
                        'total_trades':   td.get('total_trades', 0)   if td else 0,
                        'total_patterns': td.get('total_patterns', 0) if td else 0,
                        'sessions':       td.get('sessions', 0)        if td else 0,
                        'patterns':       td.get('patterns', [])       if td else [],
                        'stats':          td.get('stats', {})          if td else {},
                    } if td else None,
                })
            except Exception as e:
                return send_err(self, f'Token verify failed: {e}', 500)

        # ── SAVE TRAINING DATA TO DB ─────────────────────────────────────────
        elif '/training/save' in p:
            try:
                b     = read_body(self)
                token = b.get('token', '')
                data  = verify_token(token)
                if not data:
                    return send_err(self, 'Invalid token', 401)

                # Keep patterns array capped at 2000 most recent (JSON size limit)
                patterns = b.get('patterns', [])[-2000:]

                sb_patch('training_data', 'user_id', data['uid'], {
                    'total_trades':   int(b.get('total_trades', 0)),
                    'total_patterns': int(b.get('total_patterns', 0)),
                    'sessions':       int(b.get('sessions', 0)),
                    'patterns':       patterns,
                    'stats':          b.get('stats', {}),
                    'updated_at':     'now()',
                })
                return send_json(self, {'saved': True})
            except Exception as e:
                return send_err(self, f'Save failed: {e}', 500)

        # ── LOAD TRAINING DATA FROM DB ────────────────────────────────────────
        elif '/training/load' in p:
            try:
                b     = read_body(self)
                token = b.get('token', '')
                data  = verify_token(token)
                if not data:
                    return send_err(self, 'Invalid token', 401)

                td = sb_get('training_data', 'user_id', data['uid'])
                if not td:
                    return send_json(self, {'found': False})
                return send_json(self, {
                    'found':          True,
                    'total_trades':   td.get('total_trades', 0),
                    'total_patterns': td.get('total_patterns', 0),
                    'sessions':       td.get('sessions', 0),
                    'patterns':       td.get('patterns', []),
                    'stats':          td.get('stats', {}),
                    'updated_at':     td.get('updated_at', ''),
                })
            except Exception as e:
                return send_err(self, f'Load failed: {e}', 500)

        # ── STRIPE CHECKOUT SESSION ───────────────────────────────────────────
        elif '/checkout' in p:
            try:
                if not STRIPE_SECRET:
                    return send_err(self, 'Stripe not configured. Add STRIPE_SECRET_KEY to Vercel env vars.', 503)
                b     = read_body(self)
                token = b.get('token', '')
                plan  = b.get('plan', 'pro')
                data  = verify_token(token)
                if not data:
                    return send_err(self, 'Invalid token', 401)

                price_id = STRIPE_PRO_PRICE if plan == 'pro' else STRIPE_INST_PRICE
                if not price_id:
                    return send_err(self, f'Stripe price ID for {plan} not configured', 503)

                user = sb_get('users', 'id', data['uid'])

                session = stripe_request('POST', '/checkout/sessions', {
                    'mode':                 'subscription',
                    'line_items[0][price]': price_id,
                    'line_items[0][quantity]': '1',
                    'customer_email':       data['email'],
                    'success_url':          APP_URL + '/hub?upgraded=1',
                    'cancel_url':           APP_URL + '/',
                    'metadata[user_id]':    data['uid'],
                    'metadata[plan]':       plan,
                    'client_reference_id':  data['uid'],
                })
                return send_json(self, {'checkout_url': session['url']})
            except Exception as e:
                return send_err(self, f'Checkout failed: {e}', 500)

        # ── STRIPE WEBHOOK (plan activation) ────────────────────────────────
        elif '/webhook' in p:
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                raw_body    = self.rfile.read(content_len)
                sig_header  = self.headers.get('Stripe-Signature', '')

                # Verify webhook signature
                if STRIPE_WEBHOOK_SEC:
                    try:
                        ts_part  = [p for p in sig_header.split(',') if p.startswith('t=')][0][2:]
                        v1_part  = [p for p in sig_header.split(',') if p.startswith('v1=')][0][3:]
                        signed   = ts_part + '.' + raw_body.decode()
                        expected = hmac.new(STRIPE_WEBHOOK_SEC.encode(), signed.encode(), 'sha256').hexdigest()
                        if not hmac.compare_digest(expected, v1_part):
                            return send_err(self, 'Invalid webhook signature', 400)
                        if abs(time.time() - int(ts_part)) > 300:
                            return send_err(self, 'Webhook timestamp too old', 400)
                    except Exception:
                        return send_err(self, 'Webhook signature verification failed', 400)

                event = json.loads(raw_body)
                etype = event.get('type', '')

                if etype in ('checkout.session.completed', 'invoice.payment_succeeded'):
                    obj     = event['data']['object']
                    uid     = obj.get('metadata', {}).get('user_id') or obj.get('client_reference_id')
                    plan    = obj.get('metadata', {}).get('plan', 'pro')
                    cus_id  = obj.get('customer', '')
                    if uid and plan in ('pro', 'institutional'):
                        sb_patch('users', 'id', uid, {'plan': plan, 'stripe_id': cus_id})

                elif etype in ('customer.subscription.deleted', 'customer.subscription.paused'):
                    cus_id = event['data']['object'].get('customer', '')
                    if cus_id:
                        user = sb_get('users', 'stripe_id', cus_id)
                        if user:
                            sb_patch('users', 'id', user['id'], {'plan': 'free'})

                return send_json(self, {'received': True})
            except Exception as e:
                return send_err(self, f'Webhook error: {e}', 500)

        # ── FORGOT PASSWORD (send reset email via Supabase Auth) ─────────────
        elif '/forgot-password' in p:
            try:
                b     = read_body(self)
                email = b.get('email', '').strip().lower()
                if not email or '@' not in email:
                    return send_err(self, 'Valid email required', 400)

                # Supabase Auth: trigger password recovery email
                # This uses the Supabase Auth /recover endpoint which sends
                # a magic-link reset email to the user automatically.
                import urllib.request, urllib.parse
                reset_url = f"{SUPABASE_URL}/auth/v1/recover"
                payload   = json.dumps({'email': email}).encode()
                req = urllib.request.Request(reset_url, data=payload, method='POST',
                    headers={
                        'apikey':        SUPABASE_KEY,
                        'Content-Type':  'application/json',
                    })
                try:
                    with urllib.request.urlopen(req, timeout=8) as r:
                        pass  # 200 = email queued, no body needed
                except Exception:
                    pass   # Supabase returns 200 even for unknown emails (anti-enum)

                # Always return success to prevent email enumeration
                return send_json(self, {
                    'ok':      True,
                    'message': 'If an account exists for that email, a reset link has been sent.',
                })
            except Exception as e:
                return send_err(self, f'Password reset request failed: {e}', 500)

        # ── RESET PASSWORD (exchange OTP token → set new password) ───────────
        elif '/reset-password' in p:
            try:
                b           = read_body(self)
                access_token = b.get('access_token', '').strip()
                new_password = b.get('password', '').strip()

                if not access_token:
                    return send_err(self, 'Access token required', 400)
                if len(new_password) < 8:
                    return send_err(self, 'Password must be at least 8 characters', 400)

                import urllib.request
                # Use Supabase Auth user update endpoint with the reset access_token
                update_url = f"{SUPABASE_URL}/auth/v1/user"
                payload    = json.dumps({'password': new_password}).encode()
                req = urllib.request.Request(update_url, data=payload, method='PUT',
                    headers={
                        'apikey':        SUPABASE_KEY,
                        'Authorization': f'Bearer {access_token}',
                        'Content-Type':  'application/json',
                    })
                try:
                    with urllib.request.urlopen(req, timeout=8) as r:
                        user_data = json.loads(r.read())
                except urllib.error.HTTPError as e:
                    body = e.read().decode()
                    return send_err(self, f'Reset failed: {body}', 400)

                uid   = user_data.get('id')
                email = user_data.get('email', '')

                # Also update bcrypt hash in our users table for /signin compat
                if uid:
                    new_hash = hash_password(new_password)
                    sb_patch('users', 'id', uid, {'password': new_hash})

                return send_json(self, {
                    'ok':      True,
                    'message': 'Password updated successfully. You can now sign in.',
                    'email':   email,
                })
            except Exception as e:
                return send_err(self, f'Password reset failed: {e}', 500)

        # ── VERIFY EMAIL (Supabase handles link; this checks status) ─────────
        elif '/verify-status' in p:
            try:
                b     = read_body(self)
                token = b.get('token', '').strip()
                if not token:
                    return send_err(self, 'Token required', 400)

                data = verify_token(token)
                if not data:
                    return send_err(self, 'Invalid or expired token', 401)

                user = sb_get('users', 'id', data['uid'])
                if not user:
                    return send_err(self, 'User not found', 404)

                # Supabase Auth: check confirmed_at field
                import urllib.request
                auth_url = f"{SUPABASE_URL}/auth/v1/admin/users/{data['uid']}"
                req = urllib.request.Request(auth_url,
                    headers={
                        'apikey':        SUPABASE_KEY,
                        'Authorization': f'Bearer {SUPABASE_KEY}',
                    })
                verified = False
                try:
                    with urllib.request.urlopen(req, timeout=8) as r:
                        auth_user = json.loads(r.read())
                        verified  = bool(auth_user.get('email_confirmed_at'))
                except Exception:
                    pass

                return send_json(self, {
                    'email':    user['email'],
                    'verified': verified,
                    'plan':     user.get('plan', 'free'),
                })
            except Exception as e:
                return send_err(self, f'Verify status failed: {e}', 500)

        else:
            return send_err(self, 'Unknown auth endpoint', 404)

    def log_message(self, *a): pass
