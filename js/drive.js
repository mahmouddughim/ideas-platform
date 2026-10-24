// Weekly backups to the user's own Google Drive, in a folder named "Ideas Backup".
// Uses the drive.file scope: the app can only see the files it created itself.
import { config } from './config.js';
import { buildExport, importData, stamp, getMeta, setMeta } from './transfer.js';

const GIS = 'https://accounts.google.com/gsi/client';
const SCOPE = 'https://www.googleapis.com/auth/drive.file';
const FOLDER = 'Ideas Backup';
const KEEP = 8;
export const BACKUP_EVERY_DAYS = 7;

export const isConfigured = () => Boolean(config.googleClientId);

let gisPromise;
let token = null; // { value, expiresAt }

function loadGis() {
  if (!gisPromise) {
    gisPromise = new Promise((resolve, reject) => {
      const s = Object.assign(document.createElement('script'), { src: GIS, async: true });
      s.onload = () => resolve(window.google.accounts.oauth2);
      s.onerror = () => reject(new Error('تعذّر تحميل خدمة Google'));
      document.head.append(s);
    });
  }
  return gisPromise;
}

// Asks Google for an access token. Must be called from a click the first time
// (browsers block the sign-in popup otherwise); afterwards Google answers silently.
async function getToken() {
  if (token && token.expiresAt > Date.now() + 60_000) return token.value;
  const oauth2 = await loadGis();
  return new Promise((resolve, reject) => {
    const client = oauth2.initTokenClient({
      client_id: config.googleClientId,
      scope: SCOPE,
      prompt: '',
      callback: (res) => {
        if (res.error) return reject(new Error(res.error_description || res.error));
        token = { value: res.access_token, expiresAt: Date.now() + res.expires_in * 1000 };
        resolve(token.value);
      },
      error_callback: (err) => reject(new Error(err.message || err.type || 'تم إلغاء الدخول')),
    });
    client.requestAccessToken();
  });
}

async function api(path, { method = 'GET', body, headers = {}, upload = false, raw = false } = {}) {
  const base = upload ? 'https://www.googleapis.com/upload/drive/v3' : 'https://www.googleapis.com/drive/v3';
  const res = await fetch(base + path, {
    method,
    body,
    headers: { Authorization: `Bearer ${await getToken()}`, ...headers },
  });
  if (res.status === 401) token = null;
  if (!res.ok) throw new Error(`Google Drive: ${res.status} ${await res.text()}`);
  if (raw) return res;
  return res.status === 204 ? null : res.json();
}

const q = (s) => encodeURIComponent(s);

async function folderId() {
  const cached = await getMeta('driveFolderId');
  if (cached) {
    try {
      const f = await api(`/files/${cached}?fields=id,trashed`);
      if (!f.trashed) return f.id;
    } catch {
      // Folder was removed; create a new one below.
    }
  }
  const found = await api(
    `/files?q=${q(`name='${FOLDER}' and mimeType='application/vnd.google-apps.folder' and trashed=false`)}&fields=files(id)`
  );
  let id = found.files[0]?.id;
  if (!id) {
    const created = await api('/files?fields=id', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: FOLDER, mimeType: 'application/vnd.google-apps.folder' }),
    });
    id = created.id;
  }
  await setMeta('driveFolderId', id);
  return id;
}

export async function listBackups() {
  const folder = await folderId();
  const res = await api(
    `/files?q=${q(`'${folder}' in parents and trashed=false`)}&orderBy=createdTime desc&fields=files(id,name,createdTime,size)&pageSize=100`
  );
  return res.files;
}

export async function backupToDrive() {
  const folder = await folderId();
  const data = JSON.stringify(await buildExport(), null, 2);
  const boundary = `b${Math.random().toString(36).slice(2)}`;
  const meta = { name: `ideas-backup-${stamp()}.json`, parents: [folder], mimeType: 'application/json' };
  const body =
    `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${JSON.stringify(meta)}\r\n` +
    `--${boundary}\r\nContent-Type: application/json\r\n\r\n${data}\r\n--${boundary}--`;
  await api('/files?uploadType=multipart&fields=id', {
    method: 'POST',
    upload: true,
    headers: { 'Content-Type': `multipart/related; boundary=${boundary}` },
    body,
  });

  // Keep only the newest KEEP backups.
  const files = await listBackups();
  for (const old of files.slice(KEEP)) await api(`/files/${old.id}`, { method: 'DELETE' });

  const at = new Date().toISOString();
  await setMeta('lastDriveBackupAt', at);
  await setMeta('lastBackupAt', at);
  return at;
}

export async function restoreFromDrive(fileId) {
  const res = await api(`/files/${fileId}?alt=media`, { raw: true });
  return importData(await res.json());
}

export async function isDue() {
  if (!isConfigured()) return false;
  const last = await getMeta('lastDriveBackupAt');
  return !last || Date.now() - new Date(last) > BACKUP_EVERY_DAYS * 86400000;
}

// On app start: if a weekly backup is due and Google already granted access
// before, back up silently. Returns false when a click is needed to sign in.
export async function autoBackup() {
  if (!(await isDue()) || !(await getMeta('driveConnected'))) return !(await isDue());
  try {
    // A blocked popup never calls back, so give up after a few seconds.
    const timeout = new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 8000));
    await Promise.race([backupToDrive(), timeout]);
    return true;
  } catch (err) {
    console.warn('automatic Drive backup needs a click', err);
    return false;
  }
}

// Loads Google's script early so the sign-in popup opens right on the click.
export function preload() {
  if (isConfigured()) loadGis().catch(() => {});
}

export async function connectDrive() {
  await getToken();
  await setMeta('driveConnected', true);
}
