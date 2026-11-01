import { globalShortcut, powerMonitor } from 'electron'
import { EventEmitter } from 'node:events'
import type { SafetyStatus } from './api-types'
import type { BackendManager } from './backend-manager'

/** Backup shortcut that always exists regardless of the user-configured one. */
export const BACKUP_SHORTCUT = 'Ctrl+Alt+Shift+Escape'
const WATCHDOG_INTERVAL_MS = 2000
const WATCHDOG_FAILS_BEFORE_KILL = 3

/**
 * Electron-side safety net, independent of the Python SafetyController. It can only ever make the
 * system MORE restrictive: it stops tracking and, when the engine cannot be reached, kills the
 * engine process so no queued input can be injected. It never resumes anything.
 *
 *  - global emergency shortcuts (user configured + a fixed backup)
 *  - watchdog: engine unresponsive for ~6 s -> hard kill
 *  - lock screen / suspend -> stop
 */
export class SafetyManager extends EventEmitter {
  private shortcuts: { accelerator: string; registered: boolean }[] = []
  private timer: NodeJS.Timeout | null = null
  private fails = 0
  private status: SafetyStatus = { shortcuts: [], watchdogOk: true }

  constructor(private readonly backend: BackendManager) {
    super()
  }

  get current(): SafetyStatus {
    return this.status
  }

  private publish(): void {
    this.status = { ...this.status, shortcuts: this.shortcuts }
    this.emit('status', this.status)
  }

  start(configuredShortcut: string): void {
    this.registerShortcuts(configuredShortcut)
    this.timer = setInterval(() => void this.watchdog(), WATCHDOG_INTERVAL_MS)
    powerMonitor.on('lock-screen', () => void this.stop('screen locked'))
    powerMonitor.on('suspend', () => void this.stop('system suspend'))
  }

  registerShortcuts(configured: string): void {
    globalShortcut.unregisterAll()
    const wanted = Array.from(new Set([configured, BACKUP_SHORTCUT]))
    this.shortcuts = wanted.map((accelerator) => {
      let registered = false
      try {
        registered = globalShortcut.register(accelerator, () => void this.stop(`shortcut ${accelerator}`))
      } catch {
        registered = false
      }
      return { accelerator, registered }
    })
    this.publish()
  }

  /** Stop path: ask the engine politely and quickly; if it does not answer, kill it. */
  async stop(reason: string): Promise<void> {
    this.emit('emergency', reason)
    const res = await this.backend.request('POST', '/api/safety/stop', undefined, 1200)
    const reached = res.ok
    if (!reached) this.backend.kill()
    this.status = { ...this.status, lastStop: { at: Date.now(), reason, backendReached: reached } }
    this.publish()
  }

  private async watchdog(): Promise<void> {
    if (this.backend.currentStatus.phase !== 'ready' || !this.backend.connection) {
      this.fails = 0
      return
    }
    const res = await this.backend.request('GET', '/health', undefined, 1500)
    if (res.ok) {
      this.fails = 0
      if (!this.status.watchdogOk) {
        this.status = { ...this.status, watchdogOk: true }
        this.publish()
      }
      return
    }
    this.fails += 1
    if (this.fails >= WATCHDOG_FAILS_BEFORE_KILL) {
      this.status = { ...this.status, watchdogOk: false }
      this.publish()
      this.emit('emergency', 'engine unresponsive')
      this.backend.kill() // the backend manager's exit handler restarts it in a safe default state
      this.fails = 0
    }
  }

  dispose(): void {
    if (this.timer) clearInterval(this.timer)
    globalShortcut.unregisterAll()
  }
}
