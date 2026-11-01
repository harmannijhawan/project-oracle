import { useEffect, useState } from 'react'
import { FolderOpen, Trash2 } from 'lucide-react'
import { api, bridge } from '../lib/api'
import { useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Button, Card, ErrorLine, Page, Slider, Toggle } from '../components/ui'
import type { Settings } from '../lib/types'

export default function SettingsPage(_: { go: (id: string) => void }) {
  const { refresh } = useOracle()
  const { run, busy, error } = useAction()
  const [s, setS] = useState<Settings | null>(null)
  const [shortcut, setShortcut] = useState('')
  const [info, setInfo] = useState<{ version: string; dataDir: string; packaged: boolean } | null>(null)
  const [confirm, setConfirm] = useState('')
  const [deleted, setDeleted] = useState<string | null>(null)

  useEffect(() => {
    void run('load', async () => { const v = await api.get<Settings>('/api/settings'); setS(v); setShortcut(v.emergency_shortcut) })
    void bridge().appInfo().then(setInfo)
  }, [run])

  const save = (patch: Partial<Settings>) => void run('save', async () => { const v = await api.put<Settings>('/api/settings', patch); setS(v); setShortcut(v.emergency_shortcut); await refresh() })
  if (!s) return <Page title="Settings"><ErrorLine error={error} /></Page>

  return (
    <Page title="Settings" subtitle="Changes apply immediately and are saved on this computer only.">
      <ErrorLine error={error} />
      <Card title="Gaze and dwell">
        <Slider label="Dwell time" value={s.dwell_s} min={0.3} max={5} step={0.1} unit=" s" onChange={(v) => save({ dwell_s: v })} description="How long you must hold your gaze on a target before it counts as a deliberate selection." />
        <Slider label="Dwell radius" value={s.dwell_radius_px} min={15} max={300} step={5} unit=" px" onChange={(v) => save({ dwell_radius_px: v })} description="How far your gaze may drift while still counting as the same fixation." />
        <Slider label="Smoothing" value={s.smoothing} min={0.1} max={5} step={0.1} onChange={(v) => save({ smoothing: v })} description="Lower is steadier but slower to follow." />
        <Slider label="Dead zone" value={s.deadzone_px} min={0} max={60} step={1} unit=" px" onChange={(v) => save({ deadzone_px: v })} description="Movements smaller than this are ignored to stop jitter." />
        <Slider label="Minimum tracking quality" value={s.min_quality} min={0.2} max={0.95} step={0.05} onChange={(v) => save({ min_quality: v })} description="Below this, ORACLE stops acting and pauses." />
        <Toggle label="Facial gestures" description="Allow a deliberate, long blink to count as a selection. Ordinary blinks are ignored." checked={s.gestures_enabled} onChange={(v) => save({ gestures_enabled: v })} />
      </Card>
      <Card title="Prediction">
        <Slider label="Abstain below confidence" value={s.abstain_below} min={0.5} max={0.95} step={0.01} onChange={(v) => save({ abstain_below: v })} description="The personal model declines to predict when it is less confident than this. Applies the next time you train." />
      </Card>
      <Card title="Camera and shortcut">
        <div className="grid grid-cols-2 gap-5">
          <label className="block text-sm text-zinc-100">Camera index
            <input type="number" min={0} max={16} value={s.camera_index} onChange={(e) => save({ camera_index: Number(e.target.value) })} className="mt-1.5 w-full rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 text-sm" />
            <span className="mt-1 block text-xs text-zinc-500">0 is usually the built-in webcam.</span>
          </label>
          <div className="text-sm text-zinc-100">Emergency shortcut
            <div className="mt-1.5 flex gap-2">
              <input value={shortcut} onChange={(e) => setShortcut(e.target.value)} className="min-w-0 flex-1 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-sm" />
              <Button busy={busy === 'save'} disabled={shortcut === s.emergency_shortcut} onClick={() => save({ emergency_shortcut: shortcut })}>Save</Button>
            </div>
            <span className="mt-1 block text-xs text-zinc-500">For example Ctrl+Alt+Shift+Q. A fixed backup shortcut (Ctrl+Alt+Shift+Escape) always works too.</span>
          </div>
        </div>
      </Card>
      <Card title="Privacy" hint="No cloud services, no telemetry, no images stored. Only numeric measurements, your trials and your settings live in the folder below.">
        <div className="flex items-center gap-3">
          <Button onClick={() => void bridge().openDataFolder()}><FolderOpen className="size-4" /> Open data folder</Button>
          {info && <span className="truncate font-mono text-xs text-zinc-500">{info.dataDir}</span>}
        </div>
        <div className="mt-5 rounded-lg border border-red-500/25 bg-red-500/5 p-4">
          <h3 className="text-sm font-semibold text-red-200">Delete all personal data</h3>
          <p className="mt-1 text-xs leading-relaxed text-zinc-400">Removes calibration, face baseline, trials, trained models and interaction history. This cannot be undone. Type DELETE to confirm.</p>
          <div className="mt-3 flex gap-2">
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="DELETE" className="w-40 rounded-lg border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-sm" />
            <Button variant="danger" disabled={confirm !== 'DELETE'} busy={busy === 'del'} onClick={() => void run('del', async () => { const c = await api.post<Record<string, number>>('/api/privacy/delete', { confirm: 'DELETE' }); setDeleted(Object.entries(c).map(([k, v]) => `${v} ${k}`).join(', ') || 'done'); setConfirm(''); await refresh() })}><Trash2 className="size-4" /> Delete</Button>
          </div>
          {deleted && <p className="mt-2 text-xs text-emerald-300">Deleted: {deleted}</p>}
        </div>
      </Card>
      {info && <p className="text-center text-xs text-zinc-600">Project ORACLE {info.version} {info.packaged ? '' : '(development build)'}</p>}
    </Page>
  )
}
