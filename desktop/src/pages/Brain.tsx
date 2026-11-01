import { Check, X } from 'lucide-react'
import { api } from '../lib/api'
import { useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Badge, Button, Card, Empty, ErrorLine, Meter, Page, pct } from '../components/ui'
import { RISK_LABEL } from '../lib/types'

export default function BrainPage(_: { go: (id: string) => void }) {
  const { state, refresh } = useOracle()
  const { run, error } = useAction()
  if (!state) return <Page title="Brain">{null}</Page>
  const d = state.decision
  const feedback = (key: string, outcome: 'confirmed' | 'rejected') => void run('fb', async () => { await api.post('/api/brain/feedback', { suggestion_key: key, outcome }); await refresh() })
  return (
    <Page title="Brain" subtitle="A deterministic, explainable ranker. It combines gaze position, your measured gaze error, dwell, what is on screen and your history. Every score lists its evidence; there is no hidden model.">
      <Card>
        <div className="flex items-center gap-3">
          <Badge tone={d.phase === 'select_ready' ? 'good' : d.phase === 'paused' ? 'bad' : 'neutral'}>{d.phase.replace('_', ' ')}</Badge>
          <span className="text-sm text-zinc-400">{d.reason}</span>
          {d.ambiguous && <Badge tone="warn">ambiguous: asking instead of acting</Badge>}
        </div>
      </Card>
      <ErrorLine error={error} />
      {d.suggestions.length === 0 ? (
        <Empty>No suggestions. Start tracking and look at something on screen.</Empty>
      ) : (
        d.suggestions.map((s, i) => (
          <Card key={s.element_key}>
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs tabular-nums text-zinc-600">#{i + 1}</span>
                  <h3 className="truncate text-sm font-semibold text-white">{s.label || '(unnamed element)'}</h3>
                </div>
                <p className="mt-0.5 text-xs text-zinc-500">{s.app} - {s.control_type} - suggested action: {s.action.replace(/_/g, ' ')}</p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Badge tone={s.risk >= 3 ? 'bad' : s.risk === 2 ? 'warn' : 'neutral'}>{RISK_LABEL[s.risk] ?? s.risk} risk</Badge>
                {s.needs_confirmation && <Badge tone="warn">needs confirmation</Badge>}
                <Button variant="ghost" aria-label="Confirm suggestion" onClick={() => feedback(s.element_key, 'confirmed')}><Check className="size-4" /></Button>
                <Button variant="ghost" aria-label="Reject suggestion" onClick={() => feedback(s.element_key, 'rejected')}><X className="size-4" /></Button>
              </div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-5">
              <div><div className="mb-1 flex justify-between text-xs text-zinc-500"><span>Probability</span><span>{pct(s.probability)}</span></div><Meter value={s.probability} /></div>
              <div><div className="mb-1 flex justify-between text-xs text-zinc-500"><span>Confidence</span><span>{pct(s.confidence)}</span></div><Meter value={s.confidence} /></div>
            </div>
            <ul className="mt-4 space-y-1 border-t border-ink-700 pt-3 text-xs">
              {s.evidence.map((e) => (
                <li key={e.name} className="flex gap-3"><span className="w-28 shrink-0 text-zinc-500">{e.name.replace(/_/g, ' ')}</span><span className="w-12 shrink-0 tabular-nums text-zinc-300">{e.value.toFixed(2)}</span><span className="text-zinc-500">{e.detail}</span></li>
              ))}
            </ul>
          </Card>
        ))
      )}
    </Page>
  )
}
