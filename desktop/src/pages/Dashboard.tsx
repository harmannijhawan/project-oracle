import { ArrowRight, Check, Circle } from 'lucide-react'
import { useOracle, useFrame } from '../lib/store'
import { Badge, Card, Meter, Page, Stat, pct, timeOf } from '../components/ui'
import TrackingControls from '../components/TrackingControls'

export default function Dashboard({ go }: { go: (id: string) => void }) {
  const { state, hotkey } = useOracle()
  const frame = useFrame()
  if (!state) return <Page title="Overview">{null}</Page>
  const quality = frame?.quality ?? state.quality
  const steps = [
    { id: 'calibration', label: 'Calibrate your gaze', done: state.calibrated, detail: state.calibration ? `${state.calibration.mean_error_px.toFixed(0)} px mean error` : 'Nine-point calibration, about one minute' },
    { id: 'baseline', label: 'Record a face baseline', done: state.baseline.ready, detail: state.baseline.ready ? `${state.baseline.n} frames recorded` : 'Needed before any facial-behaviour trial' },
    { id: 'experiments', label: 'Run prediction trials', done: !!state.model, detail: state.model ? `Model: ${state.model.name}` : 'Commit-before-reveal trials build your personal model' },
    { id: 'control', label: 'Turn on gaze control', done: state.cursor_control, detail: 'Off by default. You enable it explicitly.' },
  ]
  return (
    <Page title="Overview" subtitle="Everything ORACLE does runs locally. Control is opt-in at every step and the emergency stop is always one click or one shortcut away.">
      <Card>
        <div className="grid grid-cols-4 gap-6">
          <Stat label="Safety" value={state.safety.state === 'active' ? 'Armed' : 'Halted'} sub={`Shortcut ${state.safety.shortcut}`} />
          <Stat label="Tracking" value={state.tracking ? (state.face ? 'Face found' : 'No face') : 'Stopped'} />
          <div>
            <div className="text-xs text-zinc-500">Tracking quality</div>
            <div className="mb-2 mt-1 text-xl font-semibold tabular-nums text-white">{pct(quality)}</div>
            <Meter value={quality} tone={quality < 0.5 ? 'warn' : 'accent'} />
          </div>
          <Stat label="Display" value={`${state.monitor.width} x ${state.monitor.height}`} sub="Primary monitor" />
        </div>
        <div className="mt-5 border-t border-ink-700 pt-4">
          <TrackingControls />
        </div>
        {state.last_error && <p className="mt-3 text-xs text-amber-300">Last engine message: {state.last_error}</p>}
        {hotkey === 'unavailable' && <p className="mt-3 text-xs text-amber-300">The engine could not register the global shortcut (another app may hold it). The backup shortcut and the on-screen button still work.</p>}
      </Card>

      <Card title="Setup" hint="Work through these in order. Each step explains what it records.">
        <ul className="divide-y divide-ink-700">
          {steps.map((s) => (
            <li key={s.id}>
              <button onClick={() => go(s.id)} className="group flex w-full items-center gap-4 py-3 text-left">
                <span className={`grid size-6 place-items-center rounded-full ${s.done ? 'bg-emerald-500/20 text-emerald-300' : 'bg-ink-700 text-zinc-500'}`}>{s.done ? <Check className="size-3.5" /> : <Circle className="size-2.5" />}</span>
                <span className="flex-1">
                  <span className="block text-sm text-zinc-100">{s.label}</span>
                  <span className="block text-xs text-zinc-500">{s.detail}</span>
                </span>
                <ArrowRight className="size-4 text-zinc-600 transition-transform group-hover:translate-x-0.5 group-hover:text-zinc-300" />
              </button>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Recent actions" hint="Every action passes the safety controller and permission policy before it runs.">
        {state.recent_actions.length === 0 ? (
          <p className="text-sm text-zinc-500">No actions yet.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {state.recent_actions.slice(0, 6).map((a, i) => (
              <li key={i} className="flex items-center gap-3">
                <span className="w-20 font-mono text-xs text-zinc-500">{timeOf(a.ts)}</span>
                <span className="flex-1 truncate text-zinc-200">{a.kind.replace(/_/g, ' ')}{a.label ? ` - ${a.label}` : ''}</span>
                <Badge tone={a.status === 'executed' ? 'good' : 'warn'}>{a.status}</Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </Page>
  )
}
