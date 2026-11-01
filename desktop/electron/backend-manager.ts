import { ChildProcess, spawn, execFile } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { EventEmitter } from 'node:events'
import * as fs from 'node:fs'
import * as path from 'node:path'
import type { ApiResult, BackendStatus, Connection } from './api-types'

export interface BackendOptions {
  packaged: boolean
  resourcesPath: string
  repoRoot: string
  dataDir: string
}

const MAX_RESTARTS = 3

/**
 * Owns the Python engine process: spawns it on a random loopback port with a per-run token,
 * waits for its ORACLE_READY line, restarts it if it dies, and makes every REST call on behalf
 * of the renderer (so the token never has to be reachable from page JavaScript via CORS).
 */
export class BackendManager extends EventEmitter {
  private proc: ChildProcess | null = null
  private token = randomBytes(32).toString('base64url')
  private conn: Connection | null = null
  private restarts = 0
  private quitting = false
  private status: BackendStatus = { phase: 'stopped' }

  constructor(private readonly opts: BackendOptions) {
    super()
  }

  get connection(): Connection | null {
    return this.conn
  }

  get currentStatus(): BackendStatus {
    return this.status
  }

  private setStatus(s: BackendStatus): void {
    this.status = s
    this.emit('status', s)
  }

  private command(): { cmd: string; args: string[]; cwd: string } {
    const args = ['--port', '0', '--data-dir', this.opts.dataDir]
    if (this.opts.packaged) {
      const dir = path.join(this.opts.resourcesPath, 'backend')
      return { cmd: path.join(dir, 'oracle-engine.exe'), args, cwd: dir }
    }
    const python = process.env.ORACLE_PYTHON || (process.platform === 'win32' ? 'python' : 'python3')
    return { cmd: python, args: ['-m', 'engine.api.server', ...args], cwd: this.opts.repoRoot }
  }

  start(): Promise<Connection> {
    this.quitting = false
    return this.spawnOnce()
  }

  private spawnOnce(): Promise<Connection> {
    const { cmd, args, cwd } = this.command()
    if (this.opts.packaged && !fs.existsSync(cmd)) {
      const detail = `Engine executable is missing: ${cmd}`
      this.setStatus({ phase: 'crashed', detail })
      return Promise.reject(new Error(detail))
    }
    this.conn = null
    this.setStatus({ phase: this.restarts ? 'restarting' : 'starting' })
    return new Promise<Connection>((resolve, reject) => {
      let settled = false
      const child = spawn(cmd, args, {
        cwd,
        windowsHide: true,
        env: { ...process.env, ORACLE_TOKEN: this.token, PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'pipe', 'pipe'],
      })
      this.proc = child
      let buf = ''
      let tail = ''
      const timer = setTimeout(() => fail(new Error('Engine did not report ready within 45 seconds')), 45_000)
      const fail = (err: Error): void => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        this.setStatus({ phase: 'crashed', detail: err.message })
        reject(err)
      }
      child.stdout?.on('data', (d: Buffer) => {
        buf += d.toString()
        const m = /ORACLE_READY (\d+) hotkey=(\w+)/.exec(buf)
        if (m && !settled) {
          settled = true
          clearTimeout(timer)
          this.conn = { port: Number(m[1]), token: this.token, hotkey: m[2] === 'ok' ? 'ok' : 'unavailable' }
          this.setStatus({ phase: 'ready', pid: child.pid })
          resolve(this.conn)
        }
        if (buf.length > 4000) buf = buf.slice(-2000)
      })
      child.stderr?.on('data', (d: Buffer) => {
        tail = (tail + d.toString()).slice(-1500)
      })
      child.on('error', (e) => fail(new Error(`Could not launch engine: ${e.message}`)))
      child.on('exit', (code) => {
        if (this.proc === child) this.proc = null
        this.conn = null
        if (this.quitting) return
        const detail = `Engine exited (code ${code})${tail ? `: ${tail.trim().split('\n').slice(-2).join(' ')}` : ''}`
        fail(new Error(detail))
        if (this.restarts < MAX_RESTARTS) {
          this.restarts += 1
          setTimeout(() => void this.spawnOnce().catch(() => undefined), 1000 * this.restarts)
        } else {
          this.setStatus({ phase: 'crashed', detail })
        }
      })
    })
  }

  async restart(): Promise<void> {
    await this.stop()
    this.restarts = 0
    this.token = randomBytes(32).toString('base64url')
    await this.start().catch(() => undefined)
  }

  /** Kills the engine without waiting for it. Used by the hard-stop path. */
  kill(permanent = false): void {
    if (permanent) this.quitting = true
    const pid = this.proc?.pid
    if (pid && process.platform === 'win32') {
      execFile('taskkill', ['/pid', String(pid), '/T', '/F'], () => undefined)
    } else {
      this.proc?.kill('SIGKILL')
    }
  }

  async stop(): Promise<void> {
    this.quitting = true
    const proc = this.proc
    if (!proc) return this.setStatus({ phase: 'stopped' })
    try {
      if (this.conn) await this.request('POST', '/api/tracking/stop', undefined, 1500)
    } catch {
      /* the process is being killed anyway */
    }
    this.kill(true)
    this.proc = null
    this.conn = null
    this.setStatus({ phase: 'stopped' })
  }

  async request<T = unknown>(method: string, apiPath: string, body?: unknown, timeoutMs = 15_000): Promise<ApiResult<T>> {
    if (!this.conn) return { ok: false, status: 0, data: { error: 'engine_unavailable', message: 'The engine is not running' } as T }
    if (!apiPath.startsWith('/')) throw new Error('invalid path')
    const ctrl = new AbortController()
    // calibration capture blocks server-side for up to 8 s, so callers may pass a longer budget
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    try {
      const res = await fetch(`http://127.0.0.1:${this.conn.port}${apiPath}`, {
        method,
        headers: { 'x-oracle-token': this.conn.token, ...(body !== undefined ? { 'content-type': 'application/json' } : {}) },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
      })
      const text = await res.text()
      let data: unknown = null
      try {
        data = text ? JSON.parse(text) : null
      } catch {
        data = { message: text }
      }
      return { ok: res.ok, status: res.status, data: data as T }
    } catch (e) {
      return { ok: false, status: 0, data: { error: 'network', message: (e as Error).message } as T }
    } finally {
      clearTimeout(timer)
    }
  }
}
