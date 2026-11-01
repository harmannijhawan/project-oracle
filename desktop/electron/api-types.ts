// Types shared by the main process, the preload bridge and the renderer.
export interface Connection {
  port: number
  token: string
  hotkey: 'ok' | 'unavailable' | 'unknown'
}

export interface BackendStatus {
  phase: 'starting' | 'ready' | 'restarting' | 'crashed' | 'stopped'
  detail?: string
  pid?: number
}

export interface SafetyStatus {
  /** Electron-side independent emergency-stop shortcuts and whether registration succeeded. */
  shortcuts: { accelerator: string; registered: boolean }[]
  watchdogOk: boolean
  lastStop?: { at: number; reason: string; backendReached: boolean }
}

export interface ApiResult<T = unknown> {
  ok: boolean
  status: number
  data: T
}

export interface OracleBridge {
  connection(): Promise<Connection | null>
  request<T = unknown>(method: string, path: string, body?: unknown): Promise<ApiResult<T>>
  emergencyStop(reason?: string): Promise<void>
  backendStatus(): Promise<BackendStatus>
  safetyStatus(): Promise<SafetyStatus>
  restartBackend(): Promise<void>
  openDataFolder(): Promise<void>
  appInfo(): Promise<{ version: string; platform: string; dataDir: string; packaged: boolean }>
  onBackendStatus(cb: (s: BackendStatus) => void): () => void
  onSafetyStatus(cb: (s: SafetyStatus) => void): () => void
  onEmergencyStop(cb: (reason: string) => void): () => void
}
