import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSessionStore } from '../stores/sessionStore'
import { useAvatarStore } from '../stores/avatarStore'
import { api } from '../api/client'
import styles from './SessionsPage.module.css'

export default function SessionsPage() {
  const navigate = useNavigate()
  const { sessions, loading, error, fetchSessions, addSession, updateSession } = useSessionStore()
  const { avatars, fetchAvatars } = useAvatarStore()
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: '', campaign_name: '', avatar_ids: [] })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetchSessions()
    fetchAvatars()
  }, [fetchSessions, fetchAvatars])

  const toggleAvatar = (id) => {
    setForm((f) => ({
      ...f,
      avatar_ids: f.avatar_ids.includes(id)
        ? f.avatar_ids.filter((x) => x !== id)
        : [...f.avatar_ids, id],
    }))
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      const session = await api.createSession(form)
      addSession(session)
      setCreating(false)
      setForm({ name: '', campaign_name: '', avatar_ids: [] })
    } catch (err) {
      alert(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleEnd = async (id) => {
    if (!confirm('End this session?')) return
    try {
      const updated = await api.endSession(id)
      updateSession(updated)
    } catch (err) {
      alert(err.message)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1>Sessions</h1>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>+ New Session</button>
      </div>

      {creating && (
        <form className={`card ${styles.createForm}`} onSubmit={handleCreate}>
          <h3>New Session</h3>
          <div className={styles.formRow}>
            <div className={styles.field}>
              <label>Session Name</label>
              <input
                required
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="The Mines of Phandelver, Session 4"
              />
            </div>
            <div className={styles.field}>
              <label>Campaign</label>
              <input
                value={form.campaign_name}
                onChange={(e) => setForm((f) => ({ ...f, campaign_name: e.target.value }))}
                placeholder="Lost Mine of Phandelver"
              />
            </div>
          </div>

          <div className={styles.field}>
            <label>Select Avatars for this Session</label>
            <div className={styles.avatarPicker}>
              {avatars.map((a) => (
                <label key={a.id} className={styles.avatarCheck}>
                  <input
                    type="checkbox"
                    checked={form.avatar_ids.includes(a.id)}
                    onChange={() => toggleAvatar(a.id)}
                  />
                  {a.name} <span className="text-muted">({a.char_class})</span>
                </label>
              ))}
              {avatars.length === 0 && <span className="text-muted">No avatars created yet.</span>}
            </div>
          </div>

          <div className={styles.formFooter}>
            <button type="button" className="btn" onClick={() => setCreating(false)}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Creating…' : 'Create Session'}
            </button>
          </div>
        </form>
      )}

      {loading && <p className="text-muted">Loading sessions…</p>}
      {error && <p className="text-crimson">{error}</p>}

      {!loading && sessions.length === 0 && !creating && (
        <p className="text-muted" style={{ textAlign: 'center', marginTop: '3rem' }}>
          No sessions yet. Create one to start a game.
        </p>
      )}

      <div className={styles.list}>
        {sessions.map((s) => (
          <div key={s.id} className={`card ${styles.sessionCard}`}>
            <div>
              <div className={styles.sessionName}>{s.name}</div>
              {s.campaign_name && <div className="text-secondary">{s.campaign_name}</div>}
              <div className="text-muted" style={{ fontSize: '0.75rem', marginTop: '0.25rem' }}>
                {new Date(s.created_at).toLocaleString()} •{' '}
                {s.avatar_ids.length} avatar{s.avatar_ids.length !== 1 ? 's' : ''}
              </div>
            </div>
            <div className={styles.sessionStatus}>
              <span className={`mode-badge ${s.is_active ? 'mode-active' : 'mode-absent'}`}>
                {s.is_active ? 'Active' : 'Ended'}
              </span>
              {s.is_active && (
                <button className="btn btn-danger btn-sm" onClick={() => handleEnd(s.id)}>
                  End Session
                </button>
              )}
              <button
                className="btn btn-sm"
                onClick={() => navigate(`/sessions/${s.id}/memory`)}
              >
                Memory Review
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
