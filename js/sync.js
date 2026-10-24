// Sync between devices through Supabase.
// Each device keeps working offline on its own IndexedDB copy. A sync pulls
// records other devices wrote since the last pull and merges them with the same
// rules as a file import (newer edits win, answers are kept), then pushes the
// local records changed since the last push.
import { config } from './config.js';
import { db, changes } from './db.js';
import { importData, getMeta, setMeta, FORMAT, FORMAT_VERSION } from './transfer.js';

const SUPABASE_JS = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm';
const KINDS = ['ideas', 'sections'];
const PERIOD_MS = 60 * 1000;

export const syncEvents = new EventTarget();
export const isConfigured = () => Boolean(config.supabaseUrl && config.supabaseKey);

let clientPromise;
let running = null;
let again = false;
let syncing = false;

function client() {
  if (!clientPromise) {
    clientPromise = import(SUPABASE_JS).then(({ createClient }) =>
      createClient(config.supabaseUrl, config.supabaseKey, { auth: { persistSession: true } })
    );
  }
  return clientPromise;
}

export async function currentUser() {
  if (!isConfigured()) return null;
  const { data } = await (await client()).auth.getSession();
  return data.session?.user || null;
}

export async function signIn(email, password) {
  const { error } = await (await client()).auth.signInWithPassword({ email, password });
  if (error) throw error;
  await sync();
}

// Returns true when Supabase asks the user to confirm the email first.
export async function signUp(email, password) {
  const { data, error } = await (await client()).auth.signUp({
    email,
    password,
    options: { emailRedirectTo: location.origin + location.pathname },
  });
  if (error) throw error;
  if (data.session) await sync();
  return !data.session;
}

export async function signOut() {
  await (await client()).auth.signOut();
  await setMeta('lastPullAt', null);
  await setMeta('lastPushAt', null);
  status('idle');
}

function status(state, detail) {
  syncEvents.dispatchEvent(new CustomEvent('status', { detail: { state, detail } }));
}

async function pull(sb) {
  const since = (await getMeta('lastPullAt')) || '1970-01-01T00:00:00Z';
  const payload = { format: FORMAT, version: FORMAT_VERSION, ideas: [], sections: [] };
  let newest = since;
  const pageSize = 500;
  for (let from = 0; ; from += pageSize) {
    const { data, error } = await sb
      .from('records')
      .select('kind,data,synced_at')
      .gt('synced_at', since)
      .order('synced_at')
      .range(from, from + pageSize - 1);
    if (error) throw error;
    for (const r of data) {
      payload[r.kind]?.push(r.data);
      if (r.synced_at > newest) newest = r.synced_at;
    }
    if (data.length < pageSize) break;
  }
  if (payload.ideas.length || payload.sections.length) await importData(payload);
  await setMeta('lastPullAt', newest);
  return payload.ideas.length + payload.sections.length;
}

async function push(sb) {
  const since = (await getMeta('lastPushAt')) || '';
  const startedAt = new Date().toISOString();
  const rows = [];
  for (const kind of KINDS) {
    for (const rec of await db.all(kind)) {
      const updatedAt = rec.updatedAt || '1970-01-01T00:00:00.000Z';
      if (updatedAt > since) rows.push({ kind, id: rec.id, data: rec, updated_at: updatedAt });
    }
  }
  for (let i = 0; i < rows.length; i += 200) {
    const { error } = await sb.from('records').upsert(rows.slice(i, i + 200), { onConflict: 'user_id,kind,id' });
    if (error) throw error;
  }
  await setMeta('lastPushAt', startedAt);
  return rows.length;
}

// Runs one sync; calls made while one is running are folded into one more run.
export function sync() {
  if (!isConfigured()) return Promise.resolve();
  if (running) {
    again = true;
    return running;
  }
  running = (async () => {
    try {
      do {
        again = false;
        if (!(await currentUser()) || !navigator.onLine) return;
        const sb = await client();
        status('syncing');
        syncing = true;
        let pulled;
        try {
          pulled = await pull(sb);
          await push(sb);
        } finally {
          syncing = false;
        }
        const at = new Date().toISOString();
        await setMeta('lastSyncAt', at);
        status('ok', { at, pulled });
      } while (again);
    } catch (err) {
      console.error('sync failed', err);
      status('error', err.message || String(err));
    } finally {
      running = null;
    }
  })();
  return running;
}

let timer;
function scheduleSoon() {
  clearTimeout(timer);
  timer = setTimeout(sync, 2000);
}

export function startSync() {
  if (!isConfigured()) return;
  changes.addEventListener('change', (e) => {
    if (!syncing && e.detail !== 'meta') scheduleSoon();
  });
  window.addEventListener('online', () => sync());
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') sync();
  });
  setInterval(() => document.visibilityState === 'visible' && sync(), PERIOD_MS);
  client().then((sb) =>
    sb.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_IN') sync();
    })
  );
  sync();
}
