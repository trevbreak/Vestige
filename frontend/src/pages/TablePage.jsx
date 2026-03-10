import { useEffect, useRef, useState, useCallback } from 'react'
import { useAvatarStore } from '../stores/avatarStore'
import { useSessionStore } from '../stores/sessionStore'
import { api } from '../api/client'
import styles from './TablePage.module.css'

const MODE_ICONS = { active: '🎙', passive: '💬', absent: '💤' }

const STATUS_LABELS = {
  active: 'Listening',
  passive: 'Passive',
  absent: 'Absent',
  speaking: 'Speaking',
  thinking: 'Thinking…',
}

// Avatar status derived from real-time events
const UTTERANCE_TYPE_LABELS = {
  speech: '',
  backchannel: '💬',
  holding_phrase: '⏳',
  overlap: '[overlap]',
  inaudible: '[inaudible]',
}

export default function TablePage() {
  const { avatars, fetchAvatars } = useAvatarStore()
  const { sessions, fetchSessions } = useSessionStore()
  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [transcripts, setTranscripts] = useState([])
  const [wsStatus, setWsStatus] = useState('disconnected')
  const [pipelineRunning, setPipelineRunning] = useState(false)
  const [avatarStatuses, setAvatarStatuses] = useState({}) // {name: 'thinking'|'speaking'|null}
  const wsRef = useRef(null)
  const transcriptEndRef = useRef(null)

  useEffect(() => {
    fetchAvatars()
    fetchSessions()
  }, [fetchAvatars, fetchSessions])

  useEffect(() => {
    if (!selectedSessionId) return
    api.getTranscripts(selectedSessionId).then(setTranscripts).catch(console.error)
    // Check pipeline status
    fetch(`/api/pipeline/${selectedSessionId}/status`)
      .then((r) => r.json())
      .then((d) => setPipelineRunning(d.running))
      .catch(() => {})
  }, [selectedSessionId])

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcripts])

  // WebSocket — reconnect whenever session changes
  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws`)
    wsRef.current = ws

    ws.onopen = () => {
      setWsStatus('connected')
      ws.send(JSON.stringify({ type: 'ping' }))
    }

    ws.onmessage = (e) => {
      let msg
      try { msg = JSON.parse(e.data) } catch { return }

      if (msg.type === 'transcript' && msg.session_id === selectedSessionId) {
        const entry = msg.entry
        setTranscripts((prev) => [...prev, { ...entry, _key: Date.now() + Math.random() }])

        // Update avatar thinking/speaking status
        if (entry.speaker_type === 'avatar') {
          const status = entry.utterance_type === 'holding_phrase' ? 'thinking' : 'speaking'
          setAvatarStatuses((prev) => ({ ...prev, [entry.speaker]: status }))
          // Clear after a short delay
          setTimeout(() => {
            setAvatarStatuses((prev) => {
              const next = { ...prev }
              if (next[entry.speaker] === status) delete next[entry.speaker]
              return next
            })
          }, entry.utterance_type === 'holding_phrase' ? 8000 : 3000)
        }
      }

      if (msg.type === 'pipeline_status' && msg.session_id === selectedSessionId) {
        setPipelineRunning(msg.status === 'started')
      }
    }

    ws.onclose = () => setWsStatus('disconnected')
    ws.onerror = () => setWsStatus('error')

    return () => ws.close()
  }, [selectedSessionId])

  const togglePipeline = async () => {
    if (!selectedSessionId) return
    const action = pipelineRunning ? 'stop' : 'start'
    try {
      await fetch(`/api/pipeline/${selectedSessionId}/${action}`, { method: 'POST' })
    } catch (err) {
      console.error('Pipeline toggle failed:', err)
    }
  }

  const activeSessions = sessions.filter((s) => s.is_active)

  const sessionAvatars = selectedSessionId
    ? (() => {
        const s = sessions.find((s) => s.id === selectedSessionId)
        return s ? avatars.filter((a) => s.avatar_ids.includes(a.id)) : []
      })()
    : []

  return (
    <div className={styles.table}>
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

        {selectedSessionId && (
          <button
            className={`btn btn-sm ${pipelineRunning ? 'btn-danger' : 'btn-primary'}`}
            onClick={togglePipeline}
          >
            {pipelineRunning ? '⏹ Stop Listening' : '🎙 Start Listening'}
          </button>
        )}

        <div className={styles.avatarPanels}>
          {sessionAvatars.map((avatar) => (
            <AvatarPanel
              key={avatar.id}
              avatar={avatar}
              status={avatarStatuses[avatar.name] ?? null}
            />
          ))}
          {selectedSessionId && sessionAvatars.length === 0 && (
            <p className="text-muted" style={{ fontSize: '0.8rem' }}>
              No avatars in this session.
            </p>
          )}
        </div>

        <div className={styles.wsStatus}>
          <span className={`${styles.dot} ${styles[wsStatus]}`} />
          {wsStatus === 'connected' ? 'Live'
           : wsStatus === 'error' ? 'Error'
           : 'Disconnected'}
          {pipelineRunning && wsStatus === 'connected' && (
            <span style={{ marginLeft: '0.4rem', color: 'var(--status-active)' }}>
              • Listening
            </span>
          )}
        </div>
      </aside>

      <main className={styles.main}>
        <div className={styles.transcriptHeader}>
          <h2>Live Transcript</h2>
          {selectedSessionId && (
            <span className="text-muted" style={{ fontSize: '0.78rem' }}>
              {transcripts.filter((t) => t.utterance_type === 'speech').length} lines
            </span>
          )}
        </div>

        <div className={styles.transcript}>
          {!selectedSessionId && (
            <div className={styles.transcriptEmpty}>
              Select a session to view the transcript.
            </div>
          )}
          {selectedSessionId && transcripts.length === 0 && (
            <div className={styles.transcriptEmpty}>
              No transcript yet.{' '}
              {!pipelineRunning && 'Press "Start Listening" to begin.'}
            </div>
          )}
          {transcripts.map((t) => (
            <TranscriptLine key={t._key ?? t.id} entry={t} />
          ))}
          <div ref={transcriptEndRef} />
        </div>
      </main>
    </div>
  )
}

function AvatarPanel({ avatar, status }) {
  const isSpeaking = status === 'speaking'
  const isThinking = status === 'thinking'

  return (
    <div className={`${styles.avatarPanel} card ${isSpeaking ? 'speaking' : ''}`}>
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
          {isSpeaking ? '🗣 Speaking'
           : isThinking ? '⏳ Thinking…'
           : `${MODE_ICONS[avatar.mode]} ${STATUS_LABELS[avatar.mode]}`}
        </span>
      </div>
    </div>
  )
}

function TranscriptLine({ entry }) {
  const isAvatar = entry.speaker_type === 'avatar'
  const isDM = entry.speaker_type === 'dm'
  const isHolding = entry.utterance_type === 'holding_phrase'
  const isBackchannel = entry.utterance_type === 'backchannel'
  const isInaudible = entry.utterance_type === 'inaudible'
  const isOverlap = entry.utterance_type === 'overlap'

  // Hide noise/inaudible from main transcript
  if (isInaudible) return null

  const lineClass = [
    styles.line,
    isAvatar ? styles.lineAvatar : isDM ? styles.lineDM : '',
    isHolding ? styles.lineHolding : '',
    isBackchannel ? styles.lineBackchannel : '',
    isOverlap ? styles.lineOverlap : '',
  ].filter(Boolean).join(' ')

  const badge = UTTERANCE_TYPE_LABELS[entry.utterance_type]

  return (
    <div className={lineClass}>
      <span className={styles.lineSpeaker}>{entry.speaker}</span>
      <span className={styles.lineText}>
        {badge && <span className={styles.lineBadge}>{badge}</span>}
        {entry.text}
      </span>
    </div>
  )
}
