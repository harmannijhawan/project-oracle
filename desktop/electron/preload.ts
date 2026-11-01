import { contextBridge, ipcRenderer } from 'electron'
import type { OracleBridge } from './api-types'

const subscribe = <T>(channel: string, cb: (v: T) => void): (() => void) => {
  const handler = (_: unknown, v: T): void => cb(v)
  ipcRenderer.on(channel, handler)
  return () => ipcRenderer.removeListener(channel, handler)
}

const bridge: OracleBridge = {
  connection: () => ipcRenderer.invoke('oracle:connection'),
  request: (method, path, body) => ipcRenderer.invoke('oracle:request', method, path, body),
  emergencyStop: (reason) => ipcRenderer.invoke('oracle:emergency-stop', reason),
  backendStatus: () => ipcRenderer.invoke('oracle:backend-status'),
  safetyStatus: () => ipcRenderer.invoke('oracle:safety-status'),
  restartBackend: () => ipcRenderer.invoke('oracle:restart-backend'),
  openDataFolder: () => ipcRenderer.invoke('oracle:open-data'),
  appInfo: () => ipcRenderer.invoke('oracle:app-info'),
  onBackendStatus: (cb) => subscribe('oracle:backend-status', cb),
  onSafetyStatus: (cb) => subscribe('oracle:safety-status', cb),
  onEmergencyStop: (cb) => subscribe('oracle:emergency', cb),
}

contextBridge.exposeInMainWorld('oracle', bridge)
