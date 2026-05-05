// LockWork — Frontend JS
let currentUser = null, currentRole = 'client', milestoneCount = 0;
let currentProjectId = null, currentTab = 'projects';
let submitProjId = null, submitMsId = null, selectedFile = null;
let disputeProjId = null, allFreelancers = [];

// ── API ──────────────────────────────────────
async function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' }, credentials: 'include' };
  if (body) opts.body = JSON.stringify(body);
  try { const r = await fetch(path, opts); return r.json(); }
  catch (e) { return { ok: false, error: 'Network error' }; }
}

// ── NAV / PAGES ──────────────────────────────
function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const el = document.getElementById('page-' + name);
  if (el) { el.classList.add('active'); el.classList.add('animate-in'); }
  window.scrollTo(0, 0);
  if (name === 'dashboard') renderDashboard();
  if (name === 'newproject') initNewProject();
  if (name === 'home') updateStats();
  if (name === 'freelancers') loadFreelancers();
}

function updateNav() {
  const nav = document.getElementById('authNav');
  const bell = document.getElementById('notifBell');
  if (currentUser) {
    nav.innerHTML = `<span style="color:var(--muted);font-size:0.75rem">${currentUser.name}</span>
      <a onclick="showPage('dashboard')">Dashboard</a>
      <a onclick="logout()">Sign Out</a>`;
    bell.style.display = 'block';
    loadNotifCount();
  } else {
    nav.innerHTML = `<a onclick="showPage('auth')">Sign In</a>`;
    bell.style.display = 'none';
  }
}

async function loadNotifCount() {
  const r = await api('/api/notifications');
  const unread = (r.notifications || []).filter(n => !n.read).length;
  const badge = document.getElementById('notifCount');
  if (unread > 0) { badge.style.display = 'flex'; badge.textContent = unread; }
  else badge.style.display = 'none';
}

// ── AUTH ─────────────────────────────────────
function toggleAuth(mode) {
  document.getElementById('loginForm').style.display = mode === 'login' ? 'block' : 'none';
  document.getElementById('registerForm').style.display = mode === 'register' ? 'block' : 'none';
  document.getElementById('authAlert').innerHTML = '';
}

function selectRole(role) {
  currentRole = role;
  document.getElementById('roleClient').classList.toggle('selected', role === 'client');
  document.getElementById('roleFreelancer').classList.toggle('selected', role === 'freelancer');
}

async function login() {
  const email = document.getElementById('loginEmail').value.trim();
  const pass = document.getElementById('loginPass').value;
  if (!email || !pass) { showAlert('authAlert', 'Please enter email and password', 'err'); return; }
  const r = await api('/api/login', 'POST', { email, password: pass });
  if (r.ok) { currentUser = r.user; updateNav(); showPage('dashboard'); }
  else showAlert('authAlert', r.error || 'Login failed', 'err');
}

async function register() {
  const name = document.getElementById('regName').value.trim();
  const email = document.getElementById('regEmail').value.trim();
  const pass = document.getElementById('regPass').value;
  if (!name || !email || !pass) { showAlert('authAlert', 'All fields required', 'err'); return; }
  const r = await api('/api/register', 'POST', { name, email, password: pass, role: currentRole });
  if (r.ok) { currentUser = r.user; updateNav(); showPage('dashboard'); }
  else showAlert('authAlert', r.error || 'Registration failed', 'err');
}

async function demoLogin(role) {
  const demos = { business: { email: 'business@demo.com', password: 'demo123' }, freelancer: { email: 'freelancer@demo.com', password: 'demo123' } };
  let r = await api('/api/login', 'POST', demos[role]);
  if (!r.ok) {
    const names = { business: 'Acme Corp', freelancer: 'Alex Dev' };
    const roles = { business: 'client', freelancer: 'freelancer' };
    r = await api('/api/register', 'POST', { name: names[role], email: demos[role].email, password: demos[role].password, role: roles[role] });
  }
  if (r.ok) { currentUser = r.user; updateNav(); showPage('dashboard'); }
}

async function logout() {
  await api('/api/logout', 'POST');
  currentUser = null; updateNav(); showPage('home');
}

// ── DASHBOARD ────────────────────────────────
async function renderDashboard() {
  if (!currentUser) { showPage('auth'); return; }
  document.getElementById('dashTitle').textContent = `Welcome, ${currentUser.name}`;
  document.getElementById('dashSubtitle').textContent = currentUser.role === 'client'
    ? 'Manage projects, track milestones, and review freelancer submissions'
    : 'Find projects, submit work, and build your reputation';

  const actions = document.getElementById('dashActions');
  actions.innerHTML = currentUser.role === 'client'
    ? `<button class="btn btn-outline btn-sm" onclick="openModal('topupModal')">💰 Add Funds</button>
       <button class="btn btn-amber" onclick="showPage('newproject')">+ Post Project</button>`
    : `<button class="btn btn-outline btn-sm" onclick="openModal('verifyModal')">🪪 Get Verified</button>
       <button class="btn btn-purple btn-sm" onclick="openSkillModal()">🎯 Take Skill Test</button>`;

  // Build tabs
  const tabs = currentUser.role === 'client'
    ? ['projects', 'browse', 'activity', 'notifications', 'profile']
    : ['projects', 'browse', 'activity', 'notifications', 'verification', 'profile'];
  const labels = { projects: 'My Projects', browse: 'Browse', activity: 'Activity', notifications: '🔔 Alerts', verification: 'Verification', profile: 'Profile' };
  document.getElementById('dashTabs').innerHTML = tabs.map(t =>
    `<div class="tab ${t === currentTab ? 'active' : ''}" id="tab-${t}" onclick="switchTab('${t}')">${labels[t]}</div>`
  ).join('');

  switchTab(currentTab);
}

async function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const tabEl = document.getElementById('tab-' + tab);
  if (tabEl) tabEl.classList.add('active');
  const el = document.getElementById('tabContent');
  el.innerHTML = '<div class="empty-state"><div>Loading...</div></div>';
  if (tab === 'projects') await renderMyProjects(el);
  if (tab === 'browse') await renderBrowseProjects(el);
  if (tab === 'activity') await renderActivity(el);
  if (tab === 'notifications') await renderNotifications(el);
  if (tab === 'verification') renderVerification(el);
  if (tab === 'profile') await renderProfile(el);
}

// ── PROJECTS LIST ────────────────────────────
async function renderMyProjects(el) {
  const r = await api('/api/projects/mine');
  const projects = r.projects || [];
  if (!projects.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">📋</div>
      <div>${currentUser.role === 'client' ? 'No projects yet. Post your first one.' : "No projects yet. Browse open ones!"}</div>
      ${currentUser.role === 'freelancer' ? '<br><button class="btn btn-amber" onclick="switchTab(\'browse\')" style="margin-top:12px">Browse Projects →</button>' : ''}
    </div>`; return;
  }
  el.innerHTML = projects.map(p => projectCard(p)).join('');
}

async function renderBrowseProjects(el) {
  const r = await api('/api/projects/all');
  const projects = r.projects || [];
  const label = currentUser.role === 'client' ? 'All your posted projects' : 'All open projects — click any to apply';
  el.innerHTML = `<p class="text-muted" style="margin-bottom:16px;font-size:0.75rem;">${label}</p>` +
    (projects.length ? projects.map(p => projectCard(p)).join('') : '<div class="empty-state"><div class="icon">🔍</div><div>No open projects right now.</div></div>');
}

function projectCard(p) {
  const done = p.milestones.filter(m => m.status === 'complete').length;
  const pct = p.milestones.length ? (done / p.milestones.length * 100).toFixed(0) : 0;
  const disputeBadge = p.dispute_status === 'open' ? '<span class="badge badge-dispute" style="margin-left:6px;">⚖️ Dispute</span>' : '';
  const guaranteeBadge = p.completion_guarantee ? '<span class="badge badge-verified" style="margin-left:6px;">🛡️ Guaranteed</span>' : '';
  return `<div class="card" style="cursor:pointer;margin-bottom:8px;" onclick="viewProject('${p.id}')">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
      <div>
        <div class="card-title">${p.title}${guaranteeBadge}${disputeBadge}</div>
        <div class="card-id">ID: ${p.id} · By ${p.client_name} · ${p.deadline || 'No deadline'}</div>
      </div>
      <span class="badge badge-${p.status}">${p.status}</span>
    </div>
    <div class="flex justify-between items-center">
      <div class="text-muted">${p.milestones.length} milestone${p.milestones.length !== 1 ? 's' : ''} · ${p.freelancer_name || '<span style="color:var(--green)">Open</span>'}</div>
      <div class="escrow-amount" style="font-size:1.1rem">$${Number(p.total).toFixed(2)}</div>
    </div>
    <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
    <div class="text-muted mt-8">${done} of ${p.milestones.length} milestones complete · $${Number(p.released).toFixed(2)} released</div>
  </div>`;
}

// ── ACTIVITY ─────────────────────────────────
async function renderActivity(el) {
  const r = await api('/api/activity');
  const logs = r.logs || [];
  if (!logs.length) { el.innerHTML = '<div class="empty-state"><div class="icon">📝</div><div>No activity yet.</div></div>'; return; }
  el.innerHTML = '<div class="card">' + logs.map(l => `
    <div class="log-entry">
      <div class="log-time">${l.time.slice(0, 10)} ${l.time.slice(11, 16)}</div>
      <div class="log-dot"></div>
      <div class="log-text">${l.text}</div>
    </div>`).join('') + '</div>';
}

// ── NOTIFICATIONS ────────────────────────────
async function renderNotifications(el) {
  const r = await api('/api/notifications');
  const notifs = r.notifications || [];
  await api('/api/notifications/read', 'POST');
  document.getElementById('notifCount').style.display = 'none';
  if (!notifs.length) { el.innerHTML = '<div class="empty-state"><div class="icon">🔔</div><div>No notifications yet.</div></div>'; return; }
  el.innerHTML = '<div class="card" style="padding:0;">' + notifs.map(n => `
    <div class="notif-item ${n.read ? '' : 'unread'}" ${n.link ? `onclick="handleNotifLink('${n.link}')"` : ''} style="${n.link ? 'cursor:pointer;' : ''}">
      <div class="notif-dot ${n.read ? 'read' : ''}"></div>
      <div>
        <div style="font-size:0.82rem;">${n.text}</div>
        <div class="text-muted" style="font-size:0.65rem;margin-top:3px;">${n.created_at.slice(0, 16).replace('T', ' ')}</div>
      </div>
    </div>`).join('') + '</div>';
}

function handleNotifLink(link) {
  if (link.startsWith('/project/')) viewProject(link.replace('/project/', ''));
  else if (link === '/dashboard') showPage('dashboard');
}

// ── VERIFICATION TAB ─────────────────────────
function renderVerification(el) {
  const verified = currentUser.id_verified;
  el.innerHTML = `
    <div class="card" style="max-width:600px;">
      <div class="section-label" style="margin-bottom:20px;">🪪 ID Verification</div>
      <div class="alert alert-info">Verified freelancers get 3x more project invitations and appear at the top of search results.</div>
      ${verified
        ? '<div class="alert alert-ok">✅ Your ID is verified. You have the verified badge on your profile.</div>'
        : `<p class="text-muted" style="font-size:0.8rem;margin-bottom:16px;">Upload a government-issued photo ID. Your document is reviewed within 24 hours.</p>
           <button class="btn btn-amber" onclick="openModal('verifyModal')">Upload ID Document</button>`}
    </div>
    <div class="card" style="max-width:600px;">
      <div class="section-label" style="margin-bottom:20px;">🎯 Skill Tests</div>
      <p class="text-muted" style="font-size:0.8rem;margin-bottom:20px;">Pass skill tests to earn badges. Score 70+ to get certified. Certified skills show on your profile.</p>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;">
        ${['JavaScript','Python','React','UI/UX Design','Node.js','SQL','PHP','WordPress'].map(skill => `
          <button class="btn btn-outline" onclick="openSkillModal('${skill}')" style="text-align:left;padding:12px;">
            🎯 ${skill}
            ${(currentUser.skills || '').includes(skill) ? '<span class="badge badge-complete" style="margin-left:4px;">✓</span>' : ''}
          </button>`).join('')}
      </div>
    </div>`;
}

// ── PROFILE ──────────────────────────────────
async function renderProfile(el) {
  const [bal, projR] = await Promise.all([api('/api/balance'), api('/api/projects/mine')]);
  const balance = Number(bal.balance || 0);
  const projects = projR.projects || [];
  const completed = projects.filter(p => p.status === 'complete').length;
  const active = projects.filter(p => ['active', 'pending', 'open'].includes(p.status)).length;
  const totalValue = projects.reduce((s, p) => s + Number(p.total), 0);
  const initials = currentUser.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
  const isClient = currentUser.role === 'client';

  el.innerHTML = `
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
    <div class="card" style="margin-bottom:0;">
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px;">
        <div style="width:64px;height:64px;border-radius:50%;background:var(--amber);display:flex;align-items:center;justify-content:center;font-family:var(--sans);font-size:1.4rem;font-weight:800;color:var(--navy);flex-shrink:0;">${initials}</div>
        <div>
          <div style="font-family:var(--sans);font-size:1.2rem;font-weight:700;">${currentUser.name}</div>
          <div class="text-muted">${currentUser.email}</div>
          <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;">
            <span class="badge ${isClient ? 'badge-active' : 'badge-complete'}">${isClient ? '🏢 Business' : '👤 Freelancer'}</span>
            ${currentUser.id_verified ? '<span class="badge badge-verified">🪪 Verified</span>' : ''}
            ${currentUser.premium ? '<span class="badge badge-review">⭐ Premium</span>' : ''}
          </div>
        </div>
      </div>
      <div style="font-size:0.78rem;">
        <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);">
          <span class="text-muted">Member ID</span><span class="bold">${currentUser.id}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);">
          <span class="text-muted">Joined</span><span>${(currentUser.created_at || '').slice(0, 10)}</span>
        </div>
        ${!isClient ? `
        <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);">
          <span class="text-muted">Reliability Score</span><span class="text-green bold">${Number(currentUser.reliability_score || 0).toFixed(1)}%</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:8px 0;">
          <span class="text-muted">Skills</span><span style="text-align:right;max-width:180px;">${currentUser.skills || 'None yet'}</span>
        </div>` : ''}
      </div>
    </div>
    <div class="card" style="margin-bottom:0;">
      <div class="section-label" style="margin-bottom:16px;">Balance</div>
      <div class="escrow-box">
        <div class="escrow-amount">$${balance.toFixed(2)}</div>
        <div class="escrow-meta">${isClient ? 'Available to lock in escrow' : 'Available balance'}</div>
      </div>
      ${isClient ? '<button class="btn btn-amber w-full" onclick="openModal(\'topupModal\')">💰 Add Funds</button>' : ''}
    </div>
  </div>

  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:2px;background:var(--border);border:1px solid var(--border);margin-bottom:16px;">
    ${[['Total', projects.length, 'var(--amber)'], ['Active', active, 'var(--blue)'], ['Done', completed, 'var(--green)'], ['$' + totalValue.toFixed(0), isClient ? 'Spent' : 'Earned', 'var(--amber)']].map(([n, l, c]) => `
    <div style="background:var(--navy2);padding:20px;text-align:center;">
      <div style="font-family:var(--sans);font-size:1.6rem;font-weight:800;color:${c};">${n}</div>
      <div style="font-size:0.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:0.1em;margin-top:4px;">${l}</div>
    </div>`).join('')}
  </div>

  <div class="card">
    <div class="section-label" style="margin-bottom:20px;">Edit Profile</div>
    <div id="profileAlert"></div>
    <div class="form-row">
      <div class="form-group"><label>Full Name</label><input type="text" id="editName" value="${currentUser.name}"></div>
      <div class="form-group"><label>Email</label><input type="email" id="editEmail" value="${currentUser.email}"></div>
    </div>
    <div class="form-group"><label>Bio</label><textarea id="editBio" placeholder="Tell clients about yourself...">${currentUser.bio || ''}</textarea></div>
    ${!isClient ? `<div class="form-group"><label>Skills (comma separated)</label><input type="text" id="editSkills" value="${currentUser.skills || ''}" placeholder="JavaScript, React, Node.js"></div>` : ''}
    <button class="btn btn-amber" onclick="saveProfile()">Save Changes</button>
  </div>

  <div class="card">
    <div class="section-label" style="margin-bottom:20px;">Change Password</div>
    <div id="passwordAlert"></div>
    <div class="form-row">
      <div class="form-group"><label>Current Password</label><input type="password" id="currPass" placeholder="••••••••"></div>
      <div class="form-group"><label>New Password</label><input type="password" id="newPass" placeholder="••••••••"></div>
    </div>
    <div class="form-group" style="max-width:280px;"><label>Confirm New Password</label><input type="password" id="confirmPass" placeholder="••••••••"></div>
    <button class="btn btn-outline" onclick="changePassword()">Update Password</button>
  </div>

  ${projects.length ? `<div class="card">
    <div class="section-label" style="margin-bottom:16px;">Recent Projects</div>
    ${projects.slice(0, 3).map(p => `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border);cursor:pointer;" onclick="viewProject('${p.id}')">
        <div><div style="font-size:0.85rem;font-weight:600;">${p.title}</div><div class="text-muted" style="font-size:0.7rem;">${p.milestones.length} milestones · $${Number(p.total).toFixed(2)}</div></div>
        <span class="badge badge-${p.status}">${p.status}</span>
      </div>`).join('')}
    ${projects.length > 3 ? `<div style="text-align:center;margin-top:12px;"><a onclick="switchTab('projects')" style="color:var(--amber);cursor:pointer;font-size:0.78rem;">View all ${projects.length} →</a></div>` : ''}
  </div>` : ''}

  <div class="card" style="border-color:rgba(239,68,68,0.3);">
    <div class="section-label" style="margin-bottom:12px;color:var(--red);">Account</div>
    <p class="text-muted" style="font-size:0.78rem;margin-bottom:16px;">Sign out of your account on this device.</p>
    <button class="btn btn-danger" onclick="logout()">Sign Out</button>
  </div>`;
}

async function saveProfile() {
  const name = document.getElementById('editName').value.trim();
  const email = document.getElementById('editEmail').value.trim();
  const bio = document.getElementById('editBio') ? document.getElementById('editBio').value.trim() : '';
  const skills = document.getElementById('editSkills') ? document.getElementById('editSkills').value.trim() : '';
  if (!name || !email) { showAlert('profileAlert', 'Name and email required', 'err'); return; }
  const r = await api('/api/profile', 'POST', { name, email, bio, skills });
  if (r.ok) { currentUser = { ...currentUser, ...r.user }; updateNav(); showAlert('profileAlert', 'Profile updated!', 'ok'); }
  else showAlert('profileAlert', r.error || 'Failed', 'err');
}

async function changePassword() {
  const curr = document.getElementById('currPass').value;
  const nw = document.getElementById('newPass').value;
  const conf = document.getElementById('confirmPass').value;
  if (!curr || !nw || !conf) { showAlert('passwordAlert', 'All fields required', 'err'); return; }
  if (nw !== conf) { showAlert('passwordAlert', 'Passwords do not match', 'err'); return; }
  const r = await api('/api/password', 'POST', { current_password: curr, new_password: nw });
  if (r.ok) {
    showAlert('passwordAlert', 'Password changed!', 'ok');
    ['currPass', 'newPass', 'confirmPass'].forEach(id => document.getElementById(id).value = '');
  } else showAlert('passwordAlert', r.error || 'Failed', 'err');
}

// ── FREELANCER DIRECTORY ─────────────────────
async function loadFreelancers() {
  const r = await api('/api/freelancers');
  allFreelancers = r.freelancers || [];
  renderFreelancerList(allFreelancers);
}

function filterFreelancers(q) {
  const filtered = q
    ? allFreelancers.filter(f => (f.skills || '').toLowerCase().includes(q.toLowerCase()) || f.name.toLowerCase().includes(q.toLowerCase()))
    : allFreelancers;
  renderFreelancerList(filtered);
}

function renderFreelancerList(list) {
  const el = document.getElementById('freelancerList');
  if (!list.length) { el.innerHTML = '<div class="empty-state"><div class="icon">👤</div><div>No freelancers found.</div></div>'; return; }
  el.innerHTML = list.map(f => {
    const initials = f.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
    const rel = Number(f.reliability_score || 0);
    return `<div class="freelancer-card" onclick="viewFreelancer('${f.id}')">
      <div class="fl-avatar">${initials}</div>
      <div class="fl-info">
        <div class="fl-name">${f.name} ${f.id_verified ? '<span class="badge badge-verified">🪪 Verified</span>' : ''}</div>
        <div class="fl-skills">${f.skills || 'No skills listed'}</div>
        <div style="font-size:0.72rem;color:var(--muted);margin-top:4px;">${f.bio ? f.bio.slice(0, 80) + (f.bio.length > 80 ? '...' : '') : ''}</div>
        <div class="fl-stats">
          <div class="fl-stat">Reliability: <span>${rel.toFixed(0)}%</span></div>
          <div class="fl-stat">Projects: <span>${f.projects_completed || 0}</span></div>
          <div class="fl-stat">Score: <span>${f.skill_score || 0}pts</span></div>
        </div>
        <div class="reliability-bar"><div class="reliability-fill" style="width:${rel}%"></div></div>
      </div>
    </div>`;
  }).join('');
}

async function viewFreelancer(id) {
  const r = await api(`/api/freelancers/${id}`);
  if (!r.ok) return;
  const f = r.freelancer;
  const initials = f.name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
  showPage('project');
  document.getElementById('projectDetailContent').innerHTML = `
    <button class="btn btn-outline btn-sm" onclick="showPage('freelancers')" style="margin-bottom:20px;">← Back to Freelancers</button>
    <div class="card">
      <div style="display:flex;gap:20px;align-items:flex-start;flex-wrap:wrap;">
        <div style="width:80px;height:80px;border-radius:50%;background:var(--amber);display:flex;align-items:center;justify-content:center;font-family:var(--sans);font-size:1.8rem;font-weight:800;color:var(--navy);">${initials}</div>
        <div style="flex:1;">
          <div style="font-family:var(--sans);font-size:1.4rem;font-weight:700;">${f.name}</div>
          <div class="text-muted">${f.email}</div>
          <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">
            ${f.id_verified ? '<span class="badge badge-verified">🪪 ID Verified</span>' : ''}
            ${(f.skills || '').split(',').filter(s => s.trim()).map(s => `<span class="badge badge-active">${s.trim()}</span>`).join('')}
          </div>
        </div>
        ${currentUser && currentUser.role === 'client' ? `<button class="btn btn-amber" onclick="showPage('newproject');document.getElementById('projFreelancer').value='${f.email}'">Hire ${f.name.split(' ')[0]}</button>` : ''}
      </div>
      ${f.bio ? `<p style="margin-top:20px;font-size:0.85rem;line-height:1.7;color:var(--text);">${f.bio}</p>` : ''}
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:2px;background:var(--border);border:1px solid var(--border);margin-bottom:16px;">
      <div style="background:var(--navy2);padding:20px;text-align:center;"><div style="font-family:var(--sans);font-size:1.6rem;font-weight:800;color:var(--green);">${Number(f.reliability_score || 0).toFixed(0)}%</div><div class="stat-l">Reliability</div></div>
      <div style="background:var(--navy2);padding:20px;text-align:center;"><div style="font-family:var(--sans);font-size:1.6rem;font-weight:800;color:var(--amber);">${f.projects_completed || 0}</div><div class="stat-l">Completed</div></div>
      <div style="background:var(--navy2);padding:20px;text-align:center;"><div style="font-family:var(--sans);font-size:1.6rem;font-weight:800;color:var(--blue);">${f.skill_score || 0}</div><div class="stat-l">Skill Score</div></div>
    </div>`;
}

// ── NEW PROJECT ──────────────────────────────
function initNewProject() {
  milestoneCount = 0;
  ['projTitle', 'projDesc', 'projFreelancer'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('milestoneInputs').innerHTML = '';
  document.getElementById('totalAmount').textContent = '$0.00';
  document.getElementById('newProjectAlert').innerHTML = '';
  document.getElementById('balanceWarning').style.display = 'none';
  document.getElementById('guaranteeCheck').checked = false;
  addMilestone(); addMilestone(); addMilestone();
  const d = new Date(); d.setDate(d.getDate() + 30);
  document.getElementById('projDeadline').value = d.toISOString().split('T')[0];
  document.getElementById('guaranteeCheck').onchange = calcTotal;
}

function addMilestone() {
  milestoneCount++;
  const n = milestoneCount;
  const div = document.createElement('div');
  div.id = 'ms-' + n; div.className = 'milestone-item';
  div.innerHTML = `<span class="milestone-num">M${n}</span>
    <input type="text" placeholder="Milestone description" style="flex:1;margin-right:8px" id="msTitle-${n}" oninput="calcTotal()">
    <input type="number" placeholder="Amount $" style="width:120px;margin-right:8px" id="msAmt-${n}" min="0" step="0.01" oninput="calcTotal()">
    <input type="date" style="width:140px;margin-right:8px" id="msDead-${n}" title="Milestone deadline">
    <button class="btn btn-outline btn-sm" onclick="removeMilestone(${n})">✕</button>`;
  document.getElementById('milestoneInputs').appendChild(div);
}

function removeMilestone(n) { const el = document.getElementById('ms-' + n); if (el) el.remove(); calcTotal(); }

function calcTotal() {
  let base = 0;
  for (let i = 1; i <= milestoneCount; i++) {
    const a = parseFloat(document.getElementById('msAmt-' + i)?.value || 0);
    if (!isNaN(a)) base += a;
  }
  const guarantee = document.getElementById('guaranteeCheck')?.checked;
  const commission = base * 0.10;
  const guaranteeFee = guarantee ? base * 0.05 : 0;
  const total = base + commission + guaranteeFee;
  document.getElementById('totalAmount').textContent = '$' + total.toFixed(2);
  document.getElementById('feeBreakdown').textContent =
    `Base $${base.toFixed(2)} + 10% fee $${commission.toFixed(2)}${guarantee ? ` + 5% guarantee $${guaranteeFee.toFixed(2)}` : ''}`;
}

async function createProject() {
  const title = document.getElementById('projTitle').value.trim();
  const desc = document.getElementById('projDesc').value.trim();
  const freelancerEmail = document.getElementById('projFreelancer').value.trim();
  const deadline = document.getElementById('projDeadline').value;
  const guarantee = document.getElementById('guaranteeCheck').checked;
  const milestones = [];
  for (let i = 1; i <= milestoneCount; i++) {
    const t = document.getElementById('msTitle-' + i), a = document.getElementById('msAmt-' + i);
    const dead = document.getElementById('msDead-' + i);
    if (t && a && t.value.trim() && parseFloat(a.value) > 0)
      milestones.push({ title: t.value.trim(), amount: parseFloat(a.value), deadline: dead?.value || null });
  }
  if (!title || !milestones.length) { showAlert('newProjectAlert', 'Title and at least one milestone required', 'err'); return; }
  const r = await api('/api/projects', 'POST', { title, description: desc, freelancer_email: freelancerEmail, deadline, milestones, completion_guarantee: guarantee });
  if (r.ok) { showPage('dashboard'); setTimeout(() => viewProject(r.project.id), 300); }
  else {
    showAlert('newProjectAlert', r.error || 'Failed to create project', 'err');
    if (r.error && r.error.includes('balance')) document.getElementById('balanceWarning').style.display = 'block';
  }
}

// ── PROJECT DETAIL ────────────────────────────
async function viewProject(id) {
  currentProjectId = id;
  showPage('project');
  document.getElementById('projectDetailContent').innerHTML = '<div class="empty-state"><div>Loading...</div></div>';
  const r = await api('/api/projects/' + id);
  if (!r.ok) { document.getElementById('projectDetailContent').innerHTML = '<div class="empty-state"><div>Project not found.</div></div>'; return; }
  const p = r.project;
  const isClient = currentUser.role === 'client' && p.client_id === currentUser.id;
  const isMyFreelancer = currentUser.role === 'freelancer' && p.freelancer_id === currentUser.id;
  const isOpen = ['open', 'pending'].includes(p.status) && !p.freelancer_id;
  const canAccept = currentUser.role === 'freelancer' && (isOpen || (p.status === 'pending' && p.freelancer_id === currentUser.id && !p.freelancer_accepted));

  const milestonesHTML = p.milestones.map((m, i) => {
    let actions = '';
    if (isMyFreelancer && m.status === 'pending' && p.freelancer_accepted)
      actions = `<button class="btn btn-amber btn-sm" onclick="openSubmitModal('${p.id}','${m.id}','${m.title.replace(/'/g, "\\'")}')">📎 Submit Work</button>`;
    if (isClient && m.status === 'submitted')
      actions = `<button class="btn btn-green btn-sm" onclick="approveMilestone('${p.id}','${m.id}')">✓ Approve & Pay</button>
                 <button class="btn btn-outline btn-sm" onclick="rejectMilestone('${p.id}','${m.id}')">Request Revision</button>`;
    if (m.status === 'complete')
      actions = `<span class="text-green" style="font-size:0.75rem;">✓ Paid $${Number(m.amount).toFixed(2)}</span>`;
    const bc = m.status === 'pending' ? 'locked' : m.status === 'submitted' ? 'review' : m.status === 'complete' ? 'complete' : 'active';
    let submission = '';
    if ((m.status === 'submitted' || m.status === 'complete') && (m.submission_note || m.file_name)) {
      submission = `<div class="milestone-body">
        ${m.submission_note ? `<div style="font-size:0.8rem;margin-bottom:8px;">💬 ${m.submission_note}</div>` : ''}
        ${m.file_name ? `<div class="file-preview"><span>📄</span><div><div style="font-weight:700;font-size:0.8rem;">${m.file_name}</div><div class="text-muted">Submitted file</div></div>
          <a href="/api/milestones/${m.id}/file" class="btn btn-outline btn-sm" style="margin-left:auto;" download="${m.file_name}">↓ Download</a></div>` : ''}
      </div>`;
    }
    return `<div class="milestone-item" style="flex-direction:column;align-items:stretch;">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <span class="milestone-num">M${i + 1}</span>
        <span class="milestone-title">${m.title}</span>
        ${m.deadline ? `<span class="text-muted" style="font-size:0.7rem;">📅 ${m.deadline}</span>` : ''}
        <span class="badge badge-${bc}">${m.status}</span>
        <span class="milestone-amount">$${Number(m.amount).toFixed(2)}</span>
        <div class="milestone-actions">${actions}</div>
      </div>
      ${submission}
    </div>`;
  }).join('');

  const done = p.milestones.filter(m => m.status === 'complete').length;
  const pct = p.milestones.length ? (done / p.milestones.length * 100).toFixed(0) : 0;
  const acceptBtn = canAccept ? `<button class="btn btn-amber" onclick="acceptProject('${p.id}')">✅ Accept & Sign Contract</button>` : '';
  const cancelBtn = isClient && ['open', 'pending'].includes(p.status) ? `<button class="btn btn-danger btn-sm" onclick="cancelProject('${p.id}')">Cancel Project</button>` : '';
  const disputeBtn = (isClient || isMyFreelancer) && p.status === 'active' && p.dispute_status !== 'open'
    ? `<button class="btn btn-outline btn-sm" style="color:var(--red);border-color:var(--red);" onclick="openDisputeModal('${p.id}')">⚖️ Raise Dispute</button>` : '';
  const contract = p.contract;

  document.getElementById('projectDetailContent').innerHTML = `
    <div class="page-header">
      <div>
        <button class="btn btn-outline btn-sm" onclick="showPage('dashboard')" style="margin-bottom:12px;">← Dashboard</button>
        <h2>${p.title} ${p.completion_guarantee ? '<span class="badge badge-verified">🛡️ Guaranteed</span>' : ''}</h2>
        <p class="text-muted">ID: ${p.id} · Posted by ${p.client_name}</p>
      </div>
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
        <span class="badge badge-${p.status}" style="font-size:0.8rem;padding:6px 12px;">${p.status.toUpperCase()}</span>
        ${p.dispute_status === 'open' ? '<span class="badge badge-dispute" style="font-size:0.8rem;padding:6px 12px;">⚖️ DISPUTE OPEN</span>' : ''}
        ${acceptBtn}${cancelBtn}${disputeBtn}
      </div>
    </div>

    <div class="detail-grid">
      <div>
        <div class="card">
          <div class="section-label" style="margin-bottom:12px;">Project Brief</div>
          <p style="font-size:0.85rem;line-height:1.7;">${p.description || 'No description.'}</p>
          ${p.deadline ? `<p class="text-muted mt-16" style="font-size:0.75rem;">📅 Deadline: ${p.deadline}</p>` : ''}
        </div>

        <div class="card">
          <div class="section-label" style="margin-bottom:16px;">Milestones</div>
          ${milestonesHTML}
          <div class="progress-bar" style="margin-top:16px;"><div class="progress-fill" style="width:${pct}%"></div></div>
          <div class="text-muted mt-8">${done} of ${p.milestones.length} complete · $${Number(p.released).toFixed(2)} released</div>
        </div>

        <!-- CHAT -->
        ${(isClient || isMyFreelancer) ? `
        <div class="card">
          <div class="section-label" style="margin-bottom:12px;">Project Chat</div>
          <div class="chat-box" id="chatBox"></div>
          <div class="chat-input-row" style="margin-top:8px;">
            <input type="text" id="chatInput" placeholder="Type a message..." onkeydown="if(event.key==='Enter')sendMessage('${p.id}')">
            <button class="btn btn-amber" onclick="sendMessage('${p.id}')">Send</button>
          </div>
        </div>` : ''}

        <!-- CONTRACT -->
        ${(isClient || isMyFreelancer) ? `
        <div class="card">
          <div class="section-label" style="margin-bottom:12px;">Contract</div>
          <div class="contract-preview">${contract ? contract.terms : 'No contract.'}</div>
          <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">
            <a class="btn btn-outline btn-sm" href="/api/projects/${p.id}/contract" target="_blank">↓ Download</a>
            ${contract ? `<span class="text-muted" style="font-size:0.75rem;padding-top:8px;">
              Client: ${contract.signed_client ? '✅ Signed' : '⏳'} &nbsp;
              Freelancer: ${contract.signed_freelancer ? '✅ Signed' : '⏳ Awaiting'}
            </span>` : ''}
          </div>
        </div>` : ''}
      </div>

      <!-- RIGHT SIDEBAR -->
      <div>
        <div class="escrow-box">
          <div class="escrow-amount">$${Number(p.total).toFixed(2)}</div>
          <div class="escrow-meta">Total project value</div>
          <hr style="border-color:var(--amber-dim);margin:16px 0;">
          <div class="flex justify-between text-muted" style="font-size:0.75rem;margin-bottom:6px;"><span>Released</span><span class="text-green">$${Number(p.released).toFixed(2)}</span></div>
          <div class="flex justify-between text-muted" style="font-size:0.75rem;margin-bottom:6px;"><span>Locked</span><span class="text-amber">$${(Number(p.total) - Number(p.released)).toFixed(2)}</span></div>
          <div class="flex justify-between text-muted" style="font-size:0.75rem;"><span>Platform Fee (10%)</span><span>$${(Number(p.total) * 0.10).toFixed(2)}</span></div>
          ${p.completion_guarantee ? `<div class="flex justify-between text-muted" style="font-size:0.75rem;margin-top:6px;"><span>🛡️ Guarantee Fee</span><span>$${Number(p.guarantee_fee).toFixed(2)}</span></div>` : ''}
        </div>

        <div class="card">
          <div class="section-label" style="margin-bottom:12px;">Parties</div>
          <div style="font-size:0.78rem;margin-bottom:12px;">
            <div class="text-muted">Client</div>
            <div class="bold">${p.client_name}</div>
          </div>
          <div style="font-size:0.78rem;">
            <div class="text-muted">Freelancer</div>
            <div class="bold">${p.freelancer_name || p.freelancer_email || '<span style="color:var(--green)">Open</span>'}</div>
            <span class="badge ${p.freelancer_accepted ? 'badge-complete' : 'badge-pending'}" style="margin-top:6px;display:inline-block;">${p.freelancer_accepted ? '✅ Contract Signed' : '⏳ Awaiting'}</span>
          </div>
        </div>

        <div class="card">
          <div class="section-label" style="margin-bottom:12px;">Activity</div>
          <div id="projectLogs" style="font-size:0.78rem;">Loading...</div>
        </div>
      </div>
    </div>`;

  // Load chat and logs
  if (isClient || isMyFreelancer) loadChat(p.id);
  api('/api/activity?project=' + id).then(r => {
    const logs = r.logs || [];
    document.getElementById('projectLogs').innerHTML = logs.slice(0, 8).map(l => `
      <div style="padding:8px 0;border-bottom:1px solid var(--border);">
        <div class="text-muted" style="font-size:0.65rem;">${l.time.slice(0, 16).replace('T', ' ')}</div>
        <div style="font-size:0.78rem;margin-top:2px;">${l.text}</div>
      </div>`).join('') || '<div class="text-muted">No activity yet.</div>';
  });
}

// ── CHAT ─────────────────────────────────────
async function loadChat(pid) {
  const r = await api('/api/projects/' + pid + '/messages');
  const box = document.getElementById('chatBox');
  if (!box) return;
  const msgs = r.messages || [];
  if (!msgs.length) { box.innerHTML = '<div style="color:var(--muted);font-size:0.78rem;text-align:center;margin:auto;">No messages yet. Start the conversation.</div>'; return; }
  box.innerHTML = msgs.map(m => `
    <div class="chat-msg ${m.sender_id === currentUser.id ? 'mine' : 'theirs'}">
      <div class="chat-sender">${m.sender_id === currentUser.id ? 'You' : m.sender_name}</div>
      ${m.content}
      <div class="chat-time">${m.created_at.slice(11, 16)}</div>
    </div>`).join('');
  box.scrollTop = box.scrollHeight;
}

async function sendMessage(pid) {
  const input = document.getElementById('chatInput');
  const content = input.value.trim();
  if (!content) return;
  input.value = '';
  const r = await api('/api/projects/' + pid + '/messages', 'POST', { content });
  if (r.ok) loadChat(pid);
}

// ── MILESTONE SUBMIT ─────────────────────────
function openSubmitModal(projId, msId, msTitle) {
  submitProjId = projId; submitMsId = msId;
  document.getElementById('submitMsTitle').value = msTitle;
  document.getElementById('submitNote').value = '';
  document.getElementById('submitAlert').innerHTML = '';
  clearFile();
  openModal('submitModal');
}

function handleFileSelect(input) { if (input.files && input.files[0]) setFile(input.files[0]); }
function handleDrop(e) {
  e.preventDefault();
  document.getElementById('uploadZone').classList.remove('dragover');
  if (e.dataTransfer.files && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
}
function setFile(file) {
  if (file.size > 5 * 1024 * 1024) { showAlert('submitAlert', 'File too large. Max 5MB.', 'err'); return; }
  selectedFile = file;
  document.getElementById('uploadZone').style.display = 'none';
  document.getElementById('filePreview').style.display = 'flex';
  document.getElementById('fileName').textContent = file.name;
  document.getElementById('fileSize').textContent = (file.size / 1024).toFixed(1) + ' KB';
}
function clearFile() {
  selectedFile = null;
  document.getElementById('fileInput').value = '';
  document.getElementById('uploadZone').style.display = 'block';
  document.getElementById('filePreview').style.display = 'none';
}

async function doSubmitMilestone() {
  const note = document.getElementById('submitNote').value.trim();
  let fileData = null, fileName = null, fileType = null;
  if (selectedFile) {
    try {
      fileData = await new Promise((res, rej) => {
        const reader = new FileReader();
        reader.onload = e => res(e.target.result.split(',')[1]);
        reader.onerror = rej;
        reader.readAsDataURL(selectedFile);
      });
      fileName = selectedFile.name;
      fileType = selectedFile.type || 'application/octet-stream';
    } catch (e) { showAlert('submitAlert', 'Failed to read file.', 'err'); return; }
  }
  const r = await api(`/api/projects/${submitProjId}/milestones/${submitMsId}/submit`, 'POST',
    { note, file_name: fileName, file_data: fileData, file_type: fileType });
  if (r.ok) { closeModal('submitModal'); viewProject(submitProjId); }
  else showAlert('submitAlert', r.error || 'Submission failed', 'err');
}

// ── PROJECT ACTIONS ──────────────────────────
async function acceptProject(id) { const r = await api('/api/projects/' + id + '/accept', 'POST'); if (r.ok) viewProject(id); }
async function cancelProject(id) {
  if (!confirm('Cancel project? Remaining escrow will be returned.')) return;
  const r = await api('/api/projects/' + id + '/cancel', 'POST');
  if (r.ok) showPage('dashboard');
}
async function approveMilestone(pId, mId) { const r = await api(`/api/projects/${pId}/milestones/${mId}/approve`, 'POST'); if (r.ok) { viewProject(pId); updateStats(); } }
async function rejectMilestone(pId, mId) { const r = await api(`/api/projects/${pId}/milestones/${mId}/reject`, 'POST'); if (r.ok) viewProject(pId); }

// ── DISPUTE ───────────────────────────────────
function openDisputeModal(pid) {
  disputeProjId = pid;
  document.getElementById('disputeReason').value = '';
  document.getElementById('disputeAlert').innerHTML = '';
  openModal('disputeModal');
}
async function doRaiseDispute() {
  const reason = document.getElementById('disputeReason').value.trim();
  if (!reason) { showAlert('disputeAlert', 'Please describe the issue', 'err'); return; }
  const r = await api(`/api/projects/${disputeProjId}/dispute`, 'POST', { reason });
  if (r.ok) { showAlert('disputeAlert', 'Dispute raised. Platform will mediate within 48 hours.', 'ok'); setTimeout(() => { closeModal('disputeModal'); viewProject(disputeProjId); }, 2000); }
  else showAlert('disputeAlert', r.error || 'Failed', 'err');
}

// ── VERIFICATION ──────────────────────────────
async function handleIdUpload(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  const reader = new FileReader();
  reader.onload = async (e) => {
    const doc_data = e.target.result.split(',')[1];
    const r = await api('/api/verify-id', 'POST', { doc_data, doc_name: file.name });
    if (r.ok) {
      showAlert('verifyAlert', '✅ ID verified successfully!', 'ok');
      currentUser.id_verified = 1;
      setTimeout(() => closeModal('verifyModal'), 2000);
    } else showAlert('verifyAlert', r.error || 'Verification failed', 'err');
  };
  reader.readAsDataURL(file);
}

// ── SKILL TEST ────────────────────────────────
const skillQuestions = {
  'JavaScript': [
    { q: 'What does `typeof null` return in JavaScript?', options: ['null', 'object', 'undefined', 'string'], correct: 1 },
    { q: 'Which method adds an element to the end of an array?', options: ['push()', 'pop()', 'shift()', 'unshift()'], correct: 0 },
    { q: 'What is a closure?', options: ['A loop', 'A function with access to its outer scope', 'An error handler', 'A class'], correct: 1 },
    { q: '`===` checks:', options: ['Value only', 'Type only', 'Value and type', 'Neither'], correct: 2 },
    { q: 'What does `async/await` do?', options: ['Speeds up code', 'Handles promises synchronously', 'Creates threads', 'Compiles code'], correct: 1 },
  ],
  'Python': [
    { q: 'What is the output of `print(type([]))`?', options: ["<class 'list'>", "<class 'array'>", "list", "Array"], correct: 0 },
    { q: 'Which keyword defines a function in Python?', options: ['function', 'def', 'func', 'define'], correct: 1 },
    { q: 'What does `len("hello")` return?', options: ['4', '5', '6', 'Error'], correct: 1 },
    { q: 'How do you start a comment in Python?', options: ['//', '#', '/*', '--'], correct: 1 },
    { q: 'What is a list comprehension?', options: ['A for loop', 'A concise way to create lists', 'A data type', 'An import'], correct: 1 },
  ],
  'default': [
    { q: 'What does API stand for?', options: ['Application Programming Interface', 'Automated Process Integration', 'Applied Program Index', 'None'], correct: 0 },
    { q: 'What is version control?', options: ['Controlling app versions', 'Tracking code changes over time', 'A deployment tool', 'A testing method'], correct: 1 },
    { q: 'What does HTTP stand for?', options: ['HyperText Transfer Protocol', 'High Tech Transfer Process', 'HyperText Type Protocol', 'None'], correct: 0 },
    { q: 'What is a database?', options: ['A file system', 'An organized collection of data', 'A programming language', 'A server'], correct: 1 },
    { q: 'What is debugging?', options: ['Writing code', 'Finding and fixing errors', 'Deploying apps', 'Testing UI'], correct: 1 },
  ]
};
let currentQuizAnswers = [], currentQuizSkill = '';

function openSkillModal(skill = 'JavaScript') {
  currentQuizSkill = skill;
  currentQuizAnswers = [];
  const questions = skillQuestions[skill] || skillQuestions['default'];
  document.getElementById('skillAlert').innerHTML = '';
  document.getElementById('skillTestContent').innerHTML = `
    <h4 style="margin-bottom:16px;font-family:var(--sans);">${skill} — 5 Questions</h4>
    ${questions.map((q, i) => `
      <div style="margin-bottom:20px;">
        <div class="quiz-question"><strong>Q${i + 1}:</strong> ${q.q}</div>
        ${q.options.map((opt, j) => `
          <label class="quiz-option" id="opt-${i}-${j}">
            <input type="radio" name="q${i}" value="${j}" style="display:none;" onchange="selectAnswer(${i},${j},${q.correct})">
            ${opt}
          </label>`).join('')}
      </div>`).join('')}
    <button class="btn btn-amber w-full" onclick="submitSkillTest()">Submit Test</button>`;
  openModal('skillModal');
}

function selectAnswer(qi, ai, correct) {
  document.querySelectorAll(`[id^="opt-${qi}-"]`).forEach(el => el.classList.remove('selected'));
  document.getElementById(`opt-${qi}-${ai}`).classList.add('selected');
  currentQuizAnswers[qi] = { answer: ai, correct: ai === correct };
}

async function submitSkillTest() {
  const questions = skillQuestions[currentQuizSkill] || skillQuestions['default'];
  if (currentQuizAnswers.filter(a => a !== undefined).length < questions.length) {
    showAlert('skillAlert', 'Please answer all questions', 'err'); return;
  }
  const r = await api('/api/skill-test', 'POST', { skill: currentQuizSkill, answers: currentQuizAnswers });
  if (r.ok) {
    const msg = r.passed
      ? `🎉 Passed! Score: ${r.score}/100. "${currentQuizSkill}" added to your profile.`
      : `Score: ${r.score}/100. Need 70+ to pass. Try again after 24 hours.`;
    showAlert('skillAlert', msg, r.passed ? 'ok' : 'err');
    if (r.passed) { currentUser.skills = (currentUser.skills ? currentUser.skills + ', ' : '') + currentQuizSkill; }
    setTimeout(() => closeModal('skillModal'), 3000);
  }
}

// ── STATS ────────────────────────────────────
async function updateStats() {
  const r = await api('/api/stats');
  if (r) {
    document.getElementById('statProjects').textContent = r.projects;
    document.getElementById('statEscrow').textContent = '$' + Number(r.escrow || 0).toFixed(0);
    document.getElementById('statCompleted').textContent = r.completed;
    document.getElementById('statFreelancers').textContent = r.freelancers || 0;
  }
}

// ── FUNDS ─────────────────────────────────────
async function topUp(amount) {
  const r = await api('/api/topup', 'POST', { amount });
  if (r.ok) {
    showAlert('topupAlert', `$${amount.toLocaleString()} added!`, 'ok');
    setTimeout(() => { closeModal('topupModal'); if (currentTab === 'profile') switchTab('profile'); }, 1500);
  } else showAlert('topupAlert', r.error || 'Failed', 'err');
}

// ── MODALS ────────────────────────────────────
function openModal(id) { document.getElementById(id).classList.add('active'); }
function closeModal(id) { document.getElementById(id).classList.remove('active'); }

// ── ALERTS ────────────────────────────────────
function showAlert(id, msg, type) {
  const el = document.getElementById(id);
  if (el) { el.innerHTML = `<div class="alert alert-${type}">${msg}</div>`; setTimeout(() => { if (el) el.innerHTML = ''; }, 5000); }
}

// ── INIT ──────────────────────────────────────
api('/api/me').then(r => {
  if (r.ok) { currentUser = r.user; updateNav(); }
  updateStats();
});
