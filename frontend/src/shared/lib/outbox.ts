// Durable outbox for commands that must reach the server exactly once (offline cash sales,
// waiter/guest submissions). Each entry keeps its request key forever, so a retry after a lost
// response is resolved by the server's idempotency ledger instead of creating a second sale.
//
// States follow nest_core.fsm.SYNC_ENTRY:
//   Queued → Sending → Acknowledged | Queued (transient) | Ambiguous (lost response) | Rejected
//   Rejected → Needs Review → Acknowledged | Discarded (only by a person, never automatically)

import { ApiError } from './api'
import { idb } from './idb'

export type SyncStatus = 'Queued' | 'Sending' | 'Ambiguous' | 'Acknowledged' | 'Rejected' | 'Needs Review' | 'Discarded'

export interface OutboxEntry<P = unknown> {
  key: string
  kind: string
  payload: P
  status: SyncStatus
  created: number
  attempts: number
  nextAttempt: number
  dependsOn?: string // e.g. a return waits for its sale
  lastError?: string
  result?: unknown
}

export type Sender = (e: OutboxEntry) => Promise<unknown>

const BASE_DELAY = 2000
const MAX_DELAY = 5 * 60_000

export function backoff(attempts: number, rand = Math.random()): number {
  const exp = Math.min(MAX_DELAY, BASE_DELAY * 2 ** Math.max(0, attempts - 1))
  return Math.round(exp * (0.75 + rand * 0.5)) // ±25 % jitter so tills don't retry in lockstep
}

export class Outbox {
  private running = false
  private listeners = new Set<(entries: OutboxEntry[]) => void>()
  private channel: BroadcastChannel | null = null

  constructor(
    private readonly db: IDBDatabase,
    private readonly send: Sender,
    private readonly lockName: string,
    private readonly now = () => Date.now(),
  ) {
    if (typeof BroadcastChannel !== 'undefined') {
      this.channel = new BroadcastChannel(lockName)
      this.channel.onmessage = () => void this.emit()
    }
  }

  async add<P>(key: string, kind: string, payload: P, dependsOn?: string): Promise<OutboxEntry<P>> {
    const existing = await idb.get<OutboxEntry<P>>(this.db, 'outbox', key)
    if (existing) return existing // same key, same command: never enqueue twice
    const entry: OutboxEntry<P> = { key, kind, payload, status: 'Queued', created: this.now(), attempts: 0, nextAttempt: 0, dependsOn }
    try {
      await idb.put(this.db, 'outbox', entry)
    } catch (e) {
      const quota = (e as DOMException)?.name === 'QuotaExceededError'
      throw new Error(quota ? 'This device is out of storage. Export or sync pending sales before continuing.' : String(e))
    }
    await this.emit()
    return entry
  }

  async list(): Promise<OutboxEntry[]> {
    return (await idb.all<OutboxEntry>(this.db, 'outbox')).sort((a, b) => a.created - b.created)
  }

  async pending(): Promise<OutboxEntry[]> {
    return (await this.list()).filter((e) => !['Acknowledged', 'Discarded'].includes(e.status))
  }

  subscribe(fn: (entries: OutboxEntry[]) => void) {
    this.listeners.add(fn)
    void this.list().then(fn)
    return () => this.listeners.delete(fn)
  }

  private async emit() {
    const all = await this.list()
    for (const fn of this.listeners) fn(all)
  }

  private async save(e: OutboxEntry) {
    await idb.put(this.db, 'outbox', e)
    this.channel?.postMessage('changed')
  }

  /** Drain in creation order. One tab at a time (Web Locks), so two tabs never send the same entry. */
  async flush(): Promise<void> {
    if (this.running) return
    const run = async () => {
      this.running = true
      try {
        await this.drain()
      } finally {
        this.running = false
        await this.emit()
      }
    }
    const locks = typeof navigator !== 'undefined' ? (navigator as Navigator).locks : null
    if (locks?.request) {
      await locks.request(this.lockName, { ifAvailable: true }, async (lock) => {
        if (lock) await run()
      })
    } else {
      await run()
    }
  }

  private async drain() {
    const entries = await this.list()
    const done = new Set(entries.filter((e) => e.status === 'Acknowledged').map((e) => e.key))
    for (const e of entries) {
      if (!['Queued', 'Ambiguous'].includes(e.status)) continue
      // An earlier entry still backing off means the server was unreachable moments ago: stop here
      // rather than let later entries overtake it.
      if (e.nextAttempt > this.now()) break
      if (e.dependsOn && !done.has(e.dependsOn)) continue
      e.status = 'Sending'
      e.attempts += 1
      await this.save(e)
      try {
        e.result = await this.send(e)
        const status = (e.result as { status?: string } | undefined)?.status
        // the server may accept the entry but park it for a manager (e.g. outside offline policy)
        e.status = status === 'needs_review' ? 'Needs Review' : 'Acknowledged'
        e.lastError = undefined
        if (e.status === 'Acknowledged') done.add(e.key)
      } catch (err) {
        const kind = err instanceof ApiError ? err.kind : 'transient'
        e.lastError = err instanceof Error ? err.message : String(err)
        if (kind === 'transient' || kind === 'ambiguous') {
          e.status = kind === 'ambiguous' ? 'Ambiguous' : 'Queued'
          e.nextAttempt = this.now() + backoff(e.attempts)
          await this.save(e)
          if (kind === 'transient') break // the network is down: stop, keep order
          continue
        }
        e.status = 'Rejected'
      }
      await this.save(e)
    }
  }

  async markForReview(key: string, note: string) {
    const e = await idb.get<OutboxEntry>(this.db, 'outbox', key)
    if (!e || e.status !== 'Rejected') return
    e.status = 'Needs Review'
    e.lastError = note
    await this.save(e)
    await this.emit()
  }

  /** Download everything not yet acknowledged — the manual escape hatch if a device must be wiped. */
  async exportPending(): Promise<Blob> {
    const rows = await this.pending()
    return new Blob([JSON.stringify({ exported_at: new Date(this.now()).toISOString(), entries: rows }, null, 2)], { type: 'application/json' })
  }
}
