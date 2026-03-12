/**
 * Settings Page — Phase 7.
 *
 * Runtime-tunable configuration panel. Changes take effect immediately
 * without requiring a server restart. Values reset on restart — edit .env
 * for permanent changes.
 */

import { useState, useEffect, useCallback } from 'react'
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
      { key: 'vad_threshold', label: 'VAD Threshold', type: 'number', min: 0.1, max: 0.99, step: 0.05, hint: 'Silero VAD sensitivity (0.1 = sensitive, 0.99 = strict)' },
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
      { key: 'backchannel_chance', label: 'Backchannel Chance', type: 'number', min: 0, max: 1, step: 0.05, hint: 'Probability of backchannel when eligible (0–1)' },
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

export default function SettingsPage() {
  const [values, setValues] = useState(null)
  const [dirty, setDirty] = useState({})     // { key: newValue } — pending changes
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [savedAt, setSavedAt] = useState(null)

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

  const handleReset = () => {
    setDirty({})
  }

  if (!values) {
    return <div className={styles.loading}>Loading settings…</div>
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

      {SECTIONS.map((section) => (
        <section key={section.title} className={`card ${styles.section}`}>
          <h2 className={styles.sectionTitle}>{section.title}</h2>
          <div className={styles.grid}>
            {section.fields.map(({ key, label, type, min, max, step, hint }) => {
              const current = dirty[key] !== undefined ? dirty[key] : values[key]
              const isDirty = dirty[key] !== undefined
              return (
                <div key={key} className={`${styles.field} ${isDirty ? styles.fieldDirty : ''}`}>
                  <label className={styles.label} htmlFor={key}>
                    {label}
                    {isDirty && <span className={styles.dirtyDot} title="Unsaved change" />}
                  </label>
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
                  {hint && <span className={styles.hint}>{hint}</span>}
                </div>
              )
            })}
          </div>
        </section>
      ))}

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
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
