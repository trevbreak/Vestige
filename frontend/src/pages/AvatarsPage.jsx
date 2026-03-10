import { useEffect, useState } from 'react'
import { useAvatarStore } from '../stores/avatarStore'
import AvatarCard from '../components/AvatarCard'
import AvatarForm from '../components/AvatarForm'
import styles from './AvatarsPage.module.css'

export default function AvatarsPage() {
  const { avatars, loading, error, fetchAvatars } = useAvatarStore()
  const [showForm, setShowForm] = useState(false)
  const [editTarget, setEditTarget] = useState(null)

  useEffect(() => { fetchAvatars() }, [fetchAvatars])

  const openCreate = () => { setEditTarget(null); setShowForm(true) }
  const openEdit = (avatar) => { setEditTarget(avatar); setShowForm(true) }
  const closeForm = () => { setShowForm(false); setEditTarget(null) }

  return (
    <div className={styles.page}>
      <div className={styles.pageHeader}>
        <h1>Avatars</h1>
        <button className="btn btn-primary" onClick={openCreate}>+ New Avatar</button>
      </div>

      {loading && <p className="text-muted">Loading avatars…</p>}
      {error && <p className="text-crimson">{error}</p>}

      {!loading && avatars.length === 0 && (
        <div className={styles.empty}>
          <p>No avatars yet.</p>
          <p className="text-muted">Create one to begin building your party.</p>
          <button className="btn btn-primary mt-4" onClick={openCreate}>Create First Avatar</button>
        </div>
      )}

      <div className={styles.grid}>
        {avatars.map((avatar) => (
          <AvatarCard key={avatar.id} avatar={avatar} onEdit={openEdit} />
        ))}
      </div>

      {showForm && <AvatarForm initial={editTarget} onClose={closeForm} />}
    </div>
  )
}
