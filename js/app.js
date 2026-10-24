import {
  AUDIENCES, STATUSES, PROJECT_TYPES, GOALS,
  loadSections, saveSection, deleteSection,
  loadIdeas, getIdea, newIdea, saveIdea, deleteIdea, answerQuestion,
} from './model.js';
import { buildExport, download, importData, stamp, getMeta, setMeta } from './transfer.js';
import * as cloud from './sync.js';
import * as drive from './drive.js';

const app = document.getElementById('app');
const BACKUP_REMINDER_DAYS = 7;

// ---------- helpers ----------

const esc = (s = '') =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

const fmtDate = (iso) =>
  iso ? new Date(iso).toLocaleString('ar', { dateStyle: 'medium', timeStyle: 'short' }) : '';

const options = (list, selected, empty) =>
  (empty !== undefined ? `<option value="">${esc(empty)}</option>` : '') +
  list.map(([v, label]) => `<option value="${esc(v)}" ${v === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');

const pairs = (arr) => arr.map((x) => [x, x]);

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), 2500);
}

function debounce(fn, ms) {
  let t;
  const wrapped = (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
  wrapped.flush = (...a) => {
    clearTimeout(t);
    return fn(...a);
  };
  return wrapped;
}

function parseHash() {
  const [path, query = ''] = location.hash.slice(1).split('?');
  return { parts: path.split('/').filter(Boolean), params: new URLSearchParams(query) };
}

// ---------- list view ----------

async function renderList(params) {
  const [ideas, sections] = await Promise.all([loadIdeas(), loadSections()]);
  const f = {
    s: params.get('s') || '',
    a: params.get('a') || '',
    st: params.get('st') || '',
    q: params.get('q') || '',
  };
  const secById = Object.fromEntries(sections.map((s) => [s.id, s]));
  const q = f.q.trim().toLowerCase();
  const shown = ideas.filter(
    (i) =>
      (!f.s || i.sectionId === f.s) &&
      (!f.a || i.audience === f.a) &&
      (f.st ? i.status === f.st : i.status !== 'archived') &&
      (!q || `${i.title} ${i.body} ${(i.tags || []).join(' ')}`.toLowerCase().includes(q))
  );
  const count = (id) => ideas.filter((i) => i.sectionId === id && i.status !== 'archived').length;
  const link = (patch) => {
    const p = new URLSearchParams({ ...f, ...patch });
    for (const [k, v] of [...p]) if (!v) p.delete(k);
    return `#/?${p}`;
  };

  app.innerHTML = `
    ${await backupBanner()}
    <div class="layout">
      <aside class="sections">
        <a class="chip ${!f.s ? 'active' : ''}" href="${link({ s: '' })}">📚 الكل <span>${ideas.length}</span></a>
        ${sections
          .map((s) => `<a class="chip ${f.s === s.id ? 'active' : ''}" href="${link({ s: s.id })}">${esc(s.icon || '📁')} ${esc(s.name)} <span>${count(s.id)}</span></a>`)
          .join('')}
        <a class="chip add" href="#/settings">+ قسم</a>
      </aside>
      <section class="list">
        <form class="filters" id="filters">
          <input type="search" name="q" placeholder="ابحث في أفكارك…" value="${esc(f.q)}">
          <select name="a">${options(Object.entries(AUDIENCES), f.a, 'الجميع')}</select>
          <select name="st">${options(Object.entries(STATUSES), f.st, 'كل الحالات')}</select>
        </form>
        ${
          shown.length
            ? `<div class="cards">${shown.map((i) => card(i, secById[i.sectionId])).join('')}</div>`
            : `<div class="empty">
                 <p>${ideas.length ? 'لا توجد أفكار تطابق البحث.' : 'لا توجد أفكار بعد. ابدأ بكتابة أول فكرة!'}</p>
                 <a class="btn primary" href="#/new${f.s ? `?s=${f.s}` : ''}">+ فكرة جديدة</a>
               </div>`
        }
      </section>
    </div>`;

  const form = document.getElementById('filters');
  const apply = () => {
    const d = Object.fromEntries(new FormData(form));
    history.replaceState(null, '', link(d));
  };
  form.addEventListener('change', () => { apply(); route(); });
  form.addEventListener('input', debounce(() => { apply(); route(true); }, 300));
  form.addEventListener('submit', (e) => e.preventDefault());
}

function card(i, section) {
  const pending = (i.analysis?.questions || []).filter((q) => q.answer === undefined || q.answer === null).length;
  return `
    <a class="card" href="#/idea/${esc(i.id)}">
      <h3>${esc(i.title || 'فكرة بلا عنوان')}</h3>
      <p>${esc((i.body || '').slice(0, 140))}${(i.body || '').length > 140 ? '…' : ''}</p>
      <div class="meta">
        ${section ? `<span class="tag">${esc(section.icon || '')} ${esc(section.name)}</span>` : ''}
        <span class="tag">${AUDIENCES[i.audience] || ''}</span>
        <span class="tag status-${esc(i.status)}">${STATUSES[i.status] || ''}</span>
        ${i.analysis ? `<span class="tag ai">🤖 محللة${i.analysis.popularity?.score != null ? ` · ${i.analysis.popularity.score}%` : ''}</span>` : ''}
        ${pending ? `<span class="tag warn">❓ ${pending} سؤال بانتظارك</span>` : ''}
      </div>
    </a>`;
}

async function backupBanner() {
  const last = await getMeta('lastBackupAt');
  const ideas = await loadIdeas();
  if (!ideas.length) return '';
  const days = last ? (Date.now() - new Date(last)) / 86400000 : Infinity;
  if (days < BACKUP_REMINDER_DAYS) return '';
  const button = drive.isConfigured()
    ? '<button class="btn small" data-action="drive-backup">رفع نسخة إلى Google Drive</button>'
    : '<button class="btn small" data-action="backup">حفظ نسخة الآن</button>';
  return `<div class="banner">🛟 ${last ? `آخر نسخة احتياطية قبل ${Math.floor(days)} يوماً.` : 'لم تأخذ نسخة احتياطية بعد.'}
    ${button}</div>`;
}

// ---------- editor view ----------

async function renderEditor(id, params) {
  const sections = await loadSections();
  let idea = id ? await getIdea(id) : newIdea(params.get('s'));
  if (!idea || idea.deleted) {
    app.innerHTML = `<div class="empty"><p>الفكرة غير موجودة.</p><a class="btn" href="#/">العودة</a></div>`;
    return;
  }
  const isNew = !id;
  let savedOnce = false;

  app.innerHTML = `
    <div class="editor">
      <div class="editor-head">
        <a href="#/" class="btn ghost">→ رجوع</a>
        <span class="saved" id="saved">${isNew ? '' : `آخر تعديل: ${fmtDate(idea.updatedAt)}`}</span>
      </div>
      <form id="idea-form" class="idea-form">
        <input name="title" class="title" placeholder="عنوان الفكرة" value="${esc(idea.title)}" autocomplete="off">
        <textarea name="body" rows="10" placeholder="اكتب فكرتك بالتفصيل: ما المشكلة؟ ما الحل؟ لمن؟ لماذا الآن؟">${esc(idea.body)}</textarea>
        <div class="grid">
          <label>القسم<select name="sectionId">${options(sections.map((s) => [s.id, `${s.icon || ''} ${s.name}`]), idea.sectionId, 'بدون قسم')}</select></label>
          <label>نوع المشروع<select name="projectType">${options(pairs(PROJECT_TYPES), idea.projectType, '—')}</select></label>
          <label>الهدف<select name="goal">${options(pairs(GOALS), idea.goal, '—')}</select></label>
          <label>لمن؟<select name="audience">${options(Object.entries(AUDIENCES), idea.audience)}</select></label>
          <label>الحالة<select name="status">${options(Object.entries(STATUSES), idea.status)}</select></label>
          <label>وسوم (افصل بفاصلة)<input name="tags" value="${esc((idea.tags || []).join('، '))}" placeholder="مثال: ذكاء اصطناعي، تعليم"></label>
        </div>
      </form>
      <div class="actions">
        <button class="btn" data-action="export-one">🤖 تصدير هذه الفكرة لـ Claude</button>
        ${isNew ? '' : '<button class="btn danger" data-action="delete">حذف</button>'}
      </div>
      <div id="analysis">${analysisView(idea)}</div>
      <div id="versions">${versionsView(idea)}</div>
    </div>`;

  const form = document.getElementById('idea-form');
  const readForm = () => {
    const d = Object.fromEntries(new FormData(form));
    d.tags = d.tags.split(/[,،]/).map((t) => t.trim()).filter(Boolean);
    return d;
  };
  const persist = debounce(async () => {
    const d = readForm();
    if (isNew && !savedOnce && !d.title.trim() && !d.body.trim()) return;
    // Nothing changed: don't bump updatedAt, or this device would win sync conflicts it shouldn't.
    if (Object.keys(d).every((k) => JSON.stringify(d[k]) === JSON.stringify(idea[k] ?? (k === 'tags' ? [] : '')))) return;
    idea = await saveIdea({ ...idea, ...d });
    savedOnce = true;
    if (!form.isConnected) return; // saved while leaving the page
    document.getElementById('saved').textContent = `✓ تم الحفظ ${fmtDate(idea.updatedAt)}`;
    document.getElementById('versions').innerHTML = versionsView(idea);
    if (isNew && location.hash.startsWith('#/new')) history.replaceState(null, '', `#/idea/${idea.id}`);
  }, 700);
  form.addEventListener('input', () => persist());
  form.addEventListener('change', () => persist());
  current.flush = () => persist.flush();

  app.querySelector('[data-action="export-one"]').onclick = async () => {
    await persist.flush();
    download(await buildExport({ onlyIds: [idea.id] }), `idea-${stamp()}.json`);
    toast('تم التصدير. أرسل الملف إلى Claude ليحلله.');
  };
  const del = app.querySelector('[data-action="delete"]');
  if (del)
    del.onclick = async () => {
      if (!confirm('حذف هذه الفكرة؟')) return;
      await deleteIdea(idea.id);
      location.hash = '#/';
    };

  bindAnalysis(() => idea, (updated) => (idea = updated));
}

function analysisView(idea) {
  const a = idea.analysis;
  if (!a) {
    return `<div class="panel muted">
      <h2>🤖 تحليل Claude</h2>
      <p>لم تُحلَّل هذه الفكرة بعد. صدّرها وأرسلها إلى Claude، ثم استورد الملف الذي يرجعه من صفحة الإعدادات.</p>
    </div>`;
  }
  const list = (title, items) =>
    items?.length ? `<h3>${title}</h3><ul>${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
  const pop = a.popularity;
  return `<div class="panel">
    <h2>🤖 تحليل Claude <small>${fmtDate(a.at)}</small></h2>
    ${a.summary ? `<p class="summary">${esc(a.summary)}</p>` : ''}
    ${
      pop?.score != null
        ? `<div class="popularity">
            <div class="meter"><div style="width:${Math.max(0, Math.min(100, Number(pop.score)))}%"></div></div>
            <strong>${esc(pop.score)}%</strong> ${esc(pop.label || 'نسبة الرواج المتوقعة')}
            ${pop.note ? `<p>${esc(pop.note)}</p>` : ''}
          </div>`
        : ''
    }
    ${
      a.similar?.length
        ? `<h3>مشاريع مشابهة موجودة</h3><ul>${a.similar
            .map((s) => `<li>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a>` : esc(s.name)}${s.note ? ` — ${esc(s.note)}` : ''}</li>`)
            .join('')}</ul>`
        : ''
    }
    ${list('نقاط القوة', a.strengths)}
    ${list('تحسينات مقترحة', a.improvements)}
    ${list('أشياء ربما فاتتك', a.missed)}
    ${list('اقتراحات إضافية', a.suggestions)}
    ${
      a.questions?.length
        ? `<h3>أسئلة لك</h3><div class="questions">${a.questions.map(questionView).join('')}</div>
           <p class="hint">بعد الإجابة صدّر الفكرة مرة أخرى وأرسلها إلى Claude ليكمل التحليل.</p>`
        : ''
    }
  </div>`;
}

function questionView(q) {
  const yesno = q.type !== 'text';
  return `<div class="question" data-q="${esc(q.id)}">
    <p>${esc(q.text)}</p>
    ${
      yesno
        ? `<div class="yesno">
            <button class="btn small ${q.answer === 'yes' ? 'on' : ''}" data-answer="yes">نعم</button>
            <button class="btn small ${q.answer === 'no' ? 'on' : ''}" data-answer="no">لا</button>
            <button class="btn small ${q.answer === 'unsure' ? 'on' : ''}" data-answer="unsure">لست متأكداً</button>
          </div>`
        : ''
    }
    <textarea rows="${yesno ? 2 : 4}" placeholder="${yesno ? 'إجابة أطول (اختياري)…' : 'اكتب إجابتك…'}">${esc(yesno ? q.note || '' : q.answer || '')}</textarea>
  </div>`;
}

function bindAnalysis(getIdeaState, setIdeaState) {
  const box = document.getElementById('analysis');
  box.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-answer]');
    if (!btn) return;
    const qid = btn.closest('[data-q]').dataset.q;
    const updated = await answerQuestion(getIdeaState().id, qid, btn.dataset.answer);
    setIdeaState(updated);
    btn.parentElement.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b === btn));
  });
  const saveText = debounce(async (ta) => {
    const qEl = ta.closest('[data-q]');
    const q = getIdeaState().analysis.questions.find((x) => x.id === qEl.dataset.q);
    const updated =
      q.type === 'text'
        ? await answerQuestion(getIdeaState().id, q.id, ta.value)
        : await answerQuestion(getIdeaState().id, q.id, undefined, ta.value);
    setIdeaState(updated);
  }, 600);
  box.addEventListener('input', (e) => {
    if (e.target.matches('textarea')) saveText(e.target);
  });
}

function versionsView(idea) {
  if (!idea.versions?.length) return '';
  return `<details class="panel">
    <summary>🕓 النسخ السابقة (${idea.versions.length})</summary>
    ${idea.versions
      .map(
        (v, n) => `<div class="version">
          <div><strong>${esc(v.title || 'بلا عنوان')}</strong> <small>${fmtDate(v.at)}</small>
          <button class="btn small" data-restore="${n}">استرجاع</button></div>
          <p>${esc(v.body)}</p>
        </div>`
      )
      .join('')}
  </details>`;
}

document.addEventListener('click', async (e) => {
  const r = e.target.closest('[data-restore]');
  if (!r) return;
  const id = parseHash().parts[1];
  const idea = await getIdea(id);
  const v = idea.versions[Number(r.dataset.restore)];
  if (!v || !confirm('استرجاع هذه النسخة؟ النص الحالي سيُحفظ في السجل.')) return;
  await saveIdea({ ...idea, title: v.title, body: v.body, lastSnapshotAt: null });
  toast('تم الاسترجاع');
  route();
});

// ---------- settings view ----------

async function renderSettings() {
  const sections = await loadSections();
  const last = await getMeta('lastBackupAt');
  app.innerHTML = `
    <div class="settings">
      <a href="#/" class="btn ghost">→ رجوع</a>

      <div class="panel">
        <h2>📁 الأقسام</h2>
        <div class="section-rows">
          ${sections
            .map(
              (s) => `<form class="section-row" data-id="${esc(s.id)}">
                <input name="icon" value="${esc(s.icon || '')}" maxlength="4" class="icon-input">
                <input name="name" value="${esc(s.name)}" required>
                <button class="btn small">حفظ</button>
                <button type="button" class="btn small danger" data-del="${esc(s.id)}">حذف</button>
              </form>`
            )
            .join('')}
        </div>
        <form class="section-row" id="new-section">
          <input name="icon" placeholder="📁" maxlength="4" class="icon-input">
          <input name="name" placeholder="اسم قسم جديد" required>
          <button class="btn small primary">إضافة</button>
        </form>
      </div>

      <div class="panel">
        <h2>🤖 تبادل الأفكار مع Claude</h2>
        <p>صدّر أفكارك وأرسل الملف إلى Claude. سيعيد لك ملفاً فيه التحليل والأسئلة، استورده هنا. تعديلاتك الأحدث لا تُستبدل أبداً.</p>
        <div class="row">
          <button class="btn" data-action="export-all">تصدير كل الأفكار</button>
          <label class="btn primary">استيراد ملف من Claude<input type="file" accept="application/json,.json" id="import" hidden></label>
        </div>
      </div>

      ${await syncPanel()}

      ${await drivePanel()}

      <div class="panel">
        <h2>💾 ملف نسخة احتياطية</h2>
        <p>آخر نسخة احتياطية: <strong>${last ? fmtDate(last) : 'لا توجد بعد'}</strong></p>
        <p>يحفظ كل أفكارك في ملف على هذا الجهاز. تستطيع استرجاعه بزر "استيراد ملف" في الأعلى.</p>
        <button class="btn" data-action="backup">تنزيل ملف نسخة احتياطية</button>
      </div>
    </div>`;

  bindSyncPanel();
  bindDrivePanel();

  app.querySelectorAll('.section-row[data-id]').forEach((f) =>
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const d = Object.fromEntries(new FormData(f));
      await saveSection({ id: f.dataset.id, ...d });
      toast('تم حفظ القسم');
    })
  );
  app.querySelectorAll('[data-del]').forEach((b) =>
    b.addEventListener('click', async () => {
      if (!confirm('حذف القسم؟ الأفكار التي فيه لن تُحذف.')) return;
      await deleteSection(b.dataset.del);
      route();
    })
  );
  document.getElementById('new-section').addEventListener('submit', async (e) => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    await saveSection({ name: d.name, icon: d.icon || '📁' });
    route();
  });
  app.querySelector('[data-action="export-all"]').onclick = async () => {
    download(await buildExport(), `ideas-for-claude-${stamp()}.json`);
  };
  document.getElementById('import').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const stats = await importData(JSON.parse(await file.text()));
      toast(`تم الاستيراد: ${stats.added} جديدة، ${stats.updated} محدّثة، ${stats.analyzed} تحليل`);
    } catch (err) {
      alert(`تعذّر الاستيراد: ${err.message}`);
    }
    e.target.value = '';
  });
}

async function syncPanel() {
  if (!cloud.isConfigured()) {
    return `<div class="panel muted"><h2>🔄 المزامنة بين الأجهزة</h2><p>لم تُفعَّل بعد.</p></div>`;
  }
  const user = await cloud.currentUser();
  if (!user) {
    return `<div class="panel" id="sync-panel">
      <h2>🔄 المزامنة بين الأجهزة</h2>
      <p>سجّل الدخول بنفس الحساب على الهاتف والكمبيوتر لتظهر أفكارك في كليهما.</p>
      <form id="auth-form" class="auth-form">
        <input name="email" type="email" placeholder="البريد الإلكتروني" required autocomplete="email" dir="ltr">
        <input name="password" type="password" placeholder="كلمة المرور (6 أحرف على الأقل)" required minlength="6" autocomplete="current-password" dir="ltr">
        <div class="row">
          <button class="btn primary" name="mode" value="in">تسجيل الدخول</button>
          <button class="btn" name="mode" value="up">إنشاء حساب</button>
        </div>
      </form>
    </div>`;
  }
  const at = await getMeta('lastSyncAt');
  return `<div class="panel" id="sync-panel">
    <h2>🔄 المزامنة بين الأجهزة</h2>
    <p>مسجّل باسم <strong dir="ltr">${esc(user.email)}</strong></p>
    <p>آخر مزامنة: <strong id="last-sync">${at ? fmtDate(at) : '—'}</strong></p>
    <div class="row">
      <button class="btn primary" data-action="sync-now">مزامنة الآن</button>
      <button class="btn danger" data-action="sign-out">تسجيل الخروج</button>
    </div>
  </div>`;
}

function bindSyncPanel() {
  const form = document.getElementById('auth-form');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const { email, password } = Object.fromEntries(new FormData(form));
      const mode = e.submitter?.value;
      try {
        if (mode === 'up') {
          const needsConfirm = await cloud.signUp(email, password);
          if (needsConfirm) {
            alert('أرسلنا رسالة تأكيد إلى بريدك. افتحها واضغط الرابط، ثم عد إلى هنا وسجّل الدخول.');
            return;
          }
        } else {
          await cloud.signIn(email, password);
        }
        toast('تم تسجيل الدخول وبدأت المزامنة');
        route();
      } catch (err) {
        alert(`تعذّر الدخول: ${err.message}`);
      }
    });
  }
  const now = app.querySelector('[data-action="sync-now"]');
  if (now) now.onclick = () => cloud.sync().then(() => route());
  const out = app.querySelector('[data-action="sign-out"]');
  if (out)
    out.onclick = async () => {
      if (!confirm('تسجيل الخروج؟ أفكارك تبقى على هذا الجهاز وفي حسابك.')) return;
      await cloud.signOut();
      route();
    };
}

async function drivePanel() {
  if (!drive.isConfigured()) {
    return `<div class="panel muted"><h2>☁️ Google Drive</h2><p>لم يُفعَّل بعد.</p></div>`;
  }
  const last = await getMeta('lastDriveBackupAt');
  return `<div class="panel">
    <h2>☁️ نسخ احتياطي إلى Google Drive</h2>
    <p>كل ${drive.BACKUP_EVERY_DAYS} أيام، عند فتح التطبيق، تُرفع نسخة إلى مجلد "Ideas Backup" في حسابك على Drive، وتُحفظ آخر 8 نسخ.</p>
    <p>آخر نسخة على Drive: <strong>${last ? fmtDate(last) : 'لا توجد بعد'}</strong></p>
    <div class="row">
      <button class="btn primary" data-action="drive-backup">رفع نسخة الآن</button>
      <button class="btn" data-action="drive-list">استرجاع من Drive</button>
    </div>
    <div id="drive-files"></div>
  </div>`;
}

function bindDrivePanel() {
  const list = app.querySelector('[data-action="drive-list"]');
  if (!list) return;
  list.onclick = async () => {
    const box = document.getElementById('drive-files');
    box.textContent = 'جارٍ التحميل…';
    try {
      const files = await drive.listBackups();
      box.innerHTML = files.length
        ? files
            .map((f) => `<div class="drive-file"><span>${fmtDate(f.createdTime)}</span>
              <button class="btn small" data-restore-drive="${esc(f.id)}">استرجاع</button></div>`)
            .join('')
        : '<p>لا توجد نسخ بعد.</p>';
    } catch (err) {
      box.textContent = `تعذّر الاتصال بـ Drive: ${err.message}`;
    }
  };
  document.getElementById('drive-files').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-restore-drive]');
    if (!b || !confirm('استرجاع هذه النسخة؟ ستُدمج مع أفكارك الحالية دون حذف شيء أحدث.')) return;
    try {
      const stats = await drive.restoreFromDrive(b.dataset.restoreDrive);
      toast(`تم الاسترجاع: ${stats.added} جديدة، ${stats.updated} محدّثة`);
    } catch (err) {
      alert(`تعذّر الاسترجاع: ${err.message}`);
    }
  });
}

async function driveBackupNow() {
  try {
    toast('جارٍ الرفع إلى Google Drive…');
    await drive.connectDrive();
    await drive.backupToDrive();
    toast('✓ تم رفع النسخة إلى Google Drive');
  } catch (err) {
    alert(`تعذّر الرفع إلى Drive: ${err.message}`);
  }
}

async function backupNow() {
  download(await buildExport(), `ideas-backup-${stamp()}.json`);
  await setMeta('lastBackupAt', new Date().toISOString());
  toast('تم حفظ النسخة الاحتياطية');
}

document.addEventListener('click', (e) => {
  if (e.target.closest('[data-action="backup"]')) backupNow().then(() => route());
  if (e.target.closest('[data-action="drive-backup"]')) driveBackupNow().then(() => route());
});

// ---------- router ----------

const current = { flush: null };

async function route(keepFocus) {
  if (current.flush) {
    await current.flush();
    current.flush = null;
  }
  const { parts, params } = parseHash();
  const focused = keepFocus && document.activeElement?.name;
  const caret = focused && document.activeElement.selectionStart;
  if (parts[0] === 'idea' && parts[1]) await renderEditor(parts[1], params);
  else if (parts[0] === 'new') await renderEditor(null, params);
  else if (parts[0] === 'settings') await renderSettings();
  else await renderList(params);
  if (focused) {
    const el = app.querySelector(`[name="${focused}"]`);
    if (el) {
      el.focus();
      el.setSelectionRange?.(caret, caret);
    }
  }
  if (!keepFocus) window.scrollTo(0, 0);
}

window.addEventListener('hashchange', () => route());
route();

// Show sync state in the top bar, and refresh lists when another device sent changes.
const syncDot = document.getElementById('sync-status');
cloud.syncEvents.addEventListener('status', ({ detail }) => {
  const labels = { syncing: ['⏳', 'جارٍ المزامنة…'], ok: ['✅', 'تمت المزامنة'], error: ['⚠️', `فشلت المزامنة: ${detail.detail}`], idle: ['', ''] };
  const [icon, title] = labels[detail.state];
  syncDot.textContent = icon;
  syncDot.title = title;
  syncDot.hidden = !icon;
  const editing = parseHash().parts[0] === 'idea' || parseHash().parts[0] === 'new';
  if (detail.state === 'ok' && detail.detail.pulled && !editing) route(true);
});
cloud.startSync();
drive.preload();
drive.autoBackup();

if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js');
