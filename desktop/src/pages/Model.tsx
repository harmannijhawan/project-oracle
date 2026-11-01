import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Badge, Button, Card, Empty, ErrorLine, Page, Stat, pct } from '../components/ui'
import type { Evaluation } from '../lib/types'

interface Versions { versions: Record<string, unknown>[]; evaluation: Evaluation | null }

export default function Model(_: { go: (id: string) => void }) {
  const { state, refresh } = useOracle()
  const { run, busy, error } = useAction()
  const [data, setData] = useState<Versions | null>(null)
  const load = () => run('load', async () => setData(await api.get<Versions>('/api/model/versions')))
  useEffect(() => { void load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const train = () => void run('train', async () => { await api.post('/api/model/train'); await load(); await refresh() })
  const ev = data?.evaluation ?? null
  const results = ev ? Object.values(ev.results) : []

  return (
    <Page title="Personal model" subtitle="Logistic regression, random forest and gradient boosting are compared on sessions the model never trained on, alongside a baseline that ignores your face entirely. If the face adds nothing, this page says so." actions={<Button variant="primary" busy={busy === 'train'} onClick={train}>Train on my trials</Button>}>
      <ErrorLine error={error} />
      <Card>
        <div className="grid grid-cols-3 gap-6">
          <Stat label="Active model" value={state?.model?.name ?? 'None'} sub={state?.model ? (state.model.calibrated ? 'Probabilities calibrated' : 'Uncalibrated') : 'Train after completing trials'} />
          <Stat label="Saved versions" value={data?.versions.length ?? 0} />
          <Stat label="Abstains below" value="Settings" sub="Confidence threshold is configurable" />
        </div>
      </Card>
      {!ev ? (
        <Empty>No evaluation yet. Complete trials across at least two sessions, then train.</Empty>
      ) : (
        <Card title="Held-out evaluation" hint={`Trained on ${ev.n_train} trials (${ev.train_sessions} sessions), tested on ${ev.n_test} trials from ${ev.test_sessions} later session(s). Selected: ${ev.selected_model}.`}>
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-zinc-500"><tr><th className="pb-2 font-normal">Predictor</th><th className="pb-2 font-normal">Accuracy</th><th className="pb-2 font-normal">95% interval</th><th className="pb-2 font-normal">Answered</th><th className="pb-2 font-normal">p vs chance</th></tr></thead>
            <tbody className="divide-y divide-ink-700">
              {results.map((r) => (
                <tr key={r.name}>
                  <td className="py-2 text-zinc-200">{r.name}</td>
                  <td className="py-2 tabular-nums">{pct(r.accuracy, 1)}</td>
                  <td className="py-2 font-mono text-xs text-zinc-500">{pct(r.ci95[0])} to {pct(r.ci95[1])}</td>
                  <td className="py-2 tabular-nums text-zinc-400">{r.n_answered}{r.n_abstained ? ` (+${r.n_abstained} abstained)` : ''}</td>
                  <td className="py-2"><Badge tone={r.p_vs_chance < 0.05 ? 'good' : 'neutral'}>{r.p_vs_chance.toFixed(3)}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 rounded-lg bg-ink-800 p-4 text-sm leading-relaxed text-zinc-300">{ev.verdict}</div>
          <p className="mt-2 text-xs text-zinc-500">Face vs context-only: p = {ev.p_face_vs_context.toFixed(3)}</p>
        </Card>
      )}
    </Page>
  )
}
