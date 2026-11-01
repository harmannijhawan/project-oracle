export type SafetyState = 'active' | 'stopped' | 'auto_paused'

export interface GazePoint {
  x: number
  y: number
  dwell: number
}

export interface Evidence {
  name: string
  value: number
  detail: string
}

export interface Suggestion {
  element_key: string
  element_id: string
  label: string
  app: string
  control_type: string
  action: string
  x: number
  y: number
  probability: number
  confidence: number
  risk: number
  needs_confirmation: boolean
  evidence: Evidence[]
}

export interface Decision {
  phase: 'idle' | 'looking' | 'considering' | 'select_ready' | 'paused' | string
  suggestions: Suggestion[]
  ambiguous?: boolean
  reason: string
  select_target?: Suggestion | null
}

export interface ActionItem {
  ts: number
  kind: string
  source: string
  label: string
  status: string
  reason: string
  risk: number
}

export interface CalibrationInfo {
  n_samples: number
  mean_error_px: number
  p90_error_px: number
  relative_error: number
}

export interface MonitorInfo {
  id: string | number
  width: number
  height: number
  primary?: boolean
}

export interface BaselineInfo {
  n: number
  ready: boolean
  collecting: boolean
  features: string[]
}

export interface EngineState {
  safety: { state: SafetyState; reason: string | null; shortcut: string }
  tracking: boolean
  face: boolean
  quality: number
  gaze: GazePoint | null
  calibrated: boolean
  calibration: CalibrationInfo | null
  cursor_control: boolean
  dwell_click: boolean
  decision: Decision
  baseline: BaselineInfo
  model: { name: string; calibrated: boolean } | null
  monitor: MonitorInfo
  monitors: MonitorInfo[]
  recent_actions: ActionItem[]
  last_error: string | null
}

export interface Frame {
  type: 'frame'
  t: number
  face: boolean
  quality: number
  gaze: GazePoint | null
  decision: { phase: string; reason: string; ambiguous?: boolean }
  safety: SafetyState
}

export interface Settings {
  dwell_s: number
  dwell_radius_px: number
  smoothing: number
  deadzone_px: number
  min_quality: number
  emergency_shortcut: string
  cursor_control: boolean
  dwell_click: boolean
  gestures_enabled: boolean
  enabled_actions: string[]
  camera_index: number
  abstain_below: number
}

export interface SafetyEventRow {
  id: number
  ts: number
  kind: string
  reason: string
  detail: string
}

export interface Prediction {
  side: 'left' | 'right' | null
  abstain: boolean
  reason?: string
  p_right: number | null
  confidence?: number
  model?: string
}

export interface TrialRow {
  id: string
  session_id: string
  idx: number
  left_option: string
  right_option: string
  prediction: Prediction | null
  label: 'left' | 'right' | null
  locked_at: number | null
  revealed_at: number | null
}

export interface PredictorResult {
  name: string
  n_answered: number
  n_correct: number
  n_abstained: number
  accuracy: number
  ci95: [number, number]
  p_vs_chance: number
}

export interface Evaluation {
  n_train: number
  n_test: number
  train_sessions: number
  test_sessions: number
  selected_model: string
  results: Record<string, PredictorResult>
  p_face_vs_context: number
  verdict: string
  version?: string | number
}

export interface WindowInfo {
  handle: number
  title: string
  app: string
  z_order: number
  foreground: boolean
}

export interface UIElement {
  id: string
  name: string
  control_type: string
  app: string
  enabled: boolean
  rect: { left: number; top: number; right: number; bottom: number }
}

export const RISK_LABEL: Record<number, string> = { 1: 'Low', 2: 'Medium', 3: 'High' }
