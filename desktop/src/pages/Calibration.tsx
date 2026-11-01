import { useCallback, useEffect, useRef, useState } from 'react'
import { Maximize2 } from 'lucide-react'
import { api, errText } from '../lib/api'
import { useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Badge, Button, Card, ErrorLine, Page, Stat } from '../components/ui'
import TrackingControls from '../components/TrackingControls'
import type { CalibrationInfo } from '../lib/types'

type Phase = 'idle' | 'running' | 'failed'
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export default function Calibration(_: { go: (id: string) => void }) {
  const { state, refresh } = useOracle()
  const { error, run } = useAction()
  const [phase, setPhase] = useState<Phase>('idle')
  const [targets, setTargets] = useState<[number, number][]>([])
  const [index, setIndex] = useState(0)
  const [failure, setFailure] = useState<string | null>(null)
  const [result, setResult] = useState<CalibrationInfo | null>(null)
  const cancelled = useRef(false)

  const exitFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
  }

  const sequence = useCallback(async (from: number, list: [number, number][]) => {
    for (let i = from; i < list.length; i++) {
      if (cancelled.current) return
      setIndex(i)
      const [tx, ty] = list[i]
      await api.post('/api/simulate/look', { tx, ty }).catch(() => undefined) // only meaningful for the simulator
      await sleep(900) // let the eye settle on the dot
      try {
        await api.post('/api/calibration/capture', { tx, ty })
      } catch (e) {
        setFailure(errText(e))
        setPhase('failed')
        return
      }
    }
    const report = await api.post<CalibrationInfo>('/api/calibration/finish')
    setResult(report)
    setPhase('idle')
    exitFullscreen()
    await refresh()
  }, [refresh])

  const begin = () =>
    void run('cal', async () => {
      if (!state?.tracking) throw new Error('Start the camera (or simulator) first.')
      cancelled.current = false
      setResult(null)
      setFailure(null)
      const res = await api.post<{ targets: [number, number][] }>('/api/calibration/start')
      setTargets(res.targets)
      setPhase('running')
      await document.documentElement.requestFullscreen().catch(() => undefined)
      await sleep(700)
      await sequence(0, res.targets)
    })

  const abort = useCallback(() => {
    cancelled.current = true
    setPhase('idle')
    exitFullscreen()
  }, [])

  useEffect(() => {
    if (phase === 'idle') return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && abort()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [phase, abort])

  const info = result ?? state?.calibration ?? null
  const q = info ? (info.mean_error_px < 80 ? 'good' : info.mean_error_px < 160 ? 'warn' : 'bad') : 'neutral'

  return (
    <Page title="Calibration" subtitle="Look at each dot as it appears and keep your head still. Nine points are captured; accuracy is then measured by leaving points out and predicting them.">
      <Card title="Before you start">
        <ul className="mb-4 list-disc space-y-1 pl-5 text-sm text-zinc-400">
          <li>Sit at your normal distance with your face evenly lit, no strong light behind you.</li>
          <li>Keep your head as still as you can. Move only your eyes.</li>
          <li>Press Escape at any time to cancel.</li>
        </ul>
        <TrackingControls />
        <div className="mt-4">
          <Button variant="primary" onClick={begin} disabled={!state?.tracking || phase !== 'idle'}>
            <Maximize2 className="size-4" />
            Start calibration
          </Button>
        </div>
        <div className="mt-3"><ErrorLine error={error} /></div>
      </Card>

      {info && (
        <Card title="Last calibration" hint="Errors are measured on held-out points, not on the points used to fit.">
          <div className="grid grid-cols-4 gap-6">
            <Stat label="Mean error" value={`${info.mean_error_px.toFixed(0)} px`} />
            <Stat label="90th percentile" value={`${info.p90_error_px.toFixed(0)} px`} />
            <Stat label="Relative error" value={`${(info.relative_error * 100).toFixed(1)}%`} sub="of screen size" />
            <div>
              <div className="text-xs text-zinc-500">Verdict</div>
              <div className="mt-2"><Badge tone={q as 'good' | 'warn' | 'bad' | 'neutral'}>{q === 'good' ? 'Usable for large targets' : q === 'warn' ? 'Coarse. Expect suggestions, not precision.' : 'Poor. Recalibrate.'}</Badge></div>
            </div>
          </div>
          <p className="mt-4 text-xs leading-relaxed text-zinc-500">Webcam gaze is coarse. ORACLE uses this measured error to decide how many on-screen elements are plausible targets, and shows suggestions instead of guessing when it is unsure.</p>
        </Card>
      )}

      {phase !== 'idle' && (
        <div className="fixed inset-0 z-50 bg-ink-950">
          {phase === 'running' && targets[index] && (
            <span
              className="absolute size-7 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent shadow-[0_0_0_8px_rgba(94,234,212,0.2)]"
              style={{ left: `${targets[index][0] * 100}%`, top: `${targets[index][1] * 100}%` }}
            >
              <span className="absolute inset-[11px] rounded-full bg-ink-950" />
            </span>
          )}
          <div className="absolute inset-x-0 bottom-8 text-center text-sm text-zinc-500">
            {phase === 'running' ? `Point ${index + 1} of ${targets.length}. Press Escape to cancel.` : ''}
          </div>
          {phase === 'failed' && (
            <div className="absolute left-1/2 top-1/2 w-96 -translate-x-1/2 -translate-y-1/2 rounded-xl border border-ink-600 bg-ink-900 p-6 text-center">
              <p className="text-sm text-zinc-200">{failure}</p>
              <div className="mt-4 flex justify-center gap-2">
                <Button variant="primary" onClick={() => { setPhase('running'); void sequence(index, targets) }}>Retry this point</Button>
                <Button onClick={abort}>Cancel</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Page>
  )
}
