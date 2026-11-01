import type { OracleBridge } from '../../electron/api-types'

declare global {
  interface Window {
    oracle?: OracleBridge
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public kind?: string,
  ) {
    super(message)
  }
}

export const bridge = (): OracleBridge => {
  if (!window.oracle) throw new ApiError('Project ORACLE must be run inside its desktop shell.', 0)
  return window.oracle
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await bridge().request<T & { message?: string; error?: string; detail?: string }>(method, path, body)
  if (!res.ok) {
    const d = (res.data ?? {}) as { message?: string; error?: string; detail?: string }
    throw new ApiError(d.message || d.detail || `Request failed (${res.status})`, res.status, d.error)
  }
  return res.data as T
}

export const api = {
  get: <T>(path: string) => call<T>('GET', path),
  post: <T>(path: string, body?: unknown) => call<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => call<T>('PUT', path, body),
}

export const errText = (e: unknown): string => (e instanceof Error ? e.message : String(e))
