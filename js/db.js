// Small IndexedDB wrapper. Everything is stored on the device first;
// sync (Supabase) and Drive backups build on top of these stores later.
const DB_NAME = 'ideas-platform';
const DB_VERSION = 1;
const STORES = ['ideas', 'sections', 'meta'];

let dbPromise;

function open() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        for (const name of STORES) {
          if (!db.objectStoreNames.contains(name)) db.createObjectStore(name, { keyPath: 'id' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  return dbPromise;
}

function run(store, mode, fn) {
  return open().then(
    (db) =>
      new Promise((resolve, reject) => {
        const tx = db.transaction(store, mode);
        const result = fn(tx.objectStore(store));
        tx.oncomplete = () => resolve(result && 'result' in result ? result.result : result);
        tx.onerror = () => reject(tx.error);
      })
  );
}

// Fires 'change' after every write, so sync can push local edits.
export const changes = new EventTarget();

function write(store, fn) {
  return run(store, 'readwrite', fn).then((r) => {
    changes.dispatchEvent(new CustomEvent('change', { detail: store }));
    return r;
  });
}

export const db = {
  all: (store) => run(store, 'readonly', (s) => s.getAll()),
  get: (store, id) => run(store, 'readonly', (s) => s.get(id)),
  put: (store, value) => write(store, (s) => s.put(value)),
  putMany: (store, values) =>
    write(store, (s) => {
      for (const v of values) s.put(v);
    }),
  remove: (store, id) => write(store, (s) => s.delete(id)),
};
