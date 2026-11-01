import { useEffect, useState } from 'react'
import { Lock } from 'lucide-react'
import { api, bridge } from '../lib/api'
import { useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Badge, Button, Card, Empty, ErrorLine, Page, Toggle, timeOf } from '../components/ui'
import type { SafetyEventRow, Settings } from '../lib/types'

const KINDS: { id: string; label: string; risk: 'Low' | 'Medium' }[] = [
  { id: 'move_cursor', label: 'Move cursor', risk: 'Low' },
  { id: 'highlight', label: 'Highlight an element', risk: 'Low' },
  { id: 'scroll', label: 'Scroll', risk: 'Low' },
  { id: 'show_suggestion', label: 'Show a suggestion', risk: 'Low' },
  { id: 'click', label: 'Click', risk: 'Medium' },
  { id: 'switch_window', label: 'Switch window', risk: 'Medium' },
  { id: 'drag_start', label: 'Start a drag', risk: 'Medium' },
  { id: 'drag_end', label: 'End a drag', risk: 'Medium' },
]
const LOCKED = ['Delete files', 'Send messages', 'Purchases', 'Install software']

interface ActionRow { id: number; ts: number; command_json: string; status: string; reason: string; risk: number }

export default function Safety(_: { go: (id: string) => void }) {
  const { state, shell, refresh } = useOracle()
  const { run, busy, error } = useAction()
  const [events, setEvents] = useState<SafetyEventRow[]>([])
  const [actions, setActions] = useState<ActionRow[]>([])
  const [settings, setSettings] = useState<Settings | null>(null)

  const load = () => run('load', async () => {
    setEvents(await api.get('/api/safety/events'))
    setActions(await api.get('/api/actions/recent'))
    setSettings(await api.get('/api/settings'))
  })
  useEffect(() => { void load() }, [state?.safety.state]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleKind = (id: string, on: boolean) => {
    if (!settings) return
    const next = on ? [...settings.enabled_actions, id] : settings.enabled_actions.filter((k) => k !== id)
    void run('perm', async () => { setSettings(await api.put<Settings>('/api/settings', { enabled_actions: next })) })
  }
  const halted = state?.safety.state !== 'active'
  const label = (a: ActionRow) => { try { return (JSON.parse(a.command_json) as { kind: string }).kind.replace(/_/g, ' ') } catch { return 'action' } }

  return (
    <Page title="Safety and actions" subtitle="The safety controller sits between every command and your computer. It is independent of tracking, the brain and this window, and cannot be switched off.">
      <ErrorLine error={error} />
      <Card title="Emergency stop">
        <div className="flex items-center justify-between gap-6">
          <div className="text-sm text-zinc-300">
            State: <Badge tone={halted ? 'bad' : 'good'}>{state?.safety.state.replace('_', ' ') ?? 'unknown'}</Badge>
            <p className="mt-2 max-w-md text-xs leading-relaxed text-zinc-500">Resuming is always manual. After an automatic pause (camera lost, tracking quality too low, engine error) ORACLE waits for you.</p>
          </div>
          <div className="flex gap-2">
            <Button variant="danger" onClick={() => void bridge().emergencyStop('safety page').then(refresh)}>Stop now</Button>
            <Button disabled={!halted} busy={busy === 'resume'} onClick={() => void run('resume', async () => { await api.post('/api/safety/resume', { confirmed: true }); await refresh(); await load() })}>Resume</Button>
          </div>
        </div>
        <ul className="mt-4 space-y-1 border-t border-ink-700 pt-3 text-xs text-zinc-400">
          {(shell?.shortcuts ?? []).map((s) => (
            <li key={s.accelerator} className="flex items-center gap-2"><span className="font-mono text-zinc-300">{s.accelerator}</span>{s.registered ? <Badge tone="good">active</Badge> : <Badge tone="warn">held by another process</Badge>}</li>
          ))}
          <li className="pt-1 text-zinc-500">Watchdog: {shell?.watchdogOk === false ? 'engine was unresponsive and has been stopped' : 'engine responding'}. If the engine ever stops answering, the app terminates it so nothing can keep injecting input.</li>
        </ul>
      </Card>

      <Card title="Permitted actions" hint="Anything unchecked is refused by the controller, no matter what the brain suggests.">
        <div className="divide-y divide-ink-700">
          {KINDS.map((k) => (
            <Toggle key={k.id} label={`${k.label}`} description={`${k.risk} risk`} checked={settings?.enabled_actions.includes(k.id) ?? false} disabled={!settings || busy === 'perm'} onChange={(v) => toggleKind(k.id, v)} />
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink-700 pt-3 text-xs text-zinc-500">
          <Lock className="size-3.5" /> Never performed automatically:
          {LOCKED.map((l) => <Badge key={l}>{l}</Badge>)}
        </div>
      </Card>

      <Card title="Action log" hint="Everything the controller allowed or refused.">
        {actions.length === 0 ? <Empty>No actions recorded.</Empty> : (
          <div className="max-h-72 overflow-y-auto"><ul className="space-y-1.5 text-sm">
            {actions.slice(0, 50).map((a) => (
              <li key={a.id} className="flex items-center gap-3"><span className="w-20 shrink-0 font-mono text-xs text-zinc-500">{timeOf(a.ts)}</span><span className="flex-1 truncate text-zinc-200">{label(a)}</span><span className="max-w-64 truncate text-xs text-zinc-500">{a.reason}</span><Badge tone={a.status === 'executed' ? 'good' : 'warn'}>{a.status}</Badge></li>
            ))}
          </ul></div>
        )}
      </Card>

      <Card title="Safety events">
        {events.length === 0 ? <Empty>No stops or pauses yet.</Empty> : (
          <ul className="space-y-1.5 text-sm">
            {events.slice(0, 30).map((e) => (
              <li key={e.id} className="flex items-center gap-3"><span className="w-20 font-mono text-xs text-zinc-500">{timeOf(e.ts)}</span><Badge tone={e.kind === 'resume' ? 'good' : e.kind === 'resume_refused' ? 'warn' : 'bad'}>{e.kind.replace('_', ' ')}</Badge><span className="text-zinc-300">{e.reason.replace(/_/g, ' ')}</span><span className="truncate text-xs text-zinc-600">{e.detail}</span></li>
            ))}
          </ul>
        )}
      </Card>
    </Page>
  )
}
