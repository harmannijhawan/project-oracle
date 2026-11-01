import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from '../lib/api'
import { useAction } from '../lib/useAction'
import { Badge, Button, Card, Empty, ErrorLine, Page } from '../components/ui'
import type { UIElement, WindowInfo } from '../lib/types'

interface Snapshot { windows: WindowInfo[]; elements: UIElement[]; foreground: unknown }

export default function Screen(_: { go: (id: string) => void }) {
  const { run, busy, error } = useAction()
  const [snap, setSnap] = useState<Snapshot | null>(null)
  const load = () => void run('snap', async () => setSnap(await api.get<Snapshot>('/api/screen/snapshot')))
  useEffect(load, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Page title="Screen context" subtitle="Windows UI Automation tells ORACLE which windows and controls exist and where. It reads control names and positions only, never screenshots, and only while you are using it." actions={<Button busy={busy === 'snap'} onClick={load}><RefreshCw className="size-4" /> Refresh</Button>}>
      <ErrorLine error={error} />
      <Card title="Windows" hint={snap ? `${snap.windows.length} visible` : undefined}>
        {!snap || snap.windows.length === 0 ? <Empty>No windows reported. UI Automation is only available on Windows.</Empty> : (
          <ul className="divide-y divide-ink-700 text-sm">
            {snap.windows.map((w) => (
              <li key={w.handle} className="flex items-center gap-3 py-2">
                <span className="flex-1 truncate text-zinc-200">{w.title || '(untitled)'}</span>
                <span className="text-xs text-zinc-500">{w.app}</span>
                {w.foreground && <Badge tone="good">foreground</Badge>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title="Interactive elements" hint={snap ? `${snap.elements.length} found (max 300 shown)` : undefined}>
        {!snap || snap.elements.length === 0 ? <Empty>No interactive elements found.</Empty> : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-ink-900 text-xs text-zinc-500"><tr><th className="pb-2 font-normal">Name</th><th className="pb-2 font-normal">Type</th><th className="pb-2 font-normal">App</th><th className="pb-2 font-normal">Position</th></tr></thead>
              <tbody className="divide-y divide-ink-700">
                {snap.elements.map((e) => (
                  <tr key={e.id} className={e.enabled ? '' : 'opacity-50'}>
                    <td className="max-w-56 truncate py-1.5 text-zinc-200">{e.name || '(no name)'}</td>
                    <td className="py-1.5 text-zinc-400">{e.control_type}</td>
                    <td className="py-1.5 text-zinc-500">{e.app}</td>
                    <td className="py-1.5 font-mono text-xs text-zinc-600">{e.rect.left},{e.rect.top} {e.rect.right - e.rect.left}x{e.rect.bottom - e.rect.top}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Page>
  )
}
