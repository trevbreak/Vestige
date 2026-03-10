import { useEffect, useRef, useState } from 'react'
import { useAvatarStore } from '../stores/avatarStore'
import { useSessionStore } from '../stores/sessionStore'
import { api } from '../api/client'
import styles from './TablePage.module.css'

const MODE_ICONS = { active: '🎙', passive: '💬', absent: '💤' }
const STATUS_LABELS = {
  active: 'Listening',
  passive: 'Passive',
  absent: 'Absent',
}

export default function TablePage() {
  const { avatars, fetchAvatars } = useAvatarStore()
  const { sessions, fetchSessions } = useSessionStore()
  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [transcripts, setTranscripts] = useState([])
  const [wsStatus, setWsStatus] = useState('disconnected')
  const wsRef = useRef(null)
  const transcriptEndRef = useRef(null)

  useEffect(() => {
    fetchAvatars()
    fetchSessions()
  }, [fetchAvatars, fetchSessions])

  useEffect(() => {
    if (!selectedSessionId) return
    api.getTranscripts(selectedSessionId).then(setTranscripts).catch(console.error)
  }, [selectedSessionId])

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcripts])

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws`)
    wsRef.current = ws

    ws.onopen = () => {
      setWsStatus('connected')
      ws.send(JSON.stringify({ type: 'ping' }))
    }
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'transcript' && msg.session_id === selectedSessionId) {
        setTranscripts((t) => [...t, msg.entry])
      }
    }
    ws.onclose = () => setWsStatus('disconnected')
    ws.onerror = () => setWsStatus('error')

    return () => ws.close()
  }, [selectedSessionId])

  const activeSessions = sessions.filter((s) => s.is_active)

  const sessionAvatars = selectedSessionId
    ? (() => {
        const s = sessions.find((s) => s.id === selectedSessionId)
        return s ? avatars.filter((a) => s.avatar_ids.includes(a.id)) : []
      })()
    : []

  return (
    <div className={styles.table}>
      {/* Sidebar: session picker + avatar panels */}
      <aside className={styles.sidebar}>
        <div className={styles.sideSection}>
          <label className={styles.sideLabel}>Session</label>
          <select
            value={selectedSessionId ?? ''}
            onChange={(e) => setSelectedSessionId(Number(e.target.value) || null)}
          >
            <option value="">— Select a session —</option>
            {activeSessions.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>

        <div className={styles.avatarPanels}>
          {sessionAvatars.map((avatar) => (
            <AvatarPanel key={avatar.id} avatar={avatar} />
          ))}
          {selectedSessionId && sessionAvatars.length === 0 && (
            <p className="text-muted" style={{ fontSize: '0.8rem' }}>No avatars in this session.</p>
          )}
        </div>

        <div className={styles.wsStatus}>
          <span className={`${styles.dot} ${styles[wsStatus]}`} />
          {wsStatus === 'connected' ? 'Live' : wsStatus === 'error' ? 'Error' : 'Disconnected'}
        </div>
      </aside>

      {/* Main: live transcript */}
      <main className={styles.main}>
        <div className={styles.transcriptHeader}>
          <h2>Live Transcript</h2>
          {selectedSessionId && (
            <span className="text-muted" style={{ fontSize: '0.78rem' }}>
              {transcripts.length} lines
            </span>
          )}
        </div>

        <div className={styles.transcript}>
          {!selectedSessionId && (
            <div className={styles.transcriptEmpty}>Select a session to view the transcript.</div>
          )}
          {selectedSessionId && transcripts.length === 0 && (
            <div className={styles.transcriptEmpty}>No transcript yet. Waiting for audio…</div>
          )}
          {transcripts.map((t) => (
            <TranscriptLine key={t.id} entry={t} />
          ))}
          <div ref={transcriptEndRef} />
        </div>
      </main>
    </div>
  )
}

function AvatarPanel({ avatar }) {
  return (
    <div className={`${styles.avatarPanel} card`}>
      <div className={styles.apPortrait}>
        {avatar.portrait_path ? (
          <img src={`/${avatar.portrait_path}`} alt={avatar.name} />
        ) : (
          <span>{avatar.name[0]}</span>
        )}
      </div>
      <div className={styles.apInfo}>
        <div className={styles.apName}>{avatar.name}</div>
        <div className={styles.apSub}>{avatar.race} {avatar.char_class}</div>
        <div className={styles.apStats}>
          <span>HP {avatar.hit_points_current}/{avatar.hit_points_max}</span>
          <span>AC {avatar.armor_class}</span>
        </div>
        <span className={`mode-badge mode-${avatar.mode}`}>
          {MODE_ICONS[avatar.mode]} {STATUS_LABELS[avatar.mode]}
        </span>
      </div>
    </div>
  )
}

function TranscriptLine({ entry }) {
  const isAvatar = entry.speaker_type === 'avatar'
  const isDM = entry.speaker_type === 'dm'
  return (
    <div className={`${styles.line} ${isAvatar ? styles.lineAvatar : isDM ? styles.lineDM : ''}`}>
      <span className={styles.lineSpeaker}>{entry.speaker}</span>
      <span className={styles.lineText}>{entry.text}</span>
    </div>
  )
}
