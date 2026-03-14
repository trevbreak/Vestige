import { useEffect, useRef, useState, useCallback } from 'react'
import { useAvatarStore } from '../stores/avatarStore'
import { useSessionStore } from '../stores/sessionStore'
import { useAudioPlayer } from '../hooks/useAudioPlayer'
import { useMicStream } from '../hooks/useMicStream'
import { api } from '../api/client'
import InitiativeTracker from '../components/InitiativeTracker'
import EmberParticles from '../components/EmberParticles'
import styles from './TablePage.module.css'

const MODE_ICONS = { active: '🎙', passive: '💬', absent: '💤' }

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
  const [pipelineLoading, setPipelineLoading] = useState(false)
  const [pipelineError, setPipelineError] = useState(null)
  const [avatarStatuses, setAvatarStatuses] = useState({}) // {avatarId: 'thinking'|'speaking'|null}
  const wsRef = useRef(null)
  const transcriptEndRef = useRef(null)

  // Audio playback via Web Audio API
  const { handleWsMessage: handleAudio, speaking, cancelAll, primeAudioContext } = useAudioPlayer()

  // Browser mic streaming
  const { micActive, micLoading, micError, startMic, stopMic, micLevel } = useMicStream(selectedSessionId)

  useEffect(() => {
    fetchAvatars()
    fetchSessions()
  }, [fetchAvatars, fetchSessions])

  useEffect(() => {
    if (!selectedSessionId) return
    api.getTranscripts(selectedSessionId).then(setTranscripts).catch(console.error)
    fetch(`/api/pipeline/${selectedSessionId}/status`)
      .then((r) => r.json())
      .then((d) => setPipelineRunning(d.running))
      .catch(() => {})
  }, [selectedSessionId])

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [transcripts])

  // Keep stable refs to callbacks so the WS effect doesn't reconnect on every render
  const handleAudioRef = useRef(handleAudio)
  const cancelAllRef = useRef(cancelAll)
  useEffect(() => { handleAudioRef.current = handleAudio }, [handleAudio])
  useEffect(() => { cancelAllRef.current = cancelAll }, [cancelAll])

  // WebSocket — reconnect only when session changes
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

      // ── Audio messages → audio player hook ──────────────────────────
      if (['audio_start', 'audio_chunk', 'audio_end', 'avatar_speaking'].includes(msg.type)) {
        handleAudioRef.current(msg)
      }

      // ── Transcript message ───────────────────────────────────────────
      if (msg.type === 'transcript' && msg.session_id === selectedSessionId) {
        const entry = msg.entry
        setTranscripts((prev) => [...prev, { ...entry, _key: Date.now() + Math.random() }])

        if (entry.speaker_type === 'avatar') {
          const status = entry.utterance_type === 'holding_phrase' ? 'thinking' : 'speaking'
          setAvatarStatuses((prev) => ({ ...prev, [entry.speaker]: status }))
          setTimeout(() => {
            setAvatarStatuses((prev) => {
              const next = { ...prev }
              if (next[entry.speaker] === status) delete next[entry.speaker]
              return next
            })
          }, entry.utterance_type === 'holding_phrase' ? 8000 : 4000)
        }
      }

      // ── Avatar speaking (from audio output manager) ──────────────────
      if (msg.type === 'avatar_speaking' && msg.session_id === selectedSessionId) {
        const key = msg.avatar_name
        if (msg.speaking) {
          setAvatarStatuses((prev) => ({ ...prev, [key]: 'speaking' }))
        } else {
          setAvatarStatuses((prev) => {
            const next = { ...prev }
            if (next[key] === 'speaking') delete next[key]
            return next
          })
        }
      }

      // ── Pipeline status ──────────────────────────────────────────────
      if (msg.type === 'pipeline_status' && msg.session_id === selectedSessionId) {
        setPipelineRunning(msg.status === 'started')
        if (msg.status === 'stopped') cancelAllRef.current()
      }
    }

    ws.onclose = () => setWsStatus('disconnected')
    ws.onerror = () => setWsStatus('error')

    return () => {
      if (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN) {
        ws.close()
      }
    }
  }, [selectedSessionId])

  const togglePipeline = async () => {
    if (!selectedSessionId) return
    setPipelineError(null)
    if (pipelineRunning) {
      try { await api.stopPipeline(selectedSessionId) } catch {}
      setPipelineRunning(false)
      stopMic()
    } else {
      setPipelineLoading(true)
      // Unlock AudioContext synchronously in this user-gesture handler
      await primeAudioContext()
      try {
        await api.startPipeline(selectedSessionId)
        setPipelineRunning(true)
      } catch (err) {
        setPipelineError(err.message)
        setPipelineLoading(false)
        return
      }
      try {
        await startMic()
      } catch (err) {
        setPipelineError(`Mic error: ${err.message}`)
        await api.stopPipeline(selectedSessionId).catch(() => {})
        setPipelineRunning(false)
      }
      setPipelineLoading(false)
    }
  }

  const activeSessions = sessions.filter((s) => s.is_active)

  const sessionAvatars = selectedSessionId
    ? (() => {
        const s = sessions.find((s) => s.id === selectedSessionId)
        return s ? avatars.filter((a) => s.avatar_ids.includes(a.id)) : []
      })()
    : []

  // Merge audio player "speaking" state with WS-driven statuses
  const getAvatarStatus = (avatar) => {
    if (speaking?.avatarId === avatar.id) return 'speaking'
    return avatarStatuses[avatar.name] ?? null
  }

  return (
    <div className={styles.table}>
      <EmberParticles />
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            <button
              className={`btn btn-sm ${pipelineRunning ? 'btn-danger' : 'btn-primary'}`}
              onClick={togglePipeline}
              disabled={pipelineLoading}
            >
              {pipelineLoading
                ? <><span className={styles.spinnerDot} /> Loading…</>
                : pipelineRunning ? '⏹ Stop Listening' : '🎙 Start Listening'}
            </button>
            {micActive && (
              <div className={styles.micLevelRow}>
                <span className={styles.micDot} />
                <div className={styles.micLevelBar}>
                  <div
                    className={styles.micLevelFill}
                    style={{ width: `${Math.min(100, micLevel * 400)}%` }}
                  />
                </div>
              </div>
            )}
            {pipelineError && (
              <span style={{ fontSize: '0.75rem', color: 'var(--crimson-light)' }}>
                Pipeline: {pipelineError}
              </span>
            )}
            {micError && (
              <span style={{ fontSize: '0.75rem', color: 'var(--crimson-light)' }}>
                Mic: {micError}
              </span>
            )}
          </div>
        )}

        <div className={styles.avatarPanels}>
          {sessionAvatars.map((avatar) => (
            <AvatarPanel
              key={avatar.id}
              avatar={avatar}
              status={getAvatarStatus(avatar)}
            />
          ))}
          {selectedSessionId && sessionAvatars.length === 0 && (
            <p className="text-muted" style={{ fontSize: '0.8rem' }}>
              No avatars in this session.
            </p>
          )}
        </div>

        <InitiativeTracker
          sessionId={selectedSessionId}
          sessionAvatars={sessionAvatars}
        />

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
      <div className={`${styles.apPortrait} ${isSpeaking ? styles.apPortraitSpeaking : ''}`}>
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
           : `${MODE_ICONS[avatar.mode]} ${avatar.mode === 'active' ? 'Listening' : avatar.mode === 'passive' ? 'Passive' : 'Absent'}`}
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
  const isOverlap = entry.utterance_type === 'overlap'

  if (entry.utterance_type === 'inaudible') return null

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
