/**
 * Initiative Tracker — Phase 6 combat UI component.
 *
 * Displays:
 *   - Combat phase banner (active / ended)
 *   - Initiative order list with current-turn highlight
 *   - HP, conditions, death save pips per combatant
 *   - Start / End combat controls
 *   - Next Turn button (DM advances turns)
 *   - Quick damage / heal inline inputs
 */

import { useState, useCallback } from 'react'
import { api } from '../api/client'
import styles from './InitiativeTracker.module.css'

const CONDITION_ICONS = {
  blinded: '🙈',
  charmed: '💞',
  deafened: '🔇',
  frightened: '😱',
  grappled: '🤝',
  incapacitated: '💤',
  invisible: '👻',
  paralyzed: '⚡',
  petrified: '🪨',
  poisoned: '☠',
  prone: '⬇',
  restrained: '⛓',
  stunned: '💫',
  unconscious: '💀',
}

export default function InitiativeTracker({ sessionId, sessionAvatars }) {
  const [combat, setCombat] = useState(null)         // CombatState dict from API
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Setup form state
  const [setupRows, setSetupRows] = useState([])
  const [showSetup, setShowSetup] = useState(false)

  // Per-combatant quick-edit state: { [avatarId]: { dmgInput, healInput } }
  const [quickEdit, setQuickEdit] = useState({})

  // ── API helpers ─────────────────────────────────────────────────────────

  const refreshState = useCallback(async () => {
    if (!sessionId) return
    try {
      const state = await api.getCombatState(sessionId)
      setCombat(state)
    } catch {
      setCombat(null)
    }
  }, [sessionId])

  const withLoading = async (fn) => {
    setLoading(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  // ── Setup helpers ───────────────────────────────────────────────────────

  const openSetup = () => {
    const rows = sessionAvatars.map((av) => ({
      avatar_id: av.id,
      name: av.name,
      initiative: '',
      initiative_bonus: 0,
      hp_current: av.hit_points_current ?? 10,
      hp_max: av.hit_points_max ?? 10,
      is_enemy: false,
    }))
    setSetupRows(rows)
    setShowSetup(true)
  }

  const updateRow = (idx, field, value) => {
    setSetupRows((prev) => {
      const next = [...prev]
      next[idx] = { ...next[idx], [field]: value }
      return next
    })
  }

  const addEnemyRow = () => {
    setSetupRows((prev) => [
      ...prev,
      { avatar_id: 0, name: '', initiative: '', initiative_bonus: 0, hp_current: 10, hp_max: 10, is_enemy: true },
    ])
  }

  const removeRow = (idx) => {
    setSetupRows((prev) => prev.filter((_, i) => i !== idx))
  }

  const handleStart = () => withLoading(async () => {
    const combatants = setupRows.map((r) => ({
      ...r,
      initiative: parseInt(r.initiative, 10) || 0,
    }))
    const state = await api.startCombat(sessionId, combatants)
    setCombat(state)
    setShowSetup(false)
  })

  // ── Combat controls ─────────────────────────────────────────────────────

  const handleEnd = () => withLoading(async () => {
    await api.endCombat(sessionId)
    setCombat(null)
  })

  const handleNextTurn = () => withLoading(async () => {
    const result = await api.nextTurn(sessionId)
    setCombat((prev) => prev
      ? { ...prev, current_index: result.round !== prev?.round ? 0 : prev.current_index, round: result.round }
      : prev
    )
    await refreshState()
  })

  // ── Quick damage / heal ─────────────────────────────────────────────────

  const applyDamage = (avatarId) => withLoading(async () => {
    const val = parseInt(quickEdit[avatarId]?.dmgInput, 10)
    if (!val || val <= 0) return
    const result = await api.applyDamage(sessionId, avatarId, val)
    setQuickEdit((prev) => ({ ...prev, [avatarId]: { ...prev[avatarId], dmgInput: '' } }))
    updateCombatant(result)
  })

  const applyHeal = (avatarId) => withLoading(async () => {
    const val = parseInt(quickEdit[avatarId]?.healInput, 10)
    if (!val || val <= 0) return
    const result = await api.applyHeal(sessionId, avatarId, val)
    setQuickEdit((prev) => ({ ...prev, [avatarId]: { ...prev[avatarId], healInput: '' } }))
    updateCombatant(result)
  })

  const updateCombatant = (result) => {
    if (!result?.avatar_id) return
    setCombat((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        combatants: prev.combatants.map((c) =>
          c.avatar_id === result.avatar_id
            ? { ...c, hp_current: result.hp_current }
            : c
        ),
      }
    })
  }

  const setQuickField = (avatarId, field, value) => {
    setQuickEdit((prev) => ({
      ...prev,
      [avatarId]: { ...prev[avatarId], [field]: value },
    }))
  }

  // ── Render ──────────────────────────────────────────────────────────────

  const isActive = combat?.phase === 'active'

  if (showSetup) {
    return (
      <div className={styles.tracker}>
        <div className={styles.header}>
          <span className={styles.title}>Start Combat</span>
          <button className={styles.iconBtn} onClick={() => setShowSetup(false)} title="Cancel">✕</button>
        </div>

        <div className={styles.setupList}>
          {setupRows.map((row, idx) => (
            <div key={idx} className={`${styles.setupRow} ${row.is_enemy ? styles.enemy : ''}`}>
              <input
                className={styles.setupName}
                value={row.name}
                onChange={(e) => updateRow(idx, 'name', e.target.value)}
                placeholder="Name"
                disabled={!row.is_enemy}
              />
              <input
                className={styles.setupInit}
                type="number"
                value={row.initiative}
                onChange={(e) => updateRow(idx, 'initiative', e.target.value)}
                placeholder="Init"
              />
              <input
                className={styles.setupHp}
                type="number"
                value={row.hp_current}
                onChange={(e) => updateRow(idx, 'hp_current', Number(e.target.value))}
                placeholder="HP"
              />
              {row.is_enemy && (
                <button className={styles.iconBtn} onClick={() => removeRow(idx)}>✕</button>
              )}
            </div>
          ))}
          <button className={styles.addEnemyBtn} onClick={addEnemyRow}>+ Add Enemy</button>
        </div>

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.setupActions}>
          <button className="btn btn-sm btn-primary" onClick={handleStart} disabled={loading}>
            {loading ? 'Starting…' : 'Roll Initiative'}
          </button>
        </div>
      </div>
    )
  }

  if (!isActive) {
    return (
      <div className={styles.tracker}>
        <div className={styles.header}>
          <span className={styles.title}>Combat</span>
        </div>
        <div className={styles.idle}>
          {sessionId ? (
            <button className="btn btn-sm btn-primary" onClick={openSetup} disabled={!sessionId}>
              Start Combat
            </button>
          ) : (
            <span className={styles.hint}>Select a session first.</span>
          )}
        </div>
      </div>
    )
  }

  const combatants = combat.combatants ?? []
  const currentIdx = combat.current_index ?? 0

  return (
    <div className={styles.tracker}>
      <div className={styles.header}>
        <span className={styles.title}>
          Combat — Round {combat.round}
        </span>
        <button className={styles.endBtn} onClick={handleEnd} disabled={loading} title="End Combat">
          ✕ End
        </button>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.orderList}>
        {combatants.map((c, idx) => {
          const isCurrent = idx === currentIdx
          const isDead = c.hp_current <= 0 && !c.is_enemy
          const hpPct = c.hp_max > 0 ? Math.max(0, c.hp_current / c.hp_max) : 0
          const hpColor = hpPct > 0.5 ? 'var(--status-active)' : hpPct > 0.25 ? 'var(--amber)' : 'var(--crimson-light)'

          return (
            <div
              key={c.avatar_id || c.name}
              className={`${styles.combatant} ${isCurrent ? styles.current : ''} ${c.is_enemy ? styles.enemy : ''}`}
            >
              <div className={styles.combatantTop}>
                <span className={styles.initBadge}>{c.initiative}</span>
                <span className={styles.combatantName}>{c.name}</span>
                <span className={styles.hpText} style={{ color: hpColor }}>
                  {c.hp_current}/{c.hp_max}
                </span>
              </div>

              <div className={styles.hpBar}>
                <div
                  className={styles.hpFill}
                  style={{ width: `${hpPct * 100}%`, background: hpColor }}
                />
              </div>

              {c.conditions?.length > 0 && (
                <div className={styles.conditions}>
                  {c.conditions.map((cond) => (
                    <span key={cond} className={styles.conditionBadge} title={cond}>
                      {CONDITION_ICONS[cond] ?? cond}
                    </span>
                  ))}
                </div>
              )}

              {isCurrent && (
                <div className={styles.quickActions}>
                  <div className={styles.quickRow}>
                    <input
                      className={styles.quickInput}
                      type="number"
                      min="1"
                      placeholder="Dmg"
                      value={quickEdit[c.avatar_id]?.dmgInput ?? ''}
                      onChange={(e) => setQuickField(c.avatar_id, 'dmgInput', e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && applyDamage(c.avatar_id)}
                    />
                    <button
                      className={`${styles.quickBtn} ${styles.dmgBtn}`}
                      onClick={() => applyDamage(c.avatar_id)}
                      disabled={loading}
                    >
                      Dmg
                    </button>
                    <input
                      className={styles.quickInput}
                      type="number"
                      min="1"
                      placeholder="Heal"
                      value={quickEdit[c.avatar_id]?.healInput ?? ''}
                      onChange={(e) => setQuickField(c.avatar_id, 'healInput', e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && applyHeal(c.avatar_id)}
                    />
                    <button
                      className={`${styles.quickBtn} ${styles.healBtn}`}
                      onClick={() => applyHeal(c.avatar_id)}
                      disabled={loading}
                    >
                      Heal
                    </button>
                  </div>
                </div>
              )}

              {isDead && c.death_saves && (
                <DeathSaves
                  saves={c.death_saves}
                  sessionId={sessionId}
                  avatarId={c.avatar_id}
                  onResult={refreshState}
                />
              )}
            </div>
          )
        })}
      </div>

      <button
        className={`btn btn-sm btn-primary ${styles.nextTurnBtn}`}
        onClick={handleNextTurn}
        disabled={loading}
      >
        {loading ? '…' : 'Next Turn ▶'}
      </button>
    </div>
  )
}

function DeathSaves({ saves, sessionId, avatarId, onResult }) {
  const record = async (success) => {
    try {
      await api.deathSave(sessionId, avatarId, success)
      onResult()
    } catch (e) {
      console.error('Death save failed:', e)
    }
  }

  return (
    <div className={styles.deathSaves}>
      <span className={styles.dsLabel}>Death Saves</span>
      <div className={styles.dsPips}>
        <span style={{ color: 'var(--status-active)' }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <span key={i}>{i < (saves.successes ?? 0) ? '●' : '○'}</span>
          ))}
        </span>
        <span style={{ color: 'var(--crimson-light)' }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <span key={i}>{i < (saves.failures ?? 0) ? '●' : '○'}</span>
          ))}
        </span>
      </div>
      <div className={styles.dsButtons}>
        <button className={styles.dsBtnSuccess} onClick={() => record(true)}>Success</button>
        <button className={styles.dsBtnFail} onClick={() => record(false)}>Failure</button>
      </div>
    </div>
  )
}
