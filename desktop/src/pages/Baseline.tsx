import { api } from '../lib/api'
import { useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Badge, Button, Card, ErrorLine, Page, Stat } from '../components/ui'
import TrackingControls from '../components/TrackingControls'
import type { BaselineInfo } from '../lib/types'

export default function Baseline(_: { go: (id: string) => void }) {
  const { state, refresh } = useOracle()
  const { run, busy, error } = useAction()
  if (!state) return <Page title="Face baseline">{null}</Page>
  const b = state.baseline
  const act = (name: string, path: string) => void run(name, async () => { await api.post<BaselineInfo>(path); await refresh() })
  return (
    <Page title="Face baseline" subtitle="ORACLE learns what your face looks like at rest, so later signals are measured against you rather than an average person. Only numeric measurements are stored, never images.">
      <Card>
        <ol className="mb-5 list-decimal space-y-1 pl-5 text-sm text-zinc-400">
          <li>Start tracking and face the screen with a relaxed, neutral expression.</li>
          <li>Press Record, then read or browse naturally for about 30 seconds.</li>
          <li>Press Finish to save the baseline.</li>
        </ol>
        <TrackingControls />
        <div className="mt-5 flex gap-2">
          {b.collecting ? (
            <Button variant="primary" busy={busy === 'finish'} onClick={() => act('finish', '/api/baseline/finish')}>Finish and save</Button>
          ) : (
            <Button variant="primary" busy={busy === 'start'} disabled={!state.tracking} onClick={() => act('start', '/api/baseline/start')}>{b.ready ? 'Record again' : 'Record baseline'}</Button>
          )}
        </div>
        <div className="mt-3"><ErrorLine error={error} /></div>
      </Card>
      <Card title="Status">
        <div className="grid grid-cols-3 gap-6">
          <Stat label="Frames collected" value={b.n} />
          <div>
            <div className="text-xs text-zinc-500">State</div>
            <div className="mt-2">{b.collecting ? <Badge tone="warn">Recording</Badge> : b.ready ? <Badge tone="good">Ready</Badge> : <Badge>Not recorded</Badge>}</div>
          </div>
          <Stat label="Measurements per frame" value={b.features.length} />
        </div>
        {b.features.length > 0 && <p className="mt-4 font-mono text-xs leading-relaxed text-zinc-600">{b.features.join(', ')}</p>}
      </Card>
    </Page>
  )
}
