import { useState } from 'react'
import { MousePointer2, TriangleAlert } from 'lucide-react'
import { api } from '../lib/api'
import { useFrame, useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Badge, Button, Card, ErrorLine, Meter, Page, Toggle, pct } from '../components/ui'
import TrackingControls from '../components/TrackingControls'
import type { Settings } from '../lib/types'

export default function Control({ go }: { go: (id: string) => void }) {
  const { state, refresh } = useOracle()
  const frame = useFrame()
  const { run, error } = useAction()
  const [confirming, setConfirming] = useState(false)
  if (!state) return <Page title="Gaze control">{null}</Page>
  const gaze = frame?.gaze ?? state.gaze
  const { width, height } = state.monitor
  const quality = frame?.quality ?? state.quality
  const patch = (p: Partial<Settings>) => void run('settings', async () => { await api.put('/api/settings', p); await refresh() })
  const halted = state.safety.state !== 'active'

  return (
    <Page title="Gaze control" subtitle="Live view of where ORACLE thinks you are looking. Moving the real cursor is a separate switch and stays off until you turn it on.">
      <Card title="Live gaze" hint="The rectangle is your primary display, scaled down.">
        <div className="relative mx-auto overflow-hidden rounded-lg border border-ink-600 bg-ink-950" style={{ aspectRatio: `${width} / ${height}`, maxWidth: 640 }}>
          {gaze && (
            <>
              <span className="absolute size-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent/80" style={{ left: `${(gaze.x / width) * 100}%`, top: `${(gaze.y / height) * 100}%` }} />
              <svg className="absolute size-12 -translate-x-1/2 -translate-y-1/2 -rotate-90" viewBox="0 0 36 36" style={{ left: `${(gaze.x / width) * 100}%`, top: `${(gaze.y / height) * 100}%` }}>
                <circle cx="18" cy="18" r="16" fill="none" stroke="rgb(94 234 212)" strokeWidth="2" strokeDasharray={`${gaze.dwell * 100.5} 100.5`} />
              </svg>
            </>
          )}
          {!gaze && <div className="absolute inset-0 grid place-items-center text-sm text-zinc-600">{!state.calibrated ? 'Calibrate first' : state.tracking ? 'No reliable gaze yet' : 'Tracking is stopped'}</div>}
        </div>
        <div className="mx-auto mt-4 max-w-[640px]">
          <div className="mb-1.5 flex justify-between text-xs text-zinc-500">
            <span>Tracking quality</span>
            <span>{pct(quality)}</span>
          </div>
          <Meter value={quality} tone={quality < 0.5 ? 'warn' : 'accent'} />
        </div>
        <div className="mt-4"><TrackingControls /></div>
      </Card>

      <Card title="Input control" hint="Each switch can be turned off at any moment; the emergency stop turns everything off.">
        {!state.calibrated && (
          <div className="mb-3 flex items-center gap-3 rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
            <TriangleAlert className="size-4 shrink-0" />
            Gaze control needs a calibration.
            <Button className="ml-auto" onClick={() => go('calibration')}>Calibrate</Button>
          </div>
        )}
        <div className="flex items-start justify-between gap-6 py-2">
          <div>
            <div className="flex items-center gap-2 text-sm text-zinc-100"><MousePointer2 className="size-4" /> Move the real cursor with my gaze {state.cursor_control && <Badge tone="good">On</Badge>}</div>
            <p className="mt-0.5 max-w-lg text-xs leading-relaxed text-zinc-500">Cursor movement is low risk and smoothed. Clicks are separate and always pass the permission policy.</p>
          </div>
          {state.cursor_control ? (
            <Button onClick={() => patch({ cursor_control: false })}>Turn off</Button>
          ) : confirming ? (
            <div className="flex gap-2">
              <Button variant="primary" disabled={!state.calibrated || halted} onClick={() => { setConfirming(false); patch({ cursor_control: true }) }}>Yes, turn on</Button>
              <Button variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
            </div>
          ) : (
            <Button variant="primary" disabled={!state.calibrated || halted} onClick={() => setConfirming(true)}>Turn on</Button>
          )}
        </div>
        <Toggle checked={state.dwell_click} disabled={!state.calibrated} onChange={(v) => patch({ dwell_click: v })} label="Dwell to click" description="Holding your gaze on a target the brain is confident about performs the click. Low-confidence or ambiguous targets only show a suggestion." />
        <ErrorLine error={error} />
      </Card>
    </Page>
  )
}
