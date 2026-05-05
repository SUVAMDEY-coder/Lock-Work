"""
LockWork — Managed Freelance Escrow Platform
Flask backend — ready for Render deployment
"""
from flask import Flask, request, jsonify, session, send_from_directory
import sqlite3, uuid, datetime, hashlib, os, base64, threading

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'lockwork-secret-key-change-in-prod')

DB_PATH = os.environ.get('DB_PATH', 'lockwork.db')
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

def now(): return datetime.datetime.now().isoformat()
def gen_id(): return str(uuid.uuid4())[:8].upper()
def hash_pass(p): return hashlib.sha256(p.encode()).hexdigest()
def row_to_dict(row): return dict(row) if row else None

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
    p = row_to_dict(db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone())
    if not p: return None
    ms = db.execute('SELECT * FROM milestones WHERE project_id=? ORDER BY sort_order', (pid,)).fetchall()
    p['milestones'] = [dict((k, v) for k, v in row_to_dict(m).items() if k != 'file_data') for m in ms]
    p['freelancer_accepted'] = bool(p['freelancer_accepted'])
    p['contract'] = row_to_dict(db.execute('SELECT * FROM contracts WHERE project_id=?', (pid,)).fetchone())
    return p

def current_user():
    uid = session.get('user_id')
    if not uid: return None
    return row_to_dict(get_db().execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())

def calc_reliability(user_id):
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM projects WHERE freelancer_id=? AND status IN ('complete','cancelled')", (user_id,)).fetchone()[0]
    completed = db.execute("SELECT COUNT(*) FROM projects WHERE freelancer_id=? AND status='complete'", (user_id,)).fetchone()[0]
    rate = round((completed / total * 100), 1) if total > 0 else 0.0
    db.execute('UPDATE users SET completion_rate=?, reliability_score=? WHERE id=?', (rate, rate, user_id))
    db.commit()

def make_contract(pid, title, client, freelancer, total, milestones, guarantee):
    ms_lines = '\n'.join([f"  {i+1}. {m['title']} — ${float(m['amount']):.2f}" for i, m in enumerate(milestones)])
    return f"""SERVICE AGREEMENT
═══════════════════════════════════════
CONTRACT ID: {pid}   DATE: {now()[:10]}

PARTIES
───────────────────────────────────────
CLIENT:     {client}
FREELANCER: {freelancer}

PROJECT: {title}

MILESTONES & PAYMENT
───────────────────────────────────────
{ms_lines}

TOTAL VALUE:       ${total:.2f}
PLATFORM FEE:      10% of project value
COMPLETION GUARANTEE: {'YES (+5% fee applied)' if guarantee else 'NO'}

TERMS
───────────────────────────────────────
1. All funds held in escrow until milestone approval.
2. Payment released per approved milestone only.
3. IP transfers to client upon full payment.
4. If freelancer inactive 14+ days, auto-replacement triggered.
5. Either party may raise a dispute. Platform mediates in 48h.
6. Freelancer forfeits milestone payment if work not delivered.
{'7. Completion Guarantee: Client eligible for refund or free replacement.' if guarantee else ''}

SIGNATURES
───────────────────────────────────────
Client:     {client} [SIGNED]
Freelancer: {freelancer} [PENDING]
"""

# ─────────────────────────────────────────────
# ROUTES — SERVE FRONTEND
# ─────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('templates', 'index.html')

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────
@app.route('/api/me')
def me():
    u = current_user()
    if u: return jsonify(ok=True, user={k: v for k, v in u.items() if k != 'password'})
    return jsonify(ok=False)

@app.route('/api/register', methods=['POST'])
def register():
    d = request.json or {}
    if not all([d.get('name'), d.get('email'), d.get('password')]):
        return jsonify(ok=False, error='All fields required')
    db = get_db()
    if db.execute('SELECT id FROM users WHERE email=?', (d['email'].lower().strip(),)).fetchone():
        return jsonify(ok=False, error='Email already registered')
    uid = gen_id()
    db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (uid, d['name'].strip(), d['email'].lower().strip(), hash_pass(d['password']),
         d.get('role', 'client'), 10000.0, '', '', 0, 0, 0.0, 0.0, 0, now()))
    db.commit()
    session['user_id'] = uid
    log_activity(f"New user registered: {d['name']} ({d.get('role','client')})")
    u = row_to_dict(db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())
    return jsonify(ok=True, user={k: v for k, v in u.items() if k != 'password'})

@app.route('/api/login', methods=['POST'])
def login():
    d = request.json or {}
    db = get_db()
    u = row_to_dict(db.execute('SELECT * FROM users WHERE email=?', (d.get('email','').lower().strip(),)).fetchone())
    if not u or u['password'] != hash_pass(d.get('password', '')):
        return jsonify(ok=False, error='Invalid email or password')
    session['user_id'] = u['id']
    return jsonify(ok=True, user={k: v for k, v in u.items() if k != 'password'})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify(ok=True)

# ─────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────
@app.route('/api/profile', methods=['POST'])
def update_profile():
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    d = request.json or {}
    db = get_db()
    email = d.get('email', u['email']).lower().strip()
    if email != u['email'] and db.execute('SELECT id FROM users WHERE email=? AND id!=?', (email, u['id'])).fetchone():
        return jsonify(ok=False, error='Email already in use')
    db.execute('UPDATE users SET name=?, email=?, bio=?, skills=? WHERE id=?',
        (d.get('name', u['name']), email, d.get('bio', u.get('bio', '')), d.get('skills', u.get('skills', '')), u['id']))
    db.commit()
    uu = row_to_dict(db.execute('SELECT * FROM users WHERE id=?', (u['id'],)).fetchone())
    return jsonify(ok=True, user={k: v for k, v in uu.items() if k != 'password'})

@app.route('/api/password', methods=['POST'])
def change_password():
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    d = request.json or {}
    if u['password'] != hash_pass(d.get('current_password', '')):
        return jsonify(ok=False, error='Current password incorrect')
    if len(d.get('new_password', '')) < 6:
        return jsonify(ok=False, error='Password must be at least 6 characters')
    db = get_db()
    db.execute('UPDATE users SET password=? WHERE id=?', (hash_pass(d['new_password']), u['id']))
    db.commit()
    return jsonify(ok=True)

@app.route('/api/balance')
def balance():
    u = current_user()
    if not u: return jsonify(balance=0)
    row = get_db().execute('SELECT balance FROM users WHERE id=?', (u['id'],)).fetchone()
    return jsonify(balance=row['balance'] if row else 0)

@app.route('/api/topup', methods=['POST'])
def topup():
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    amount = float((request.json or {}).get('amount', 0))
    if amount <= 0: return jsonify(ok=False, error='Invalid amount')
    db = get_db()
    db.execute('UPDATE users SET balance=balance+? WHERE id=?', (amount, u['id']))
    db.commit()
    bal = db.execute('SELECT balance FROM users WHERE id=?', (u['id'],)).fetchone()['balance']
    log_activity(f"{u['name']} added ${amount:.2f} to balance", user_id=u['id'])
    return jsonify(ok=True, balance=bal)

# ─────────────────────────────────────────────
# VERIFICATION
# ─────────────────────────────────────────────
@app.route('/api/verify-id', methods=['POST'])
def verify_id():
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    d = request.json or {}
    if not d.get('doc_data'): return jsonify(ok=False, error='Document required')
    db = get_db()
    db.execute('UPDATE users SET id_verified=1 WHERE id=?', (u['id'],))
    db.commit()
    log_activity(f"{u['name']} completed ID verification", user_id=u['id'])
    notify(u['id'], '✅ Your ID has been verified!', '/dashboard')
    return jsonify(ok=True, message='ID verified successfully')

@app.route('/api/skill-test', methods=['POST'])
def skill_test():
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    d = request.json or {}
    skill = d.get('skill', '')
    answers = d.get('answers', [])
    score = sum(10 for a in answers if a and a.get('correct'))
    passed = score >= 70
    db = get_db()
    db.execute('INSERT INTO skill_tests VALUES (?,?,?,?,?,?)', (gen_id(), u['id'], skill, score, 1 if passed else 0, now()))
    if passed:
        skills_list = [s.strip() for s in (u.get('skills') or '').split(',') if s.strip()]
        if skill not in skills_list:
            skills_list.append(skill)
        db.execute('UPDATE users SET skills=?, skill_score=skill_score+? WHERE id=?', (','.join(skills_list), score, u['id']))
    db.commit()
    return jsonify(ok=True, score=score, passed=passed,
        message='Passed! Skill added to profile.' if passed else 'Score below 70. Try again after 24 hours.')

@app.route('/api/freelancers')
def list_freelancers():
    db = get_db()
    rows = db.execute('''SELECT id,name,email,bio,skills,id_verified,skill_score,
        completion_rate,reliability_score,premium,created_at
        FROM users WHERE role="freelancer" ORDER BY reliability_score DESC''').fetchall()
    result = []
    for row in rows:
        f = row_to_dict(row)
        f['projects_completed'] = db.execute(
            "SELECT COUNT(*) FROM projects WHERE freelancer_id=? AND status='complete'", (f['id'],)).fetchone()[0]
        result.append(f)
    return jsonify(ok=True, freelancers=result)

@app.route('/api/freelancers/<fid>')
def get_freelancer(fid):
    db = get_db()
    u = row_to_dict(db.execute('''SELECT id,name,email,bio,skills,id_verified,skill_score,
        completion_rate,reliability_score,premium,created_at
        FROM users WHERE id=? AND role="freelancer"''', (fid,)).fetchone())
    if not u: return jsonify(ok=False, error='Not found')
    u['projects_completed'] = db.execute(
        "SELECT COUNT(*) FROM projects WHERE freelancer_id=? AND status='complete'", (fid,)).fetchone()[0]
    return jsonify(ok=True, freelancer=u)

# ─────────────────────────────────────────────
# PROJECTS
# ─────────────────────────────────────────────
def hydrate(rows):
    db = get_db()
    projects = []
    for row in rows:
        p = row_to_dict(row)
        ms = db.execute('SELECT * FROM milestones WHERE project_id=? ORDER BY sort_order', (p['id'],)).fetchall()
        p['milestones'] = [dict((k, v) for k, v in row_to_dict(m).items() if k != 'file_data') for m in ms]
        p['freelancer_accepted'] = bool(p['freelancer_accepted'])
        projects.append(p)
    return projects

@app.route('/api/projects/mine')
def my_projects():
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    db = get_db()
    if u['role'] == 'client':
        rows = db.execute('SELECT * FROM projects WHERE client_id=? ORDER BY created_at DESC', (u['id'],)).fetchall()
    else:
        rows = db.execute('SELECT * FROM projects WHERE freelancer_id=? ORDER BY created_at DESC', (u['id'],)).fetchall()
    return jsonify(ok=True, projects=hydrate(rows))

@app.route('/api/projects/all')
def all_projects():
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    db = get_db()
    if u['role'] == 'client':
        rows = db.execute('SELECT * FROM projects WHERE client_id=? ORDER BY created_at DESC', (u['id'],)).fetchall()
    else:
        rows = db.execute("SELECT * FROM projects WHERE status IN ('open','pending','active') ORDER BY created_at DESC").fetchall()
    return jsonify(ok=True, projects=hydrate(rows))

@app.route('/api/projects', methods=['POST'])
def create_project():
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    d = request.json or {}
    if not d.get('title') or not d.get('milestones'):
        return jsonify(ok=False, error='Title and milestones required')
    base = sum(float(ms['amount']) for ms in d['milestones'])
    commission = base * 0.10
    guarantee = bool(d.get('completion_guarantee'))
    gfee = base * 0.05 if guarantee else 0
    total_charge = base + commission + gfee
    db = get_db()
    bal = db.execute('SELECT balance FROM users WHERE id=?', (u['id'],)).fetchone()['balance']
    if total_charge > bal:
        return jsonify(ok=False, error=f'Insufficient balance. Need ${total_charge:.2f} (inc. fees), have ${bal:.2f}')
    db.execute('UPDATE users SET balance=balance-? WHERE id=?', (total_charge, u['id']))
    pid = gen_id()
    fe = (d.get('freelancer_email') or '').lower().strip() or None
    fl = row_to_dict(db.execute('SELECT * FROM users WHERE email=?', (fe,)).fetchone()) if fe else None
    status = 'pending' if fe else 'open'
    db.execute('INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (pid, d['title'], d.get('description', ''), u['id'], u['name'],
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
    if fl:
        notify(fl['id'], f"📋 New project invitation: {d['title']}", f'/project/{pid}')
    log_activity(f"Project '{d['title']}' posted by {u['name']} — ${base:.2f} locked in escrow", pid, u['id'])
    return jsonify(ok=True, project=get_project_full(pid))

@app.route('/api/projects/<pid>')
def get_project(pid):
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    p = get_project_full(pid)
    if not p: return jsonify(ok=False, error='Not found')
    return jsonify(ok=True, project=p)

@app.route('/api/projects/<pid>/accept', methods=['POST'])
def accept_project(pid):
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    p = get_project_full(pid)
    if not p: return jsonify(ok=False, error='Not found')
    if p.get('freelancer_id') and p['freelancer_id'] != u['id']:
        return jsonify(ok=False, error='Project assigned to another freelancer')
    db = get_db()
    db.execute('UPDATE projects SET freelancer_accepted=1, status=?, freelancer_id=?, freelancer_name=?, freelancer_email=? WHERE id=?',
        ('active', u['id'], u['name'], u['email'], pid))
    db.execute('UPDATE contracts SET signed_freelancer=1 WHERE project_id=?', (pid,))
    db.commit()
    notify(p['client_id'], f"✅ {u['name']} accepted your project '{p['title']}'", f'/project/{pid}')
    log_activity(f"{u['name']} accepted project '{p['title']}' and signed the contract", pid, u['id'])
    return jsonify(ok=True, project=get_project_full(pid))

@app.route('/api/projects/<pid>/cancel', methods=['POST'])
def cancel_project(pid):
    u = current_user()
    p = get_project_full(pid)
    if not p: return jsonify(ok=False, error='Not found')
    db = get_db()
    remaining = float(p['total']) - float(p['released'])
    db.execute('UPDATE projects SET status=? WHERE id=?', ('cancelled', pid))
    db.execute('UPDATE users SET balance=balance+? WHERE id=?', (remaining, p['client_id']))
    db.commit()
    log_activity(f"Project '{p['title']}' cancelled — ${remaining:.2f} returned to client", pid, u['id'] if u else None)
    return jsonify(ok=True)

@app.route('/api/projects/<pid>/contract')
def get_contract(pid):
    p = get_project_full(pid)
    if not p: return 'Not found', 404
    text = p['contract']['terms'] if p.get('contract') else 'No contract.'
    return text, 200, {'Content-Type': 'text/plain',
        'Content-Disposition': f'attachment; filename="contract-{pid}.txt"'}

# ─────────────────────────────────────────────
# MILESTONES
# ─────────────────────────────────────────────
@app.route('/api/projects/<pid>/milestones/<mid>/submit', methods=['POST'])
def submit_milestone(pid, mid):
    u = current_user()
    d = request.json or {}
    db = get_db()
    db.execute("""UPDATE milestones SET status='submitted', submitted_at=?,
        submission_note=?, file_name=?, file_data=?, file_type=?
        WHERE id=? AND project_id=?""",
        (now(), d.get('note'), d.get('file_name'), d.get('file_data'), d.get('file_type'), mid, pid))
    db.commit()
    ms = row_to_dict(db.execute('SELECT title FROM milestones WHERE id=?', (mid,)).fetchone())
    p = get_project_full(pid)
    if p: notify(p['client_id'], f"📎 Work submitted for '{ms['title'] if ms else mid}'", f'/project/{pid}')
    log_activity(f"{u['name'] if u else 'Freelancer'} submitted '{ms['title'] if ms else mid}'", pid, u['id'] if u else None)
    return jsonify(ok=True)

@app.route('/api/projects/<pid>/milestones/<mid>/approve', methods=['POST'])
def approve_milestone(pid, mid):
    u = current_user()
    db = get_db()
    ms = row_to_dict(db.execute('SELECT * FROM milestones WHERE id=?', (mid,)).fetchone())
    if not ms: return jsonify(ok=False, error='Not found')
    db.execute("UPDATE milestones SET status='complete', approved_at=? WHERE id=?", (now(), mid))
    db.execute('UPDATE projects SET released=released+? WHERE id=?', (ms['amount'], pid))
    p = get_project_full(pid)
    if p and p.get('freelancer_id'):
        payout = float(ms['amount']) * 0.90  # after 10% commission
        db.execute('UPDATE users SET balance=balance+? WHERE id=?', (payout, p['freelancer_id']))
        notify(p['freelancer_id'], f"💰 ${payout:.2f} released for '{ms['title']}'", f'/project/{pid}')
        calc_reliability(p['freelancer_id'])
    if p and all(m['status'] == 'complete' for m in p['milestones']):
        db.execute("UPDATE projects SET status='complete' WHERE id=?", (pid,))
        log_activity(f"🎉 Project '{p['title']}' completed!", pid)
    db.commit()
    log_activity(f"{u['name'] if u else 'Client'} approved '{ms['title']}' — ${float(ms['amount']):.2f} released", pid, u['id'] if u else None)
    return jsonify(ok=True)

@app.route('/api/projects/<pid>/milestones/<mid>/reject', methods=['POST'])
def reject_milestone(pid, mid):
    u = current_user()
    db = get_db()
    ms = row_to_dict(db.execute('SELECT title FROM milestones WHERE id=?', (mid,)).fetchone())
    db.execute("UPDATE milestones SET status='pending', submitted_at=NULL, submission_note=NULL, file_name=NULL, file_data=NULL WHERE id=?", (mid,))
    db.commit()
    p = get_project_full(pid)
    if p and p.get('freelancer_id'):
        notify(p['freelancer_id'], f"🔄 Revision requested on '{ms['title'] if ms else mid}'", f'/project/{pid}')
    log_activity(f"{u['name'] if u else 'Client'} requested revisions on '{ms['title'] if ms else mid}'", pid, u['id'] if u else None)
    return jsonify(ok=True)

@app.route('/api/milestones/<mid>/file')
def download_file(mid):
    db = get_db()
    ms = row_to_dict(db.execute('SELECT file_data,file_name,file_type FROM milestones WHERE id=?', (mid,)).fetchone())
    if not ms or not ms.get('file_data'): return 'Not found', 404
    file_bytes = base64.b64decode(ms['file_data'])
    return file_bytes, 200, {
        'Content-Type': ms.get('file_type', 'application/octet-stream'),
        'Content-Disposition': f'attachment; filename="{ms.get("file_name", "file")}"'
    }

# ─────────────────────────────────────────────
# MESSAGING
# ─────────────────────────────────────────────
@app.route('/api/projects/<pid>/messages')
def get_messages(pid):
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    rows = get_db().execute('SELECT * FROM messages WHERE project_id=? ORDER BY created_at ASC', (pid,)).fetchall()
    return jsonify(ok=True, messages=[row_to_dict(r) for r in rows])

@app.route('/api/projects/<pid>/messages', methods=['POST'])
def send_message(pid):
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    content = (request.json or {}).get('content', '').strip()
    if not content: return jsonify(ok=False, error='Empty message')
    db = get_db()
    mid = gen_id()
    db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)', (mid, pid, u['id'], u['name'], content, now()))
    db.commit()
    p = get_project_full(pid)
    if p:
        other = p['freelancer_id'] if u['id'] == p['client_id'] else p['client_id']
        if other: notify(other, f"💬 New message from {u['name']} on '{p['title']}'", f'/project/{pid}')
    return jsonify(ok=True, message={'id': mid, 'sender_id': u['id'], 'sender_name': u['name'], 'content': content, 'created_at': now()})

# ─────────────────────────────────────────────
# DISPUTES
# ─────────────────────────────────────────────
@app.route('/api/projects/<pid>/dispute', methods=['POST'])
def raise_dispute(pid):
    u = current_user()
    if not u: return jsonify(ok=False, error='Not authenticated')
    reason = (request.json or {}).get('reason', '').strip()
    if not reason: return jsonify(ok=False, error='Reason required')
    db = get_db()
    if db.execute("SELECT id FROM disputes WHERE project_id=? AND status='open'", (pid,)).fetchone():
        return jsonify(ok=False, error='A dispute is already open for this project')
    did = gen_id()
    db.execute('INSERT INTO disputes VALUES (?,?,?,?,?,?,?,?)', (did, pid, u['id'], reason, 'open', None, now(), None))
    db.execute('UPDATE projects SET dispute_status=? WHERE id=?', ('open', pid))
    db.commit()
    p = get_project_full(pid)
    if p:
        other = p['freelancer_id'] if u['id'] == p['client_id'] else p['client_id']
        if other: notify(other, f"⚖️ Dispute raised on '{p['title']}'", f'/project/{pid}')
    log_activity(f"{u['name']} raised a dispute on project {pid}", pid, u['id'])
    return jsonify(ok=True, dispute_id=did)

# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────
@app.route('/api/notifications')
def get_notifications():
    u = current_user()
    if not u: return jsonify(notifications=[])
    rows = get_db().execute('SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20', (u['id'],)).fetchall()
    return jsonify(notifications=[row_to_dict(r) for r in rows])

@app.route('/api/notifications/read', methods=['POST'])
def mark_read():
    u = current_user()
    if not u: return jsonify(ok=False)
    get_db().execute('UPDATE notifications SET read=1 WHERE user_id=?', (u['id'],))
    get_db().commit()
    return jsonify(ok=True)

# ─────────────────────────────────────────────
# ACTIVITY & STATS
# ─────────────────────────────────────────────
@app.route('/api/activity')
def get_activity():
    u = current_user()
    if not u: return jsonify(logs=[])
    db = get_db()
    proj = request.args.get('project')
    if proj:
        rows = db.execute('SELECT * FROM activity WHERE project_id=? ORDER BY time DESC LIMIT 30', (proj,)).fetchall()
    elif u['role'] == 'client':
        rows = db.execute('''SELECT a.* FROM activity a LEFT JOIN projects p ON a.project_id=p.id
            WHERE p.client_id=? OR a.project_id IS NULL ORDER BY a.time DESC LIMIT 30''', (u['id'],)).fetchall()
    else:
        rows = db.execute('''SELECT a.* FROM activity a LEFT JOIN projects p ON a.project_id=p.id
            WHERE p.freelancer_id=? OR a.project_id IS NULL ORDER BY a.time DESC LIMIT 30''', (u['id'],)).fetchall()
    return jsonify(logs=[row_to_dict(r) for r in rows])

@app.route('/api/stats')
def stats():
    db = get_db()
    active = db.execute("SELECT COUNT(*) FROM projects WHERE status IN ('active','open','pending')").fetchone()[0]
    escrow = db.execute("SELECT SUM(total) FROM projects WHERE status NOT IN ('complete','cancelled')").fetchone()[0] or 0
    completed = db.execute("SELECT COUNT(*) FROM milestones WHERE status='complete'").fetchone()[0]
    freelancers = db.execute("SELECT COUNT(*) FROM users WHERE role='freelancer'").fetchone()[0]
    return jsonify(projects=active, escrow=escrow, completed=completed, freelancers=freelancers)

# ─────────────────────────────────────────────
# START
# ─────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    print(f'\n🔒 LockWork → http://localhost:{port}\n')
    app.run(host='0.0.0.0', port=port, debug=False)

init_db()
