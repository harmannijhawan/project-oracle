import { useCallback, useEffect, useState } from 'react'
import { Lock, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'
import { useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Badge, Button, Card, Empty, ErrorLine, Page, pct } from '../components/ui'
import TrackingControls from '../components/TrackingControls'
import type { Prediction, TrialRow } from '../lib/types'

interface Trial { id: string; session_id: string; left: string; right: string; idx: number }
type Stage = 'setup' | 'thinking' | 'locked' | 'done'
const THINK_SECONDS = 5

export default function Experiments(_: { go: (id: string) => void }) {
  const { state } = useOracle()
  const { run, busy, error } = useAction()
  const [session, setSession] = useState<string | null>(null)
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [trial, setTrial] = useState<Trial | null>(null)
  const [stage, setStage] = useState<Stage>('setup')
  const [left, setLeft] = useState(THINK_SECONDS)
  const [commit, setCommit] = useState<{ prediction: Prediction; commitment: string } | null>(null)
  const [outcome, setOutcome] = useState<{ side: 'left' | 'right'; verified: boolean } | null>(null)
  const [history, setHistory] = useState<TrialRow[]>([])
  const [audit, setAudit] = useState<{ completed_trials: number; unverifiable: string[] } | null>(null)

  const loadHistory = useCallback(async () => setHistory(await api.get<TrialRow[]>('/api/experiments/trials?limit=30')), [])
  useEffect(() => { void loadHistory().catch(() => undefined) }, [loadHistory])

  const ready = !!state?.tracking && !!state.baseline.ready

  const start = () =>
    void run('start', async () => {
      let sid = session
      if (!sid) {
        sid = (await api.post<{ session_id: string }>('/api/experiments/session')).session_id
        setSession(sid)
      }
      const t = await api.post<Trial>('/api/experiments/trial', { session_id: sid, option_a: a.trim(), option_b: b.trim() })
      const trialInfo = t
      await api.post(`/api/experiments/trial/${trialInfo.id}/begin`)
      setTrial(trialInfo)
      setOutcome(null)
      setCommit(null)
      setStage('thinking')
      setLeft(THINK_SECONDS)
    })

  // Countdown, then lock the prediction BEFORE the participant reveals a choice.
  useEffect(() => {
    if (stage !== 'thinking' || !trial) return
    if (left > 0) {
      const t = setTimeout(() => setLeft((n) => n - 1), 1000)
      return () => clearTimeout(t)
    }
    void run('lock', async () => {
      const r = await api.post<{ prediction: Prediction; commitment: string }>(`/api/experiments/trial/${trial.id}/lock`)
      setCommit(r)
      setStage('locked')
    }).then(() => setStage((s) => (s === 'thinking' ? 'setup' : s)))
  }, [stage, left, trial, run])

  const answer = (side: 'left' | 'right') =>
    void run('answer', async () => {
      const r = await api.post<{ verified: boolean }>(`/api/experiments/trial/${trial!.id}/answer`, { side })
      setOutcome({ side, verified: r.verified })
      setStage('done')
      await loadHistory()
    })

  const graded = history.filter((h) => h.label && h.prediction && !h.prediction.abstain && h.prediction.side)
  const hits = graded.filter((h) => h.prediction!.side === h.label).length

  return (
    <Page title="Experiments" subtitle="Commit-before-reveal trials. ORACLE records your face while you silently pick one of two options, locks its prediction with a cryptographic commitment, and only then do you say what you chose. Results are honest: abstentions and misses are kept.">
      {!ready && (
        <Card>
          <p className="mb-3 text-sm text-amber-200">Trials need tracking running and a recorded face baseline.</p>
          <TrackingControls />
        </Card>
      )}

      <Card title="Trial">
        {stage === 'setup' || stage === 'done' ? (
          <div className="space-y-4">
            {stage === 'done' && trial && commit && outcome && (
              <div className="rounded-lg bg-ink-800 p-4 text-sm">
                <div className="flex items-center gap-2 text-zinc-200">
                  You chose <strong>{outcome.side === 'left' ? trial.left : trial.right}</strong>.
                  {commit.prediction.abstain || !commit.prediction.side ? <Badge>ORACLE abstained</Badge> : commit.prediction.side === outcome.side ? <Badge tone="good">Prediction correct</Badge> : <Badge tone="bad">Prediction wrong</Badge>}
                </div>
                <p className="mt-2 flex items-center gap-1.5 text-xs text-zinc-500"><ShieldCheck className="size-3.5" /> Commitment {outcome.verified ? 'verified' : 'FAILED verification'}</p>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <input value={a} onChange={(e) => setA(e.target.value)} maxLength={100} placeholder="Option A (e.g. Tea)" className="rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm text-white placeholder:text-zinc-600" />
              <input value={b} onChange={(e) => setB(e.target.value)} maxLength={100} placeholder="Option B (e.g. Coffee)" className="rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm text-white placeholder:text-zinc-600" />
            </div>
            <Button variant="primary" busy={busy === 'start'} disabled={!ready || !a.trim() || !b.trim() || a.trim() === b.trim()} onClick={start}>Start trial</Button>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-4 text-center">
              {(['left', 'right'] as const).map((s) => (
                <button key={s} disabled={stage !== 'locked' || busy === 'answer'} onClick={() => answer(s)} className="rounded-xl border border-ink-600 bg-ink-800 px-4 py-10 text-lg font-medium text-white transition-colors enabled:hover:border-accent enabled:hover:bg-ink-700 disabled:cursor-default">
                  {s === 'left' ? trial?.left : trial?.right}
                </button>
              ))}
            </div>
            {stage === 'thinking' ? (
              <p className="text-center text-sm text-zinc-400">Look at the options and silently choose one. Locking in {left}s...</p>
            ) : (
              commit && (
                <div className="rounded-lg bg-ink-800 p-4 text-center text-sm">
                  <p className="flex items-center justify-center gap-2 text-zinc-300"><Lock className="size-4 text-accent" /> Prediction locked. Now click the option you chose.</p>
                  <p className="mt-2 break-all font-mono text-xs text-zinc-600">commitment {commit.commitment}</p>
                  <p className="mt-2 text-xs text-zinc-500">{commit.prediction.abstain || !commit.prediction.side ? `Abstained: ${commit.prediction.reason ?? 'not confident'}` : `Predicted ${commit.prediction.side} (${pct(commit.prediction.confidence ?? 0)} confidence)`}</p>
                </div>
              )
            )}
          </div>
        )}
        <div className="mt-3"><ErrorLine error={error} /></div>
      </Card>

      <Card title="History" hint={graded.length ? `Model answered ${graded.length} of the last ${history.length} trials and got ${hits} right (${pct(hits / graded.length)}). Chance is 50%.` : 'Trials are stored locally.'}>
        {history.length === 0 ? (
          <Empty>No trials yet.</Empty>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-zinc-500"><tr><th className="pb-2 font-normal">Options</th><th className="pb-2 font-normal">Chose</th><th className="pb-2 font-normal">Prediction</th></tr></thead>
            <tbody className="divide-y divide-ink-700">
              {history.map((h) => (
                <tr key={h.id}>
                  <td className="py-2 text-zinc-300">{h.left_option} / {h.right_option}</td>
                  <td className="py-2 text-zinc-400">{h.label ? (h.label === 'left' ? h.left_option : h.right_option) : '-'}</td>
                  <td className="py-2">{!h.prediction ? <Badge>none</Badge> : h.prediction.abstain ? <Badge>abstained</Badge> : h.label ? <Badge tone={h.prediction.side === h.label ? 'good' : 'bad'}>{h.prediction.side === h.label ? 'hit' : 'miss'}</Badge> : <Badge tone="warn">unanswered</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="mt-4 flex items-center gap-3">
          <Button onClick={() => void run('audit', async () => setAudit(await api.get('/api/experiments/audit')))} busy={busy === 'audit'}>Audit commitments</Button>
          {audit && <span className="text-xs text-zinc-400">{audit.unverifiable.length === 0 ? `All ${audit.completed_trials} completed trials verify: every prediction was locked before its answer.` : `${audit.unverifiable.length} trials failed verification.`}</span>}
        </div>
      </Card>
    </Page>
  )
}
