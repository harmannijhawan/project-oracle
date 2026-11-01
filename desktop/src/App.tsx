import { useState, type ComponentType } from 'react'
import { Activity, Brain, Crosshair, FlaskConical, Gauge, LayoutGrid, MonitorSmartphone, OctagonX, ScanFace, Settings as Cog, ShieldCheck, Target, TriangleAlert } from 'lucide-react'
import { OracleProvider, useOracle } from './lib/store'
import { api, bridge } from './lib/api'
import { useAction } from './lib/useAction'
import { Button } from './components/ui'
import Dashboard from './pages/Dashboard'
import Calibration from './pages/Calibration'
import Control from './pages/Control'
import Baseline from './pages/Baseline'
import Experiments from './pages/Experiments'
import Model from './pages/Model'
import BrainPage from './pages/Brain'
import Screen from './pages/Screen'
import Safety from './pages/Safety'
import SettingsPage from './pages/Settings'

interface NavItem {
  id: string
  label: string
  icon: ComponentType<{ className?: string }>
  page: ComponentType<{ go: (id: string) => void }>
}

const NAV: NavItem[] = [
  { id: 'dashboard', label: 'Overview', icon: LayoutGrid, page: Dashboard },
  { id: 'calibration', label: 'Calibration', icon: Target, page: Calibration },
  { id: 'control', label: 'Gaze control', icon: Crosshair, page: Control },
  { id: 'baseline', label: 'Face baseline', icon: ScanFace, page: Baseline },
  { id: 'experiments', label: 'Experiments', icon: FlaskConical, page: Experiments },
  { id: 'model', label: 'Model', icon: Gauge, page: Model },
  { id: 'brain', label: 'Brain', icon: Brain, page: BrainPage },
  { id: 'screen', label: 'Screen context', icon: MonitorSmartphone, page: Screen },
  { id: 'safety', label: 'Safety & actions', icon: ShieldCheck, page: Safety },
  { id: 'settings', label: 'Settings', icon: Cog, page: SettingsPage },
]

function EngineGate() {
  const { backend } = useOracle()
  const { run, busy } = useAction()
  const failed = backend.phase === 'crashed'
  return (
    <div className="grid h-full place-items-center p-8">
      <div className="max-w-md text-center">
        <div className={`mx-auto mb-5 grid size-14 place-items-center rounded-2xl ${failed ? 'bg-red-500/15 text-red-300' : 'bg-ink-800 text-accent'}`}>
          {failed ? <TriangleAlert className="size-7" /> : <Activity className="size-7 animate-pulse" />}
        </div>
        <h1 className="text-xl font-semibold text-white">{failed ? 'The engine could not start' : 'Starting the local engine'}</h1>
        <p className="mt-2 text-sm leading-relaxed text-zinc-400">
          {failed ? backend.detail || 'The Python engine exited unexpectedly.' : 'Loading the on-device models. Nothing leaves this computer.'}
        </p>
        {failed && (
          <div className="mt-5 flex justify-center gap-2">
            <Button variant="primary" busy={busy === 'restart'} onClick={() => void run('restart', () => bridge().restartBackend())}>
              Try again
            </Button>
            <Button onClick={() => void bridge().openDataFolder()}>Open data folder</Button>
          </div>
        )}
      </div>
    </div>
  )
}

function SafetyBar() {
  const { state, shell, connected, notice, dismissNotice, refresh } = useOracle()
  const { run, busy } = useAction()
  const s = state?.safety.state ?? 'active'
  const halted = s !== 'active'
  const stop = () => void bridge().emergencyStop('user button').then(refresh)
  const resume = () => void run('resume', async () => { await api.post('/api/safety/resume', { confirmed: true }); await refresh() })
  const primary = shell?.shortcuts.find((x) => x.registered)?.accelerator
  return (
    <div className={`flex items-center gap-4 border-b px-6 py-3 ${halted ? 'border-red-500/40 bg-red-950/50' : 'border-ink-700 bg-ink-900'}`}>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className={`size-2.5 shrink-0 rounded-full ${halted ? 'bg-red-400' : connected ? 'bg-emerald-400' : 'bg-zinc-500'}`} />
        <div className="min-w-0 text-sm">
          {halted ? (
            <span className="text-red-200">
              Control halted{state?.safety.reason ? ` (${state.safety.reason.replace(/_/g, ' ')})` : ''}. Nothing will move your cursor until you resume.
            </span>
          ) : (
            <span className="text-zinc-300">{connected ? 'Safety armed.' : 'Connecting to engine...'} {primary && <span className="text-zinc-500">Emergency stop: {primary}</span>}</span>
          )}
          {notice && (
            <button onClick={dismissNotice} className="ml-3 text-xs text-amber-300 underline underline-offset-2">
              {notice}
            </button>
          )}
        </div>
      </div>
      {halted && (
        <Button busy={busy === 'resume'} onClick={resume}>
          Resume
        </Button>
      )}
      <Button variant="danger" onClick={stop} aria-label="Emergency stop">
        <OctagonX className="size-4" />
        Emergency stop
      </Button>
    </div>
  )
}

function Shell() {
  const [active, setActive] = useState('dashboard')
  const { backend } = useOracle()
  if (backend.phase !== 'ready') return <EngineGate />
  const Current = (NAV.find((n) => n.id === active) ?? NAV[0]).page
  return (
    <div className="flex h-full">
      <nav className="flex w-56 shrink-0 flex-col border-r border-ink-700 bg-ink-900 px-3 py-5">
        <div className="mb-6 flex items-center gap-2.5 px-2">
          <span className="grid size-8 place-items-center rounded-lg bg-accent text-ink-950">
            <Crosshair className="size-4.5" />
          </span>
          <span className="text-sm font-semibold tracking-wide text-white">ORACLE</span>
        </div>
        <ul className="space-y-0.5">
          {NAV.map(({ id, label, icon: Icon }) => (
            <li key={id}>
              <button
                onClick={() => setActive(id)}
                aria-current={active === id ? 'page' : undefined}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${active === id ? 'bg-ink-700 text-white' : 'text-zinc-400 hover:bg-ink-800 hover:text-zinc-200'}`}
              >
                <Icon className="size-4" />
                {label}
              </button>
            </li>
          ))}
        </ul>
        <p className="mt-auto px-2 text-xs leading-relaxed text-zinc-600">Runs entirely on this computer. No cloud services.</p>
      </nav>
      <div className="flex min-w-0 flex-1 flex-col">
        <SafetyBar />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Current go={setActive} />
        </main>
      </div>
    </div>
  )
}

export default function App() {
  if (!window.oracle) {
    return <div className="grid h-full place-items-center p-8 text-sm text-zinc-400">Project ORACLE must be opened with its desktop application.</div>
  }
  return (
    <OracleProvider>
      <Shell />
    </OracleProvider>
  )
}
