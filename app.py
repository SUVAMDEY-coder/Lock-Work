"""
LockWork — Managed Freelance Escrow Platform
Pure Python stdlib — zero dependencies, runs anywhere
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import sqlite3, uuid, datetime, hashlib, os, base64, threading, json, urllib.parse, mimetypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.environ.get('DB_PATH', os.path.join(BASE_DIR, 'lockwork.db'))
SESSIONS = {}
db_local = threading.local()

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
def get_db():
    if not hasattr(db_local, 'conn'):
        db_local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        db_local.conn.row_factory = sqlite3.Row
    return db_local.conn

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL, role TEXT DEFAULT 'client',
            balance REAL DEFAULT 10000.0, bio TEXT DEFAULT '',
            skills TEXT DEFAULT '', id_verified INTEGER DEFAULT 0,
            skill_score INTEGER DEFAULT 0, completion_rate REAL DEFAULT 0.0,
            reliability_score REAL DEFAULT 0.0, premium INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '',
            client_id TEXT NOT NULL, client_name TEXT NOT NULL,
            freelancer_email TEXT, freelancer_id TEXT, freelancer_name TEXT,
            freelancer_accepted INTEGER DEFAULT 0, deadline TEXT,
            total REAL DEFAULT 0, released REAL DEFAULT 0,
            commission_rate REAL DEFAULT 0.10,
            completion_guarantee INTEGER DEFAULT 0, guarantee_fee REAL DEFAULT 0,
            status TEXT DEFAULT 'open', dispute_status TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS milestones (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
            amount REAL NOT NULL, status TEXT DEFAULT 'pending',
            submitted_at TEXT, approved_at TEXT, deadline TEXT,
            sort_order INTEGER DEFAULT 0, submission_note TEXT,
            file_name TEXT, file_data TEXT, file_type TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            sender_id TEXT NOT NULL, sender_name TEXT NOT NULL,
            content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS disputes (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            raised_by TEXT NOT NULL, reason TEXT NOT NULL,
            status TEXT DEFAULT 'open', resolution TEXT,
            created_at TEXT NOT NULL, resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS contracts (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
            terms TEXT NOT NULL, signed_client INTEGER DEFAULT 0,
            signed_freelancer INTEGER DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activity (
            id TEXT PRIMARY KEY, time TEXT NOT NULL, text TEXT NOT NULL,
            project_id TEXT, user_id TEXT
        );
        CREATE TABLE IF NOT EXISTS skill_tests (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, skill TEXT NOT NULL,
            score INTEGER NOT NULL, passed INTEGER DEFAULT 0, taken_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL, text TEXT NOT NULL,
            link TEXT, read INTEGER DEFAULT 0, created_at TEXT NOT NULL
        );
    ''')
    conn.commit()
    conn.close()

def now():        return datetime.datetime.now().isoformat()
def gen_id():     return str(uuid.uuid4())[:8].upper()
def hash_pass(p): return hashlib.sha256(p.encode()).hexdigest()
def r2d(row):     return dict(row) if row else None

def log_activity(text, project_id=None, user_id=None):
    db = get_db()
    db.execute('INSERT INTO activity VALUES (?,?,?,?,?)', (gen_id(), now(), text, project_id, user_id))
    db.commit()

def notify(user_id, text, link=None):
    db = get_db()
    db.execute('INSERT INTO notifications VALUES (?,?,?,?,?,?)', (gen_id(), user_id, text, link, 0, now()))
    db.commit()

def get_project_full(pid):
    db = get_db()
    p = r2d(db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone())
    if not p: return None
    ms = db.execute('SELECT * FROM milestones WHERE project_id=? ORDER BY sort_order', (pid,)).fetchall()
    p['milestones'] = [{k: v for k, v in r2d(m).items() if k != 'file_data'} for m in ms]
    p['freelancer_accepted'] = bool(p['freelancer_accepted'])
    p['contract'] = r2d(db.execute('SELECT * FROM contracts WHERE project_id=?', (pid,)).fetchone())
    return p

def calc_reliability(uid):
    db = get_db()
    total     = db.execute("SELECT COUNT(*) FROM projects WHERE freelancer_id=? AND status IN ('complete','cancelled')", (uid,)).fetchone()[0]
    completed = db.execute("SELECT COUNT(*) FROM projects WHERE freelancer_id=? AND status='complete'", (uid,)).fetchone()[0]
    rate = round(completed / total * 100, 1) if total else 0.0
    db.execute('UPDATE users SET completion_rate=?, reliability_score=? WHERE id=?', (rate, rate, uid))
    db.commit()

def hydrate(rows):
    db = get_db()
    out = []
    for row in rows:
        p = r2d(row)
        ms = db.execute('SELECT * FROM milestones WHERE project_id=? ORDER BY sort_order', (p['id'],)).fetchall()
        p['milestones'] = [{k: v for k, v in r2d(m).items() if k != 'file_data'} for m in ms]
        p['freelancer_accepted'] = bool(p['freelancer_accepted'])
        out.append(p)
    return out

def make_contract(pid, title, client, freelancer, total, milestones, guarantee):
    lines  = '\n'.join(f"  {i+1}. {m['title']} — ${float(m['amount']):.2f}" for i, m in enumerate(milestones))
    g_line = '7. Completion Guarantee: Client eligible for refund or free replacement.' if guarantee else ''
    return f"""SERVICE AGREEMENT
CONTRACT ID: {pid}   DATE: {now()[:10]}
CLIENT: {client}   FREELANCER: {freelancer}
PROJECT: {title}

MILESTONES:
{lines}

TOTAL: ${total:.2f}  |  PLATFORM FEE: 10%  |  GUARANTEE: {'YES' if guarantee else 'NO'}

TERMS:
1. Funds held in escrow until milestone approval.
2. Payment released per approved milestone only.
3. IP transfers to client upon full payment.
4. Freelancer inactive 14+ days triggers auto-replacement.
5. Disputes mediated by platform within 48h.
6. Freelancer forfeits payment if work not delivered.
{g_line}

Client: {client} [SIGNED]   Freelancer: {freelancer} [PENDING]
"""

# ─────────────────────────────────────────────
# HTTP HANDLER
# ─────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command} {self.path} {args[1]}")

    def get_sid(self):
        for part in self.headers.get('Cookie', '').split(';'):
            p = part.strip()
            if p.startswith('session='): return p[8:]
        return None

    def get_user(self):
        sid = self.get_sid()
        if not sid: return None
        uid = SESSIONS.get(sid)
        if not uid: return None
        return r2d(get_db().execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())

    def new_session(self, uid):
        sid = str(uuid.uuid4())
        SESSIONS[sid] = uid
        return sid

    def del_session(self):
        sid = self.get_sid()
        if sid: SESSIONS.pop(sid, None)

    def send_json(self, data, status=200, cookie=None):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        if cookie: self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, ctype, disposition=None, status=200):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(body))
        if disposition: self.send_header('Content-Disposition', disposition)
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        n = int(self.headers.get('Content-Length', 0))
        if n:
            try: return json.loads(self.rfile.read(n))
            except: return {}
        return {}

    def serve_file(self, rel):
        full = os.path.join(BASE_DIR, rel.lstrip('/'))
        if not os.path.isfile(full):
            self.send_json({'error': 'Not found'}, 404); return
        ct, _ = mimetypes.guess_type(full)
        with open(full, 'rb') as f:
            self.send_bytes(f.read(), ct or 'application/octet-stream')

    # ─────────── GET ─────────────────────────
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path   = parsed.path
        qs     = urllib.parse.parse_qs(parsed.query)
        u      = self.get_user()

        # Static files
        if path in ('/', '/index.html'):
            self.serve_file('templates/index.html'); return
        if path.startswith('/static/'):
            self.serve_file(path); return

        # API
        if path == '/api/me':
            if u: self.send_json({'ok': True, 'user': {k: v for k, v in u.items() if k != 'password'}})
            else:  self.send_json({'ok': False})

        elif path == '/api/balance':
            if not u: self.send_json({'balance': 0}); return
            row = get_db().execute('SELECT balance FROM users WHERE id=?', (u['id'],)).fetchone()
            self.send_json({'balance': row['balance'] if row else 0})

        elif path == '/api/stats':
            db = get_db()
            self.send_json({
                'projects':    db.execute("SELECT COUNT(*) FROM projects WHERE status IN ('active','open','pending')").fetchone()[0],
                'escrow':      db.execute("SELECT COALESCE(SUM(total),0) FROM projects WHERE status NOT IN ('complete','cancelled')").fetchone()[0],
                'completed':   db.execute("SELECT COUNT(*) FROM milestones WHERE status='complete'").fetchone()[0],
                'freelancers': db.execute("SELECT COUNT(*) FROM users WHERE role='freelancer'").fetchone()[0],
            })

        elif path == '/api/projects/mine':
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            db = get_db()
            rows = db.execute('SELECT * FROM projects WHERE client_id=? ORDER BY created_at DESC', (u['id'],)).fetchall() \
                if u['role'] == 'client' else \
                db.execute('SELECT * FROM projects WHERE freelancer_id=? ORDER BY created_at DESC', (u['id'],)).fetchall()
            self.send_json({'ok': True, 'projects': hydrate(rows)})

        elif path == '/api/projects/all':
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            db = get_db()
            rows = db.execute('SELECT * FROM projects WHERE client_id=? ORDER BY created_at DESC', (u['id'],)).fetchall() \
                if u['role'] == 'client' else \
                db.execute("SELECT * FROM projects WHERE status IN ('open','pending','active') ORDER BY created_at DESC").fetchall()
            self.send_json({'ok': True, 'projects': hydrate(rows)})

        elif path.startswith('/api/projects/') and path.endswith('/contract'):
            pid = path.split('/')[3]
            p   = get_project_full(pid)
            if not p: self.send_json({'error': 'Not found'}, 404); return
            text = (p['contract']['terms'] if p.get('contract') else 'No contract.').encode()
            self.send_bytes(text, 'text/plain', f'attachment; filename="contract-{pid}.txt"')

        elif path.startswith('/api/projects/') and '/messages' in path and len(path.split('/')) == 5:
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            pid  = path.split('/')[3]
            rows = get_db().execute('SELECT * FROM messages WHERE project_id=? ORDER BY created_at ASC', (pid,)).fetchall()
            self.send_json({'ok': True, 'messages': [r2d(r) for r in rows]})

        elif path.startswith('/api/projects/') and len(path.split('/')) == 4:
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            pid = path.split('/')[3]
            p   = get_project_full(pid)
            self.send_json({'ok': True, 'project': p} if p else {'ok': False, 'error': 'Not found'})

        elif path.startswith('/api/milestones/') and path.endswith('/file'):
            mid = path.split('/')[3]
            ms  = r2d(get_db().execute('SELECT file_data,file_name,file_type FROM milestones WHERE id=?', (mid,)).fetchone())
            if not ms or not ms.get('file_data'): self.send_json({'error': 'Not found'}, 404); return
            self.send_bytes(base64.b64decode(ms['file_data']),
                ms.get('file_type','application/octet-stream'),
                f'attachment; filename="{ms.get("file_name","file")}"')

        elif path == '/api/activity':
            if not u: self.send_json({'logs': []}); return
            db  = get_db()
            pf  = qs.get('project', [None])[0]
            if pf:
                rows = db.execute('SELECT * FROM activity WHERE project_id=? ORDER BY time DESC LIMIT 30', (pf,)).fetchall()
            elif u['role'] == 'client':
                rows = db.execute('''SELECT a.* FROM activity a LEFT JOIN projects p ON a.project_id=p.id
                    WHERE p.client_id=? OR a.project_id IS NULL ORDER BY a.time DESC LIMIT 30''', (u['id'],)).fetchall()
            else:
                rows = db.execute('''SELECT a.* FROM activity a LEFT JOIN projects p ON a.project_id=p.id
                    WHERE p.freelancer_id=? OR a.project_id IS NULL ORDER BY a.time DESC LIMIT 30''', (u['id'],)).fetchall()
            self.send_json({'logs': [r2d(r) for r in rows]})

        elif path == '/api/notifications':
            if not u: self.send_json({'notifications': []}); return
            rows = get_db().execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20', (u['id'],)).fetchall()
            self.send_json({'notifications': [r2d(r) for r in rows]})

        elif path == '/api/freelancers':
            db   = get_db()
            rows = db.execute('''SELECT id,name,email,bio,skills,id_verified,skill_score,
                completion_rate,reliability_score,premium,created_at
                FROM users WHERE role="freelancer" ORDER BY reliability_score DESC''').fetchall()
            out  = []
            for row in rows:
                f = r2d(row)
                f['projects_completed'] = db.execute(
                    "SELECT COUNT(*) FROM projects WHERE freelancer_id=? AND status='complete'", (f['id'],)).fetchone()[0]
                out.append(f)
            self.send_json({'ok': True, 'freelancers': out})

        elif path.startswith('/api/freelancers/'):
            fid = path.split('/')[3]
            db  = get_db()
            f   = r2d(db.execute('''SELECT id,name,email,bio,skills,id_verified,skill_score,
                completion_rate,reliability_score,premium,created_at
                FROM users WHERE id=? AND role="freelancer"''', (fid,)).fetchone())
            if not f: self.send_json({'ok': False, 'error': 'Not found'}); return
            f['projects_completed'] = db.execute(
                "SELECT COUNT(*) FROM projects WHERE freelancer_id=? AND status='complete'", (fid,)).fetchone()[0]
            self.send_json({'ok': True, 'freelancer': f})

        else:
            self.send_json({'error': 'Not found'}, 404)

    # ─────────── POST ────────────────────────
    def do_POST(self):
        path = self.path
        d    = self.read_body()
        u    = self.get_user()

        # AUTH
        if path == '/api/register':
            if not all([d.get('name'), d.get('email'), d.get('password')]):
                self.send_json({'ok': False, 'error': 'All fields required'}); return
            db = get_db()
            if db.execute('SELECT id FROM users WHERE email=?', (d['email'].lower().strip(),)).fetchone():
                self.send_json({'ok': False, 'error': 'Email already registered'}); return
            uid = gen_id()
            db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (uid, d['name'].strip(), d['email'].lower().strip(), hash_pass(d['password']),
                 d.get('role','client'), 10000.0, '', '', 0, 0, 0.0, 0.0, 0, now()))
            db.commit()
            sid = self.new_session(uid)
            log_activity(f"New user: {d['name']} ({d.get('role','client')})")
            uu = r2d(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
            self.send_json({'ok': True, 'user': {k: v for k, v in uu.items() if k != 'password'}},
                cookie=f'session={sid}; Path=/; SameSite=Lax')

        elif path == '/api/login':
            db = get_db()
            uu = r2d(db.execute('SELECT * FROM users WHERE email=?', (d.get('email','').lower().strip(),)).fetchone())
            if not uu or uu['password'] != hash_pass(d.get('password','')):
                self.send_json({'ok': False, 'error': 'Invalid email or password'}); return
            sid = self.new_session(uu['id'])
            self.send_json({'ok': True, 'user': {k: v for k, v in uu.items() if k != 'password'}},
                cookie=f'session={sid}; Path=/; SameSite=Lax')

        elif path == '/api/logout':
            self.del_session()
            self.send_json({'ok': True}, cookie='session=; Path=/; Max-Age=0')

        # PROFILE
        elif path == '/api/profile':
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            db    = get_db()
            email = d.get('email', u['email']).lower().strip()
            if email != u['email'] and db.execute('SELECT id FROM users WHERE email=? AND id!=?', (email, u['id'])).fetchone():
                self.send_json({'ok': False, 'error': 'Email already in use'}); return
            db.execute('UPDATE users SET name=?, email=?, bio=?, skills=? WHERE id=?',
                (d.get('name', u['name']), email,
                 d.get('bio', u.get('bio','')), d.get('skills', u.get('skills','')), u['id']))
            db.commit()
            uu = r2d(db.execute('SELECT * FROM users WHERE id=?', (u['id'],)).fetchone())
            self.send_json({'ok': True, 'user': {k: v for k, v in uu.items() if k != 'password'}})

        elif path == '/api/password':
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            if u['password'] != hash_pass(d.get('current_password','')):
                self.send_json({'ok': False, 'error': 'Current password incorrect'}); return
            if len(d.get('new_password','')) < 6:
                self.send_json({'ok': False, 'error': 'Password must be at least 6 characters'}); return
            db = get_db()
            db.execute('UPDATE users SET password=? WHERE id=?', (hash_pass(d['new_password']), u['id']))
            db.commit()
            self.send_json({'ok': True})

        elif path == '/api/topup':
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            amount = float(d.get('amount', 0))
            if amount <= 0: self.send_json({'ok': False, 'error': 'Invalid amount'}); return
            db = get_db()
            db.execute('UPDATE users SET balance=balance+? WHERE id=?', (amount, u['id']))
            db.commit()
            bal = db.execute('SELECT balance FROM users WHERE id=?', (u['id'],)).fetchone()['balance']
            log_activity(f"{u['name']} added ${amount:.2f}", user_id=u['id'])
            self.send_json({'ok': True, 'balance': bal})

        # VERIFICATION
        elif path == '/api/verify-id':
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            if not d.get('doc_data'): self.send_json({'ok': False, 'error': 'Document required'}); return
            db = get_db()
            db.execute('UPDATE users SET id_verified=1 WHERE id=?', (u['id'],))
            db.commit()
            notify(u['id'], '✅ Your ID has been verified!', '/dashboard')
            self.send_json({'ok': True, 'message': 'ID verified'})

        elif path == '/api/skill-test':
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            skill   = d.get('skill','')
            answers = d.get('answers', [])
            score   = sum(10 for a in answers if a and a.get('correct'))
            passed  = score >= 70
            db = get_db()
            db.execute('INSERT INTO skill_tests VALUES (?,?,?,?,?,?)',
                (gen_id(), u['id'], skill, score, 1 if passed else 0, now()))
            if passed:
                skills = [s.strip() for s in (u.get('skills') or '').split(',') if s.strip()]
                if skill not in skills: skills.append(skill)
                db.execute('UPDATE users SET skills=?, skill_score=skill_score+? WHERE id=?',
                    (','.join(skills), score, u['id']))
            db.commit()
            self.send_json({'ok': True, 'score': score, 'passed': passed,
                'message': 'Passed! Skill added to profile.' if passed else 'Score below 70. Try again after 24 hours.'})

        # PROJECTS
        elif path == '/api/projects':
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            if not d.get('title') or not d.get('milestones'):
                self.send_json({'ok': False, 'error': 'Title and milestones required'}); return
            base      = sum(float(ms['amount']) for ms in d['milestones'])
            guarantee = bool(d.get('completion_guarantee'))
            gfee      = base * 0.05 if guarantee else 0
            charge    = base + base * 0.10 + gfee
            db        = get_db()
            bal       = db.execute('SELECT balance FROM users WHERE id=?', (u['id'],)).fetchone()['balance']
            if charge > bal:
                self.send_json({'ok': False, 'error': f'Insufficient balance. Need ${charge:.2f} (inc. fees), have ${bal:.2f}'}); return
            db.execute('UPDATE users SET balance=balance-? WHERE id=?', (charge, u['id']))
            pid    = gen_id()
            fe     = (d.get('freelancer_email') or '').lower().strip() or None
            fl     = r2d(db.execute('SELECT * FROM users WHERE email=?', (fe,)).fetchone()) if fe else None
            status = 'pending' if fe else 'open'
            db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (pid, d['title'], d.get('description',''), u['id'], u['name'],
                 fe, fl['id'] if fl else None, fl['name'] if fl else None,
                 0, d.get('deadline'), base, 0.0, 0.10,
                 1 if guarantee else 0, gfee, status, None, now()))
            for i, ms in enumerate(d['milestones']):
                db.execute('INSERT INTO milestones VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (gen_id(), pid, ms['title'], float(ms['amount']), 'pending',
                     None, None, ms.get('deadline'), i, None, None, None, None))
            terms = make_contract(pid, d['title'], u['name'], fl['name'] if fl else 'TBD', base, d['milestones'], guarantee)
            db.execute('INSERT INTO contracts VALUES (?,?,?,?,?,?)', (gen_id(), pid, terms, 1, 0, now()))
            db.commit()
            if fl: notify(fl['id'], f"📋 Project invitation: {d['title']}", f'/project/{pid}')
            log_activity(f"Project '{d['title']}' posted — ${base:.2f} in escrow", pid, u['id'])
            self.send_json({'ok': True, 'project': get_project_full(pid)})

        elif path.endswith('/accept') and '/projects/' in path:
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            pid = path.split('/')[3]
            p   = get_project_full(pid)
            if not p: self.send_json({'ok': False, 'error': 'Not found'}); return
            if p.get('freelancer_id') and p['freelancer_id'] != u['id']:
                self.send_json({'ok': False, 'error': 'Assigned to another freelancer'}); return
            db = get_db()
            db.execute('UPDATE projects SET freelancer_accepted=1, status=?, freelancer_id=?, freelancer_name=?, freelancer_email=? WHERE id=?',
                ('active', u['id'], u['name'], u['email'], pid))
            db.execute('UPDATE contracts SET signed_freelancer=1 WHERE project_id=?', (pid,))
            db.commit()
            notify(p['client_id'], f"✅ {u['name']} accepted '{p['title']}'", f'/project/{pid}')
            log_activity(f"{u['name']} accepted '{p['title']}'", pid, u['id'])
            self.send_json({'ok': True, 'project': get_project_full(pid)})

        elif path.endswith('/cancel') and '/projects/' in path:
            pid = path.split('/')[3]
            p   = get_project_full(pid)
            if not p: self.send_json({'ok': False, 'error': 'Not found'}); return
            db  = get_db()
            rem = float(p['total']) - float(p['released'])
            db.execute('UPDATE projects SET status=? WHERE id=?', ('cancelled', pid))
            db.execute('UPDATE users SET balance=balance+? WHERE id=?', (rem, p['client_id']))
            db.commit()
            log_activity(f"Project '{p['title']}' cancelled — ${rem:.2f} returned", pid, u['id'] if u else None)
            self.send_json({'ok': True})

        # MILESTONES
        elif '/milestones/' in path and path.endswith('/submit'):
            parts    = path.split('/')
            pid, mid = parts[3], parts[5]
            db       = get_db()
            db.execute("""UPDATE milestones SET status='submitted', submitted_at=?,
                submission_note=?, file_name=?, file_data=?, file_type=?
                WHERE id=? AND project_id=?""",
                (now(), d.get('note'), d.get('file_name'), d.get('file_data'), d.get('file_type'), mid, pid))
            db.commit()
            ms = r2d(db.execute('SELECT title FROM milestones WHERE id=?', (mid,)).fetchone())
            p  = get_project_full(pid)
            if p: notify(p['client_id'], f"📎 Work submitted for '{ms['title'] if ms else mid}'", f'/project/{pid}')
            log_activity(f"{u['name'] if u else 'Freelancer'} submitted '{ms['title'] if ms else mid}'", pid, u['id'] if u else None)
            self.send_json({'ok': True})

        elif '/milestones/' in path and path.endswith('/approve'):
            parts    = path.split('/')
            pid, mid = parts[3], parts[5]
            db       = get_db()
            ms       = r2d(db.execute('SELECT * FROM milestones WHERE id=?', (mid,)).fetchone())
            if not ms: self.send_json({'ok': False, 'error': 'Not found'}); return
            db.execute("UPDATE milestones SET status='complete', approved_at=? WHERE id=?", (now(), mid))
            db.execute('UPDATE projects SET released=released+? WHERE id=?', (ms['amount'], pid))
            p = get_project_full(pid)
            if p and p.get('freelancer_id'):
                payout = float(ms['amount']) * 0.90
                db.execute('UPDATE users SET balance=balance+? WHERE id=?', (payout, p['freelancer_id']))
                notify(p['freelancer_id'], f"💰 ${payout:.2f} released for '{ms['title']}'", f'/project/{pid}')
                calc_reliability(p['freelancer_id'])
            if p and all(m['status'] == 'complete' for m in p['milestones']):
                db.execute("UPDATE projects SET status='complete' WHERE id=?", (pid,))
                log_activity(f"🎉 Project '{p['title']}' completed!", pid)
            db.commit()
            log_activity(f"{u['name'] if u else 'Client'} approved '{ms['title']}' — ${float(ms['amount']):.2f} released", pid, u['id'] if u else None)
            self.send_json({'ok': True})

        elif '/milestones/' in path and path.endswith('/reject'):
            parts    = path.split('/')
            pid, mid = parts[3], parts[5]
            db       = get_db()
            ms       = r2d(db.execute('SELECT title FROM milestones WHERE id=?', (mid,)).fetchone())
            db.execute("UPDATE milestones SET status='pending', submitted_at=NULL, submission_note=NULL, file_name=NULL, file_data=NULL WHERE id=?", (mid,))
            db.commit()
            p = get_project_full(pid)
            if p and p.get('freelancer_id'):
                notify(p['freelancer_id'], f"🔄 Revision requested on '{ms['title'] if ms else mid}'", f'/project/{pid}')
            log_activity(f"{u['name'] if u else 'Client'} requested revisions on '{ms['title'] if ms else mid}'", pid, u['id'] if u else None)
            self.send_json({'ok': True})

        # MESSAGES
        elif '/messages' in path and '/projects/' in path:
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            pid     = path.split('/')[3]
            content = d.get('content','').strip()
            if not content: self.send_json({'ok': False, 'error': 'Empty message'}); return
            db  = get_db()
            mid = gen_id()
            db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (mid, pid, u['id'], u['name'], content, now()))
            db.commit()
            p = get_project_full(pid)
            if p:
                other = p['freelancer_id'] if u['id'] == p['client_id'] else p['client_id']
                if other: notify(other, f"💬 New message from {u['name']}", f'/project/{pid}')
            self.send_json({'ok': True, 'message': {'id': mid, 'sender_id': u['id'],
                'sender_name': u['name'], 'content': content, 'created_at': now()}})

        # DISPUTES
        elif '/dispute' in path and '/projects/' in path:
            if not u: self.send_json({'ok': False, 'error': 'Not authenticated'}); return
            pid    = path.split('/')[3]
            reason = d.get('reason','').strip()
            if not reason: self.send_json({'ok': False, 'error': 'Reason required'}); return
            db = get_db()
            if db.execute("SELECT id FROM disputes WHERE project_id=? AND status='open'", (pid,)).fetchone():
                self.send_json({'ok': False, 'error': 'A dispute is already open'}); return
            did = gen_id()
            db.execute('INSERT INTO disputes VALUES (?,?,?,?,?,?,?,?)',
                (did, pid, u['id'], reason, 'open', None, now(), None))
            db.execute('UPDATE projects SET dispute_status=? WHERE id=?', ('open', pid))
            db.commit()
            p = get_project_full(pid)
            if p:
                other = p['freelancer_id'] if u['id'] == p['client_id'] else p['client_id']
                if other: notify(other, f"⚖️ Dispute raised on '{p['title']}'", f'/project/{pid}')
            log_activity(f"{u['name']} raised a dispute on {pid}", pid, u['id'])
            self.send_json({'ok': True, 'dispute_id': did})

        # NOTIFICATIONS
        elif path == '/api/notifications/read':
            if not u: self.send_json({'ok': False}); return
            get_db().execute('UPDATE notifications SET read=1 WHERE user_id=?', (u['id'],))
            get_db().commit()
            self.send_json({'ok': True})

        else:
            self.send_json({'error': 'Not found'}, 404)

# ─────────────────────────────────────────────
# START
# ─────────────────────────────────────────────
init_db()

if __name__ == '__main__':
    port   = int(os.environ.get('PORT', 5000))
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f'\n🔒 LockWork → http://localhost:{port}\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
