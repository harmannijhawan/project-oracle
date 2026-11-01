import { app, BrowserWindow, ipcMain, session, shell } from 'electron'
import * as path from 'node:path'
import { BackendManager } from './backend-manager'
import { SafetyManager } from './safety-manager'

const DEV_URL = process.env.ORACLE_DEV_URL // e.g. http://localhost:5173
const dataDir = path.join(app.getPath('appData'), 'ORACLE')

let win: BrowserWindow | null = null

const backend = new BackendManager({
  packaged: app.isPackaged,
  resourcesPath: process.resourcesPath,
  repoRoot: path.resolve(__dirname, '..', '..'),
  dataDir,
})
const safety = new SafetyManager(backend)

// Only the REST paths the UI actually uses may be proxied; the engine API is the source of truth for validation.
const ALLOWED_PREFIXES = ['/api/', '/health']
const ALLOWED_METHODS = new Set(['GET', 'POST', 'PUT'])

function send(channel: string, payload: unknown): void {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload)
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1000,
    minHeight: 680,
    backgroundColor: '#0b0d12',
    title: 'Project ORACLE',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  })
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith('file://') && !(DEV_URL && url.startsWith(DEV_URL))) e.preventDefault()
  })
  if (DEV_URL) void win.loadURL(DEV_URL)
  else void win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  win.on('closed', () => (win = null))
}

function registerIpc(): void {
  ipcMain.handle('oracle:connection', () => backend.connection)
  ipcMain.handle('oracle:request', (_e, method: string, apiPath: string, body?: unknown) => {
    const m = String(method).toUpperCase()
    if (!ALLOWED_METHODS.has(m) || typeof apiPath !== 'string' || !ALLOWED_PREFIXES.some((p) => apiPath.startsWith(p)) || apiPath.includes('..')) {
      return { ok: false, status: 400, data: { error: 'blocked', message: 'request not permitted' } }
    }
    // calibration capture blocks for up to 8 s inside the engine
    const long = apiPath.startsWith('/api/calibration/capture') || apiPath.startsWith('/api/model/train')
    return backend.request(m, apiPath, body, long ? 30_000 : 15_000).then((res) => {
      // keep the shell-level emergency shortcut in sync with the configured one
      const sc = (body as { emergency_shortcut?: unknown } | undefined)?.emergency_shortcut
      if (res.ok && m === 'PUT' && apiPath === '/api/settings' && typeof sc === 'string') safety.registerShortcuts(sc)
      return res
    })
  })
  ipcMain.handle('oracle:emergency-stop', (_e, reason?: string) => safety.stop(reason ?? 'user button'))
  ipcMain.handle('oracle:backend-status', () => backend.currentStatus)
  ipcMain.handle('oracle:safety-status', () => safety.current)
  ipcMain.handle('oracle:restart-backend', async () => {
    await backend.restart()
  })
  ipcMain.handle('oracle:open-data', () => shell.openPath(dataDir))
  ipcMain.handle('oracle:app-info', () => ({ version: app.getVersion(), platform: process.platform, dataDir, packaged: app.isPackaged }))
}

backend.on('status', (s) => send('oracle:backend-status', s))
safety.on('status', (s) => send('oracle:safety-status', s))
safety.on('emergency', (reason: string) => send('oracle:emergency', reason))

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  void app.whenReady().then(async () => {
    // The camera is the only permission the app ever needs; everything else is denied.
    session.defaultSession.setPermissionRequestHandler((_wc, permission, cb) => cb(permission === 'media'))
    registerIpc()
    createWindow()
    safety.start('Ctrl+Alt+Shift+Q')
    try {
      await backend.start()
      const settings = await backend.request<{ emergency_shortcut?: string }>('GET', '/api/settings')
      if (settings.ok && settings.data.emergency_shortcut) safety.registerShortcuts(settings.data.emergency_shortcut)
    } catch {
      /* status is already published to the UI, which shows a recovery screen */
    }
  })

  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', () => {
    safety.dispose()
    backend.kill(true)
  })
}
