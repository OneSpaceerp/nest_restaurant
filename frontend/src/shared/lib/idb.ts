// Minimal promise wrapper over IndexedDB. One database per app + site + user + register scope, so
// two Nest apps (or two cashiers on one shared tablet) never read each other's data.

export interface StoreSpec {
  name: string
  keyPath: string
  indexes?: { name: string; keyPath: string; unique?: boolean }[]
}

export const SCHEMA_VERSION = 2

export const STORES: StoreSpec[] = [
  { name: 'outbox', keyPath: 'key', indexes: [{ name: 'status', keyPath: 'status' }, { name: 'created', keyPath: 'created' }] },
  { name: 'catalog', keyPath: 'item_code' },
  { name: 'meta', keyPath: 'k' },
  { name: 'carts', keyPath: 'id' },
]

export function dbName(app: string, site: string, user: string, scope = 'default') {
  return `${app}::${site}::${user}::${scope}`
}

export function openDb(name: string, version = SCHEMA_VERSION, stores = STORES): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(name, version)
    req.onupgradeneeded = (ev) => {
      const db = req.result
      const tx = req.transaction!
      for (const s of stores) {
        const store = db.objectStoreNames.contains(s.name) ? tx.objectStore(s.name) : db.createObjectStore(s.name, { keyPath: s.keyPath })
        for (const ix of s.indexes ?? []) if (!store.indexNames.contains(ix.name)) store.createIndex(ix.name, ix.keyPath, { unique: !!ix.unique })
      }
      // migrations keyed by the version we came from; data is transformed, never dropped
      migrate(tx, (ev as IDBVersionChangeEvent).oldVersion)
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
    req.onblocked = () => reject(new Error('Close other Nest tabs to finish updating local storage.'))
  })
}

function migrate(tx: IDBTransaction, from: number) {
  if (from > 0 && from < 2) {
    // v1 outbox rows had no `attempts`; add it so the backoff logic can read every row
    const store = tx.objectStore('outbox')
    store.openCursor().onsuccess = (e) => {
      const cur = (e.target as IDBRequest<IDBCursorWithValue | null>).result
      if (!cur) return
      cur.update({ attempts: 0, ...cur.value })
      cur.continue()
    }
  }
}

function wrap<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export function tx(db: IDBDatabase, store: string, mode: IDBTransactionMode = 'readonly') {
  return db.transaction(store, mode).objectStore(store)
}

export const idb = {
  get: <T>(db: IDBDatabase, store: string, key: IDBValidKey) => wrap<T | undefined>(tx(db, store).get(key)),
  all: <T>(db: IDBDatabase, store: string) => wrap<T[]>(tx(db, store).getAll()),
  put: (db: IDBDatabase, store: string, value: unknown) => wrap(tx(db, store, 'readwrite').put(value)),
  delete: (db: IDBDatabase, store: string, key: IDBValidKey) => wrap(tx(db, store, 'readwrite').delete(key)),
  clear: (db: IDBDatabase, store: string) => wrap(tx(db, store, 'readwrite').clear()),
  async putMany(db: IDBDatabase, store: string, values: unknown[]) {
    const t = db.transaction(store, 'readwrite')
    const s = t.objectStore(store)
    for (const v of values) s.put(v)
    await new Promise<void>((resolve, reject) => {
      t.oncomplete = () => resolve()
      t.onerror = () => reject(t.error)
      t.onabort = () => reject(t.error ?? new Error('Storage is full. Sync or export pending sales before continuing.'))
    })
  },
}

export async function deleteDb(name: string) {
  await new Promise<void>((resolve) => {
    const req = indexedDB.deleteDatabase(name)
    req.onsuccess = req.onerror = req.onblocked = () => resolve()
  })
}
