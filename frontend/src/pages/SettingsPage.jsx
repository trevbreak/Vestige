/**
 * Settings Page — Phase 7 + System Status.
 *
 * Runtime-tunable configuration panel. Changes take effect immediately
 * without requiring a server restart. Values reset on restart — edit .env
 * for permanent changes.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api/client'
import styles from './SettingsPage.module.css'

const SECTIONS = [
  {
    title: 'LLM Routing',
    fields: [
      { key: 'ollama_model', label: 'Ollama Model', type: 'text', hint: 'e.g. llama3.1:8b' },
      { key: 'claude_model', label: 'Claude Model', type: 'text', hint: 'e.g. claude-haiku-4-5-20251001' },
      { key: 'claude_max_tokens', label: 'Claude Max Tokens', type: 'number', min: 64, max: 4096, step: 64 },
      { key: 'ollama_timeout_s', label: 'Ollama Timeout (s)', type: 'number', min: 5, max: 300, step: 1 },
    ],
  },
  {
    title: 'Audio Input',
    fields: [
      { key: 'vad_threshold', label: 'Voice Activation Sensitivity', type: 'slider', min: 0.05, max: 0.99, step: 0.05, hint: 'How sensitive the mic trigger is. Lower = picks up quieter speech; higher = ignores soft sounds.' },
      { key: 'whisper_no_speech_threshold', label: 'Noise Rejection', type: 'slider', min: 0.1, max: 1.0, step: 0.05, hint: 'Filters out segments Whisper thinks are silence or noise. Lower = more permissive; higher = stricter.' },
      { key: 'whisper_log_prob_threshold', label: 'Transcription Confidence', type: 'slider', min: -5.0, max: 0.0, step: 0.1, hint: 'Minimum confidence for a transcription to be kept. More negative = accept low-confidence results; closer to 0 = strict.' },
      { key: 'aec_decay_ms', label: 'AEC Decay (ms)', type: 'number', min: 0, max: 2000, step: 50, hint: 'Mic gate time after TTS ends' },
    ],
  },
  {
    title: 'Response Timing',
    fields: [
      { key: 'silence_gap_trigger', label: 'Silence Gap Trigger (s)', type: 'number', min: 1, max: 30, step: 0.5, hint: 'Seconds of silence before passive avatar speaks' },
      { key: 'self_cooldown_seconds', label: 'Self Cooldown (s)', type: 'number', min: 1, max: 120, step: 1, hint: 'Min gap before same avatar speaks again' },
      { key: 'avatar_cooldown_seconds', label: 'Avatar Cooldown (s)', type: 'number', min: 0.5, max: 30, step: 0.5, hint: 'Min gap between any two avatars' },
      { key: 'interrupt_confidence_threshold', label: 'Interrupt Threshold', type: 'number', min: 0.1, max: 1.0, step: 0.05, hint: 'Score required to trigger an avatar response' },
    ],
  },
  {
    title: 'Naturalism',
    fields: [
      { key: 'response_jitter_min', label: 'Response Jitter Min (s)', type: 'number', min: 0, max: 10, step: 0.5 },
      { key: 'response_jitter_max', label: 'Response Jitter Max (s)', type: 'number', min: 0, max: 20, step: 0.5 },
      { key: 'backchannel_min_gap', label: 'Backchannel Min Gap (s)', type: 'number', min: 2, max: 60, step: 1, hint: 'Min seconds between backchannels' },
      { key: 'backchannel_chance', label: 'Backchannel Chance', type: 'number', min: 0, max: 1, step: 0.05, hint: 'Probability of backchannel when eligible (0-1)' },
    ],
  },
  {
    title: 'Memory',
    fields: [
      { key: 'memory_top_k', label: 'Memory Top-K', type: 'number', min: 1, max: 20, step: 1, hint: 'Number of memory chunks retrieved per prompt' },
      { key: 'transcript_context_lines', label: 'Transcript Context Lines', type: 'number', min: 5, max: 100, step: 5, hint: 'Recent transcript lines sent to LLM' },
    ],
  },
]

// ── System Status ──────────────────────────────────────────────────────────

function StatusDot({ ok, loading }) {
  if (loading) return <span className={styles.dotLoading} />
  return <span className={ok ? styles.dotOk : styles.dotFail} />
}

function StatusRow({ label, ok, loading, detail }) {
  return (
    <div className={styles.statusRow}>
      <StatusDot ok={ok} loading={loading} />
      <span className={styles.statusLabel}>{label}</span>
      {detail && <span className={styles.statusDetail}>{detail}</span>}
    </div>
  )
}

function MicLevelBar({ level }) {
  const pct = Math.min(100, Math.round(level * 100))
  const color = pct > 80 ? 'var(--crimson-light)' : pct > 30 ? 'var(--status-active)' : 'var(--gold-dim)'
  return (
    <div className={styles.micBar}>
      <div className={styles.micBarFill} style={{ width: `${pct}%`, background: color }} />
      <span className={styles.micBarLabel}>{pct}% peak</span>
    </div>
  )
}

function SystemStatusSection({ refreshTrigger }) {
  const [status, setStatus] = useState(null)
  const [devices, setDevices] = useState(null)
  const [loading, setLoading] = useState(true)
  const [micResult, setMicResult] = useState(null)
  const [micTesting, setMicTesting] = useState(false)
  const [selectedDevice, setSelectedDevice] = useState(null)
  const [deviceSaving, setDeviceSaving] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [s, d] = await Promise.all([api.getSystemStatus(), api.getAudioDevices()])
      setStatus(s)
      setDevices(d)
      setSelectedDevice(null) // reset pending selection on refresh
    } catch (e) {
      console.error('Status check failed:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh, refreshTrigger])

  const handleMicTest = async () => {
    setMicTesting(true)
    setMicResult(null)
    try {
      const r = await api.runMicTest()
      setMicResult(r)
    } catch (e) {
      setMicResult({ ok: false, error: e.message, peak: 0 })
    } finally {
      setMicTesting(false)
    }
  }

  const handleDeviceApply = async () => {
    if (selectedDevice === null) return
    setDeviceSaving(true)
    try {
      await api.updateSettings({ mic_device_index: selectedDevice })
      await refresh()
    } catch (e) {
      console.error('Failed to update mic device:', e)
    } finally {
      setDeviceSaving(false)
    }
  }

  const cfg = status?.config ?? {}
  const ollama = status?.services?.ollama ?? {}
  const whisper = status?.models?.faster_whisper ?? {}
  const silero = status?.models?.silero_vad ?? {}
  const torchInfo = status?.models?.torch ?? {}
  const sd = status?.audio?.sounddevice ?? {}
  const ollamaModels = ollama.models ?? []
  const configuredModel = cfg.ollama_model ?? ''
  const modelInstalled = ollamaModels.some(
    (m) => m === configuredModel || m.startsWith(configuredModel.split(':')[0])
  )
  const activeDeviceIndex = cfg.mic_device_index ?? 0
  const pendingIndex = selectedDevice !== null ? selectedDevice : activeDeviceIndex

  return (
    <section className={`card ${styles.section}`}>
      <div className={styles.sectionTitleRow}>
        <h2 className={styles.sectionTitle}>System Status</h2>
        <button className="btn btn-sm" onClick={refresh} disabled={loading}>
          {loading ? 'Checking...' : 'Refresh'}
        </button>
      </div>

      <div className={styles.statusGrid}>
        <div className={styles.statusGroup}>
          <div className={styles.statusGroupTitle}>Services</div>
          <StatusRow
            label="Ollama"
            ok={ollama.ok}
            loading={loading}
            detail={ollama.ok
              ? `${ollamaModels.length} model(s) loaded`
              : ollama.error}
          />
          <StatusRow
            label={`  ${configuredModel || '?'}`}
            ok={modelInstalled}
            loading={loading}
            detail={modelInstalled
              ? 'ready'
              : `not found — run: ollama pull ${configuredModel}`}
          />
          <StatusRow
            label="Anthropic API key"
            ok={cfg.anthropic_api_key_set}
            loading={loading}
            detail={cfg.anthropic_api_key_set ? 'set' : 'missing — enter in Credentials below'}
          />
        </div>

        <div className={styles.statusGroup}>
          <div className={styles.statusGroupTitle}>Models / Packages</div>
          <StatusRow
            label="faster-whisper"
            ok={whisper.ok}
            loading={loading}
            detail={whisper.ok ? `model: ${cfg.whisper_model}` : whisper.error}
          />
          <StatusRow
            label="silero-vad"
            ok={silero.ok}
            loading={loading}
            detail={silero.error}
          />
          <StatusRow
            label="CUDA / torch"
            ok={torchInfo.cuda}
            loading={loading}
            detail={torchInfo.cuda
              ? torchInfo.device
              : (torchInfo.ok ? 'CPU only — audio will be slow' : torchInfo.error)}
          />
          <StatusRow
            label="sounddevice"
            ok={sd.ok}
            loading={loading}
            detail={sd.error}
          />
        </div>

        <div className={styles.statusGroup}>
          <div className={styles.statusGroupTitle}>Microphone</div>
          {devices?.devices?.length > 0 ? (
            <div className={styles.micSelectRow}>
              <select
                className={styles.input}
                style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem' }}
                value={pendingIndex}
                onChange={(e) => setSelectedDevice(Number(e.target.value))}
                disabled={loading || deviceSaving}
              >
                {devices.devices.map((d) => (
                  <option key={d.index} value={d.index}>
                    [{d.index}] {d.name}
                  </option>
                ))}
              </select>
              {selectedDevice !== null && selectedDevice !== activeDeviceIndex && (
                <button
                  className="btn btn-sm btn-primary"
                  onClick={handleDeviceApply}
                  disabled={deviceSaving}
                >
                  {deviceSaving ? 'Applying...' : 'Apply'}
                </button>
              )}
            </div>
          ) : (
            <div className={styles.statusRow}>
              <span className={styles.statusDetail}>{loading ? '...' : 'No input devices found'}</span>
            </div>
          )}
          <div className={styles.micTestRow}>
            <button
              className="btn btn-sm"
              onClick={handleMicTest}
              disabled={micTesting || !sd.ok}
            >
              {micTesting ? 'Recording 1s...' : 'Test Mic'}
            </button>
            {micResult?.ok && <MicLevelBar level={micResult.peak} />}
            {micResult && !micResult.ok && (
              <span className={styles.statusDetail} style={{ color: 'var(--crimson-light)' }}>
                {micResult.error}
              </span>
            )}
            {micResult?.ok && micResult.peak < 0.01 && (
              <span className={styles.statusDetail} style={{ color: 'var(--amber)' }}>
                Very quiet — check MIC_DEVICE_INDEX in .env
              </span>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

// ── Credentials ────────────────────────────────────────────────────────────

function ApiKeySection({ onSaved }) {
  const [key, setKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState(null)

  const handleSave = async () => {
    if (!key.trim()) return
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await api.updateSettings({ anthropic_api_key: key.trim() })
      setKey('')
      setSaved(true)
      onSaved()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={`card ${styles.section}`}>
      <h2 className={styles.sectionTitle}>Credentials</h2>
      <div className={styles.grid}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="anthropic_api_key">
            Anthropic API Key
          </label>
          <input
            id="anthropic_api_key"
            type="password"
            value={key}
            onChange={(e) => { setKey(e.target.value); setSaved(false) }}
            placeholder="sk-ant-..."
            className={styles.input}
            autoComplete="off"
          />
          <span className={styles.hint}>
            Required for Claude routing. Stored in memory only — add to .env for persistence.
          </span>
        </div>
      </div>
      <div className={styles.apiKeyFooter}>
        {error && <span className={styles.error}>{error}</span>}
        {saved && <span className={styles.savedNote}>Key updated</span>}
        <button
          className="btn btn-sm btn-primary"
          onClick={handleSave}
          disabled={!key.trim() || saving}
        >
          {saving ? 'Saving...' : 'Set Key'}
        </button>
      </div>
    </section>
  )
}


// ── Log Viewer ─────────────────────────────────────────────────────────────

const LEVEL_COLORS = {
  DEBUG: 'var(--text-muted)',
  INFO: 'var(--text-secondary)',
  WARNING: 'var(--amber)',
  ERROR: 'var(--crimson-light)',
  CRITICAL: 'var(--crimson-light)',
}

function LogViewer() {
  const [logs, setLogs] = useState([])
  const [level, setLevel] = useState('INFO')
  const [loading, setLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const bottomRef = useRef(null)

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getLogs(200, level)
      setLogs(data.logs || [])
    } catch (e) {
      console.error('getLogs failed:', e)
    } finally {
      setLoading(false)
    }
  }, [level])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(fetchLogs, 2000)
    return () => clearInterval(id)
  }, [autoRefresh, fetchLogs])

  useEffect(() => {
    bottomRef.current?.scrollIntoView()
  }, [logs])

  return (
    <section className={`card ${styles.section}`}>
      <div className={styles.sectionTitleRow}>
        <h2 className={styles.sectionTitle}>Logs</h2>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <select value={level} onChange={(e) => setLevel(e.target.value)}
            className={styles.input} style={{ padding: "0.2rem 0.4rem", fontSize: "0.75rem" }}>
            <option value="DEBUG">DEBUG+</option>
            <option value="INFO">INFO+</option>
            <option value="WARNING">WARNING+</option>
            <option value="ERROR">ERROR+</option>
          </select>
          <label className={styles.statusLabel}
            style={{ display: "flex", alignItems: "center", gap: "0.3rem", cursor: "pointer" }}>
            <input type="checkbox" checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)} />
            Auto
          </label>
          <button className="btn btn-sm" onClick={fetchLogs} disabled={loading}>
            {loading ? "..." : "Refresh"}
          </button>
        </div>
      </div>
      <div className={styles.logBox}>
        {logs.length === 0 && <span className={styles.statusDetail}>No log entries yet.</span>}
        {logs.length > 0 && (
          <div className={styles.logTailLabel}>↑ older — newer ↓</div>
        )}
        {logs.map((entry, i) => (
          <div key={i} className={styles.logLine}>
            <span className={styles.logTs} title={entry.ts}>{entry.ts && entry.ts.slice(11, 19)}</span>
            <span className={styles.logLevel} style={{ color: LEVEL_COLORS[entry.level] || "inherit" }}>
              {(entry.level || "").padEnd(7)}
            </span>
            <span className={styles.logLogger}>{entry.logger ? entry.logger.split(".").pop() : ""}</span>
            <span className={styles.logMsg}>{entry.msg}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}
// ── Main page ──────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [values, setValues] = useState(null)
  const [dirty, setDirty] = useState({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [savedAt, setSavedAt] = useState(null)
  const [statusRefresh, setStatusRefresh] = useState(0)

  const load = useCallback(async () => {
    try {
      const data = await api.getSettings()
      setValues(data)
      setDirty({})
    } catch (e) {
      console.error('Failed to load settings:', e)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleChange = (key, raw, type) => {
    const val = type === 'number' ? parseFloat(raw) : raw
    setDirty((prev) => ({ ...prev, [key]: val }))
  }

  const handleSave = async () => {
    if (Object.keys(dirty).length === 0) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await api.updateSettings(dirty)
      setValues(updated)
      setDirty({})
      setSavedAt(new Date().toLocaleTimeString())
    } catch (e) {
      setSaveError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => { setDirty({}) }

  if (!values) {
    return <div className={styles.loading}>Loading settings...</div>
  }

  const hasDirty = Object.keys(dirty).length > 0

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1>Settings</h1>
        <p className={styles.subtitle}>
          Changes take effect immediately. Values reset on server restart — edit{' '}
          <code>.env</code> for permanent changes.
        </p>
      </div>

      <SystemStatusSection refreshTrigger={statusRefresh} />

      <ApiKeySection onSaved={() => setStatusRefresh((n) => n + 1)} />

      {SECTIONS.map((section) => (
        <section key={section.title} className={`card ${styles.section}`}>
          <h2 className={styles.sectionTitle}>{section.title}</h2>
          <div className={styles.grid}>
            {section.fields.map(({ key, label, type, min, max, step, hint }) => {
              const current = dirty[key] !== undefined ? dirty[key] : values[key]
              const isDirty = dirty[key] !== undefined
              return (
                <div key={key} className={`${styles.field} ${isDirty ? styles.fieldDirty : ''} ${type === 'slider' ? styles.fieldWide : ''}`}>
                  <label className={styles.label} htmlFor={key}>
                    {label}
                    {isDirty && <span className={styles.dirtyDot} title="Unsaved change" />}
                  </label>
                  {type === 'slider' ? (
                    <div className={styles.sliderRow}>
                      <input
                        id={key}
                        type="range"
                        min={min}
                        max={max}
                        step={step}
                        value={current ?? min}
                        onChange={(e) => handleChange(key, e.target.value, 'number')}
                        className={styles.slider}
                      />
                      <span className={styles.sliderValue}>{(current ?? min).toFixed(2)}</span>
                    </div>
                  ) : (
                    <input
                      id={key}
                      type={type}
                      min={min}
                      max={max}
                      step={step}
                      value={current ?? ''}
                      onChange={(e) => handleChange(key, e.target.value, type)}
                      className={styles.input}
                    />
                  )}
                  {hint && <span className={styles.hint}>{hint}</span>}
                </div>
              )
            })}
          </div>
        </section>
      ))}

      <LogViewer />

      <div className={styles.footer}>
        {saveError && <span className={styles.error}>{saveError}</span>}
        {savedAt && !hasDirty && (
          <span className={styles.savedNote}>Saved at {savedAt}</span>
        )}
        <div className={styles.footerButtons}>
          <button
            className="btn btn-sm"
            onClick={handleReset}
            disabled={!hasDirty || saving}
          >
            Discard Changes
          </button>
          <button
            className="btn btn-sm btn-primary"
            onClick={handleSave}
            disabled={!hasDirty || saving}
          >
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
