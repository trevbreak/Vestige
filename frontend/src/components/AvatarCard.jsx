import { api } from '../api/client'
import { useAvatarStore } from '../stores/avatarStore'
import styles from './AvatarCard.module.css'

const MODE_ICONS = { active: '🎙', passive: '💬', absent: '💤' }
const MODE_LABELS = { active: 'Active', passive: 'Passive', absent: 'Absent' }

export default function AvatarCard({ avatar, onEdit }) {
  const { updateAvatar, removeAvatar } = useAvatarStore()

  const handleModeChange = async (e) => {
    const mode = e.target.value
    try {
      const updated = await api.setAvatarMode(avatar.id, mode)
      updateAvatar(updated)
    } catch (err) {
      alert(`Failed to set mode: ${err.message}`)
    }
  }

  const handleDelete = async () => {
    if (!confirm(`Archive ${avatar.name}? They can be restored later.`)) return
    try {
      await api.deleteAvatar(avatar.id)
      removeAvatar(avatar.id)
    } catch (err) {
      alert(`Failed to archive: ${err.message}`)
    }
  }

  const portraitUrl = avatar.portrait_path
    ? `/${avatar.portrait_path}`
    : null

  return (
    <div className={`${styles.card} card`}>
      <div className={styles.portrait}>
        {portraitUrl ? (
          <img src={portraitUrl} alt={avatar.name} />
        ) : (
          <div className={styles.portraitPlaceholder}>
            {avatar.name[0].toUpperCase()}
          </div>
        )}
      </div>

      <div className={styles.info}>
        <div className={styles.nameRow}>
          <h3 className={styles.name}>{avatar.name}</h3>
          <span className={`mode-badge mode-${avatar.mode}`}>
            {MODE_ICONS[avatar.mode]} {MODE_LABELS[avatar.mode]}
          </span>
        </div>

        <div className={styles.subtitle}>
          {avatar.race} {avatar.char_class} • Level {avatar.level}
          {avatar.alignment && <> • {avatar.alignment}</>}
        </div>

        <div className={styles.player}>Player: {avatar.player_name}</div>

        <div className={styles.stats}>
          <Stat label="HP" value={`${avatar.hit_points_current}/${avatar.hit_points_max}`} />
          <Stat label="AC" value={avatar.armor_class} />
          <Stat label="Str" value={avatar.strength} />
          <Stat label="Dex" value={avatar.dexterity} />
          <Stat label="Con" value={avatar.constitution} />
          <Stat label="Int" value={avatar.intelligence} />
          <Stat label="Wis" value={avatar.wisdom} />
          <Stat label="Cha" value={avatar.charisma} />
        </div>
      </div>

      <div className={styles.actions}>
        <select
          value={avatar.mode}
          onChange={handleModeChange}
          className={styles.modeSelect}
          aria-label="Avatar mode"
        >
          <option value="active">Active</option>
          <option value="passive">Passive</option>
          <option value="absent">Absent</option>
        </select>

        <button className="btn btn-sm" onClick={() => onEdit(avatar)}>
          Edit
        </button>
        <button className="btn btn-danger btn-sm" onClick={handleDelete}>
          Archive
        </button>
      </div>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>{value}</span>
    </div>
  )
}
