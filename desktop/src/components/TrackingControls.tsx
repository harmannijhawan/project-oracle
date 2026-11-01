import { Camera, Play, Square, Sparkles } from 'lucide-react'
import { api } from '../lib/api'
import { useOracle } from '../lib/store'
import { useAction } from '../lib/useAction'
import { Button, ErrorLine } from './ui'

/** Start/stop camera tracking (or the built-in simulator, for trying the app without a webcam). */
export default function TrackingControls() {
  const { state, ensureTracking, refresh } = useOracle()
  const { run, busy, error } = useAction()
  const on = state?.tracking ?? false
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {on ? (
          <Button busy={busy === 'stop'} onClick={() => void run('stop', async () => { await api.post('/api/tracking/stop'); await refresh() })}>
            <Square className="size-4" />
            Stop tracking
          </Button>
        ) : (
          <>
            <Button variant="primary" busy={busy === 'start'} onClick={() => void run('start', () => ensureTracking(false))}>
              <Camera className="size-4" />
              Start camera
            </Button>
            <Button busy={busy === 'sim'} onClick={() => void run('sim', () => ensureTracking(true))}>
              <Sparkles className="size-4" />
              Use simulator
            </Button>
          </>
        )}
        {on && <span className="inline-flex items-center gap-1.5 text-xs text-emerald-300"><Play className="size-3" /> Tracking is running</span>}
      </div>
      <ErrorLine error={error} />
    </div>
  )
}
