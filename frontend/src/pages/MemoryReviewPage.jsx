import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import styles from './MemoryReviewPage.module.css'

export default function MemoryReviewPage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()

  const [session, setSession] = useState(null)
  const [summary, setSummary] = useState(null)
  const [chunks, setChunks] = useState([])
  const [selectedAvatarId, setSelectedAvatarId] = useState(null)

  const [summarising, setSummarising] = useState(false)
  const [approving, setApproving] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Speaker attribution state
  const [speakers, setSpeakers] = useState({})   // {"Unknown": "Alice"}
  const [attributing, setAttributing] = useState(false)

  useEffect(() => {
    if (!sessionId) return
    api.getSession(sessionId).then(setSession).catch(() => {})
    api.getSessionSummary(sessionId).then(setSummary).catch(() => {})
  }, [sessionId])

  useEffect(() => {
    if (!selectedAvatarId) return
    api.getAvatarChunks(selectedAvatarId).then(setChunks).catch(() => setChunks([]))
  }, [selectedAvatarId])

  const handleSummarise = async () => {
    setError('')
    setSuccess('')
    setSummarising(true)
    try {
      const result = await api.summariseSession(sessionId)
      setSuccess(
        `Summary generated — ${result.event_count} events, ${result.npc_count} NPCs, ` +
        `${result.item_count} items, ${result.relationship_count} relationship deltas.`
      )
      const updated = await api.getSessionSummary(sessionId)
      setSummary(updated)
    } catch (e) {
      setError(e.message)
    } finally {
      setSummarising(false)
    }
  }

  const handleApprove = async () => {
    setError('')
    setSuccess('')
    setApproving(true)
    try {
      const result = await api.approveSessionSummary(sessionId)
      setSuccess(`Approved — ${result.chunks_created} memory chunks stored.`)
      const updated = await api.getSessionSummary(sessionId)
      setSummary(updated)
    } catch (e) {
      setError(e.message)
    } finally {
      setApproving(false)
    }
  }

  const handleDeleteChunk = async (chunkId) => {
    try {
      await api.deleteChunk(chunkId)
      setChunks((prev) => prev.filter((c) => c.id !== chunkId))
    } catch (e) {
      setError(e.message)
    }
  }

  const handleAttributeSpeakers = async () => {
    const filtered = Object.fromEntries(
      Object.entries(speakers).filter(([k, v]) => k.trim() && v.trim())
    )
    if (!Object.keys(filtered).length) return
    setAttributing(true)
    setError('')
    try {
      const result = await api.attributeSpeakers(sessionId, filtered)
      setSuccess(`Speaker attribution applied — ${result.updated_count} entries updated.`)
    } catch (e) {
      setError(e.message)
    } finally {
      setAttributing(false)
    }
  }

  const summaryJson = summary?.summary_json || {}
  const events = summaryJson.events || []
  const npcs = summaryJson.npcs || []
  const items = summaryJson.items || []
  const relationships = summaryJson.relationship_deltas || []
  const avatarUpdates = summaryJson.avatar_updates || []
  const avatarIds = session?.avatar_ids || []

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1>Memory Review</h1>
        <div className={styles.headerActions}>
          <span className={styles.sessionName}>{session?.name || `Session ${sessionId}`}</span>
          <button className={styles.btnSecondary} onClick={() => navigate(-1)}>Back</button>
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {success && <div className={styles.success}>{success}</div>}

      {/* Summary generation */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2>Session Summary</h2>
          <div className={styles.sectionActions}>
            <button
              className={styles.btn}
              onClick={handleSummarise}
              disabled={summarising}
            >
              {summarising ? 'Generating…' : summary ? 'Re-generate' : 'Generate Summary'}
            </button>
            {summary && !summary.is_approved && (
              <button
                className={styles.btnApprove}
                onClick={handleApprove}
                disabled={approving}
              >
                {approving ? 'Committing…' : 'Approve & Commit to Memory'}
              </button>
            )}
            {summary?.is_approved && (
              <span className={styles.approved}>✓ Approved</span>
            )}
          </div>
        </div>

        {summary ? (
          <div className={styles.summaryBody}>
            <p className={styles.summaryText}>{summary.summary_text || '(no prose summary)'}</p>

            {events.length > 0 && (
              <div className={styles.summaryGroup}>
                <h3>Events ({events.length})</h3>
                <ul>
                  {events.map((ev, i) => <li key={i}>{ev}</li>)}
                </ul>
              </div>
            )}

            {npcs.length > 0 && (
              <div className={styles.summaryGroup}>
                <h3>NPCs ({npcs.length})</h3>
                <ul>
                  {npcs.map((npc, i) => (
                    <li key={i}><strong>{npc.name}</strong>: {npc.notes}</li>
                  ))}
                </ul>
              </div>
            )}

            {items.length > 0 && (
              <div className={styles.summaryGroup}>
                <h3>Items ({items.length})</h3>
                <ul>
                  {items.map((item, i) => (
                    <li key={i}><strong>{item.name}</strong> ({item.owner}): {item.notes}</li>
                  ))}
                </ul>
              </div>
            )}

            {relationships.length > 0 && (
              <div className={styles.summaryGroup}>
                <h3>Relationship Deltas ({relationships.length})</h3>
                <ul>
                  {relationships.map((r, i) => (
                    <li key={i}>{r.avatar} → {r.target}: {r.note}</li>
                  ))}
                </ul>
              </div>
            )}

            {avatarUpdates.length > 0 && (
              <div className={styles.summaryGroup}>
                <h3>Avatar Updates</h3>
                {avatarUpdates.map((upd, i) => (
                  <div key={i} className={styles.avatarUpdate}>
                    <strong>{upd.avatar_name}</strong>
                    {upd.hp_delta !== 0 && <span> HP {upd.hp_delta > 0 ? '+' : ''}{upd.hp_delta}</span>}
                    {upd.xp_gained > 0 && <span> +{upd.xp_gained} XP</span>}
                    {upd.notes && <p>{upd.notes}</p>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className={styles.empty}>No summary yet. Click Generate Summary to create one.</p>
        )}
      </section>

      {/* Speaker attribution */}
      <section className={styles.section}>
        <h2>Speaker Attribution</h2>
        <p className={styles.hint}>
          Map auto-detected speaker labels ("Unknown", "Speaker 0") to player names.
        </p>
        <div className={styles.attributionGrid}>
          {['Unknown', 'Speaker 0', 'Speaker 1', 'Speaker 2', 'Speaker 3'].map((label) => (
            <div key={label} className={styles.attributionRow}>
              <span className={styles.speakerLabel}>{label}</span>
              <span className={styles.arrow}>→</span>
              <input
                type="text"
                placeholder="Player name or DM"
                value={speakers[label] || ''}
                onChange={(e) => setSpeakers((prev) => ({ ...prev, [label]: e.target.value }))}
                className={styles.input}
              />
            </div>
          ))}
        </div>
        <button
          className={styles.btn}
          onClick={handleAttributeSpeakers}
          disabled={attributing}
        >
          {attributing ? 'Applying…' : 'Apply Attribution'}
        </button>
      </section>

      {/* Memory chunks viewer */}
      {avatarIds.length > 0 && (
        <section className={styles.section}>
          <h2>Memory Chunks</h2>
          <div className={styles.avatarTabs}>
            {avatarIds.map((aid) => (
              <button
                key={aid}
                className={selectedAvatarId === aid ? styles.tabActive : styles.tab}
                onClick={() => setSelectedAvatarId(aid)}
              >
                Avatar {aid}
              </button>
            ))}
          </div>

          {selectedAvatarId && (
            chunks.length === 0 ? (
              <p className={styles.empty}>No memory chunks for this avatar yet.</p>
            ) : (
              <div className={styles.chunkList}>
                {chunks.map((chunk) => (
                  <div key={chunk.id} className={styles.chunk}>
                    <div className={styles.chunkMeta}>
                      <span className={styles.chunkType}>{chunk.chunk_type}</span>
                      <span className={styles.chunkImportance}>
                        {(chunk.importance * 100).toFixed(0)}% importance
                      </span>
                    </div>
                    <p className={styles.chunkText}>{chunk.text}</p>
                    <button
                      className={styles.btnDelete}
                      onClick={() => handleDeleteChunk(chunk.id)}
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )
          )}
        </section>
      )}
    </div>
  )
}
