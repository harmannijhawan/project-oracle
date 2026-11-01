import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import type { BackendStatus, Connection, SafetyStatus } from '../../electron/api-types'
import { api, bridge } from './api'
import type { EngineState, Frame } from './types'

interface Ctx {
  state: EngineState | null
  backend: BackendStatus
  shell: SafetyStatus | null
  connected: boolean
  hotkey: Connection['hotkey']
  notice: string | null
  dismissNotice: () => void
  refresh: () => Promise<void>
  ensureTracking: (simulate?: boolean) => Promise<void>
  frames: FrameStore
}

/** High-rate frame data lives outside React state so 25 Hz updates only re-render subscribers. */
export class FrameStore {
  private frame: Frame | null = null
  private listeners = new Set<() => void>()
  set(f: Frame | null): void {
    this.frame = f
    this.listeners.forEach((l) => l())
  }
  get = (): Frame | null => this.frame
  subscribe = (l: () => void): (() => void) => {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }
}

const OracleContext = createContext<Ctx | null>(null)

export function OracleProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<EngineState | null>(null)
  const [backend, setBackend] = useState<BackendStatus>({ phase: 'starting' })
  const [shell, setShell] = useState<SafetyStatus | null>(null)
  const [connected, setConnected] = useState(false)
  const [hotkey, setHotkey] = useState<Connection['hotkey']>('unknown')
  const [notice, setNotice] = useState<string | null>(null)
  const frames = useRef(new FrameStore()).current
  const socket = useRef<WebSocket | null>(null)

  const refresh = useCallback(async () => {
    try {
      setState(await api.get<EngineState>('/api/state'))
    } catch {
      /* the connection indicator already reflects this */
    }
  }, [])

  // Shell (Electron main process) status
  useEffect(() => {
    const b = bridge()
    void b.backendStatus().then(setBackend)
    void b.safetyStatus().then(setShell)
    const offs = [
      b.onBackendStatus(setBackend),
      b.onSafetyStatus(setShell),
      b.onEmergencyStop((r) => {
        setNotice(`Emergency stop (${r}). Input control is halted.`)
        void refresh()
      }),
    ]
    return () => offs.forEach((o) => o())
  }, [refresh])

  // WebSocket to the engine whenever it is ready
  useEffect(() => {
    if (backend.phase !== 'ready') {
      setConnected(false)
      return
    }
    let closed = false
    let retry: ReturnType<typeof setTimeout> | undefined
    const open = async (): Promise<void> => {
      const conn = await bridge().connection()
      if (!conn || closed) return
      setHotkey(conn.hotkey)
      const ws = new WebSocket(`ws://127.0.0.1:${conn.port}/ws?token=${encodeURIComponent(conn.token)}`)
      socket.current = ws
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry = setTimeout(() => void open(), 1000)
      }
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data as string) as { type: string } & Record<string, unknown>
        switch (m.type) {
          case 'frame':
            frames.set(m as unknown as Frame)
            break
          case 'state':
            setState(m.state as EngineState)
            break
          case 'error':
            setNotice(String(m.message))
            break
          case 'tracking':
            if (!m.running) frames.set(null)
            void refresh()
            break
          default:
            // safety, safety_state, calibration, settings, action, feedback: re-sync the snapshot (cheap, local)
            void refresh()
        }
      }
    }
    void open()
    return () => {
      closed = true
      clearTimeout(retry)
      socket.current?.close()
    }
  }, [backend.phase, frames, refresh])

  // Snapshot keepalive: covers anything the event stream does not carry (e.g. decision details)
  useEffect(() => {
    if (!connected) return
    const id = setInterval(() => void refresh(), 1500)
    return () => clearInterval(id)
  }, [connected, refresh])

  const ensureTracking = useCallback(
    async (simulate = false) => {
      await api.post('/api/tracking/start', { simulate })
      await refresh()
    },
    [refresh],
  )

  const value = useMemo<Ctx>(
    () => ({ state, backend, shell, connected, hotkey, notice, dismissNotice: () => setNotice(null), refresh, ensureTracking, frames }),
    [state, backend, shell, connected, hotkey, notice, refresh, ensureTracking, frames],
  )
  return <OracleContext.Provider value={value}>{children}</OracleContext.Provider>
}

export function useOracle(): Ctx {
  const c = useContext(OracleContext)
  if (!c) throw new Error('OracleProvider missing')
  return c
}

export function useFrame(): Frame | null {
  const { frames } = useOracle()
  return useSyncExternalStore(frames.subscribe, frames.get)
}
