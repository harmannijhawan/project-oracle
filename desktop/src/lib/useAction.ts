import { useCallback, useState } from 'react'
import { errText } from './api'

/** Wraps an async handler with busy/error state so every page reports failures the same way. */
export function useAction() {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async <T,>(name: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(name)
    setError(null)
    try {
      return await fn()
    } catch (e) {
      setError(errText(e))
      return undefined
    } finally {
      setBusy(null)
    }
  }, [])
  return { busy, error, run, setError }
}
