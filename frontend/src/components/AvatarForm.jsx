import { useState } from 'react'
import { api } from '../api/client'
import { useAvatarStore } from '../stores/avatarStore'
import styles from './AvatarForm.module.css'

const DEFAULTS = {
  name: '', player_name: '',
  race: 'Human', char_class: 'Fighter', level: 1,
  background: '', alignment: 'True Neutral',
  strength: 10, dexterity: 10, constitution: 10,
  intelligence: 10, wisdom: 10, charisma: 10,
  hit_points_max: 10, hit_points_current: 10,
  armor_class: 10, speed: 30, proficiency_bonus: 2,
  backstory: '', personality_traits: '', ideals: '', bonds: '', flaws: '',
  sentence_style: '', verbal_tics: '', never_say: '',
  mode: 'active',
}

export default function AvatarForm({ initial, onClose }) {
  const { addAvatar, updateAvatar } = useAvatarStore()
  const [form, setForm] = useState({ ...DEFAULTS, ...initial })
  const [saving, setSaving] = useState(false)
  const [rolling, setRolling] = useState(false)
  const [error, setError] = useState(null)
  const [portrait, setPortrait] = useState(null)

  const isEdit = !!initial?.id

  const set = (field) => (e) =>
    setForm((f) => ({ ...f, [field]: e.target.type === 'number' ? Number(e.target.value) : e.target.value }))

  const handleRandomise = async () => {
    setRolling(true)
    setError(null)
    try {
      const data = await api.randomiseAvatar()
      setForm((f) => ({ ...f, ...data }))
    } catch (err) {
      setError(`Randomise failed: ${err.message}`)
    } finally {
      setRolling(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      let avatar
      if (isEdit) {
        avatar = await api.updateAvatar(initial.id, form)
        updateAvatar(avatar)
      } else {
        avatar = await api.createAvatar(form)
        addAvatar(avatar)
      }
      if (portrait) {
        const withPortrait = await api.uploadPortrait(avatar.id, portrait)
        isEdit ? updateAvatar(withPortrait) : updateAvatar(withPortrait)
      }
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <form className={styles.form} onSubmit={handleSubmit}>
        <div className={styles.formHeader}>
          <h2>{isEdit ? `Edit ${initial.name}` : 'New Avatar'}</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {!isEdit && (
              <button
                type="button"
                className={`btn ${styles.randomiseBtn}${rolling ? ` ${styles.rolling}` : ''}`}
                onClick={handleRandomise}
                disabled={rolling}
                title="Let Ollama roll a random valid D&D 5e character"
              >
                <span className={styles.diceIcon}>⚄</span>{' '}
                {rolling ? 'Rolling…' : 'Randomise'}
              </button>
            )}
            <button type="button" className={styles.closeBtn} onClick={onClose}>✕</button>
          </div>
        </div>

        <div className={styles.scrollBody}>
          <Section title="Identity">
            <Row>
              <Field label="Character Name *">
                <input required value={form.name} onChange={set('name')} placeholder="Aelindra Shadowmantle" />
              </Field>
              <Field label="Player Name *">
                <input required value={form.player_name} onChange={set('player_name')} placeholder="Sarah" />
              </Field>
            </Row>
            <Row>
              <Field label="Race">
                <input value={form.race} onChange={set('race')} placeholder="Human" />
              </Field>
              <Field label="Class">
                <input value={form.char_class} onChange={set('char_class')} placeholder="Fighter" />
              </Field>
              <Field label="Level">
                <input type="number" min={1} max={20} value={form.level} onChange={set('level')} />
              </Field>
            </Row>
            <Row>
              <Field label="Background">
                <input value={form.background} onChange={set('background')} placeholder="Soldier" />
              </Field>
              <Field label="Alignment">
                <select value={form.alignment} onChange={set('alignment')}>
                  {['Lawful Good','Neutral Good','Chaotic Good',
                    'Lawful Neutral','True Neutral','Chaotic Neutral',
                    'Lawful Evil','Neutral Evil','Chaotic Evil'].map(a =>
                    <option key={a}>{a}</option>
                  )}
                </select>
              </Field>
              <Field label="Mode">
                <select value={form.mode} onChange={set('mode')}>
                  <option value="active">Active</option>
                  <option value="passive">Passive</option>
                  <option value="absent">Absent</option>
                </select>
              </Field>
            </Row>
          </Section>

          <Section title="Ability Scores">
            <Row>
              {['strength','dexterity','constitution','intelligence','wisdom','charisma'].map(stat => (
                <Field key={stat} label={stat.slice(0,3).toUpperCase()}>
                  <input type="number" min={1} max={30} value={form[stat]} onChange={set(stat)} />
                </Field>
              ))}
            </Row>
          </Section>

          <Section title="Combat Stats">
            <Row>
              <Field label="Max HP">
                <input type="number" min={1} value={form.hit_points_max} onChange={set('hit_points_max')} />
              </Field>
              <Field label="Current HP">
                <input type="number" min={0} value={form.hit_points_current} onChange={set('hit_points_current')} />
              </Field>
              <Field label="AC">
                <input type="number" min={1} value={form.armor_class} onChange={set('armor_class')} />
              </Field>
              <Field label="Speed">
                <input type="number" min={0} value={form.speed} onChange={set('speed')} />
              </Field>
              <Field label="Prof. Bonus">
                <input type="number" min={2} max={6} value={form.proficiency_bonus} onChange={set('proficiency_bonus')} />
              </Field>
            </Row>
          </Section>

          <Section title="Personality">
            <Field label="Backstory">
              <textarea value={form.backstory} onChange={set('backstory')} placeholder="Once a guard captain in the city of Neverwinter..." />
            </Field>
            <Row>
              <Field label="Traits">
                <textarea value={form.personality_traits} onChange={set('personality_traits')} placeholder="I face problems head-on." />
              </Field>
              <Field label="Ideals">
                <textarea value={form.ideals} onChange={set('ideals')} placeholder="Greater Good." />
              </Field>
            </Row>
            <Row>
              <Field label="Bonds">
                <textarea value={form.bonds} onChange={set('bonds')} placeholder="I would die to recover the sword I lost." />
              </Field>
              <Field label="Flaws">
                <textarea value={form.flaws} onChange={set('flaws')} placeholder="I made a terrible mistake in battle." />
              </Field>
            </Row>
          </Section>

          <Section title="Voice & AI Style">
            <Field label="Sentence Style">
              <input value={form.sentence_style} onChange={set('sentence_style')} placeholder='e.g. "short declarative bursts, rarely asks questions"' />
            </Field>
            <Field label="Verbal Tics">
              <input value={form.verbal_tics} onChange={set('verbal_tics')} placeholder='e.g. "often invokes Tempus, uses military jargon"' />
            </Field>
            <Field label="Never Say (one per line)">
              <textarea value={form.never_say} onChange={set('never_say')} placeholder={'certainly\nindeed\nas an AI'} />
            </Field>
          </Section>

          <Section title="Portrait">
            <Field label="Upload portrait image (JPEG/PNG/WebP)">
              <input type="file" accept="image/jpeg,image/png,image/webp"
                onChange={(e) => setPortrait(e.target.files[0])} style={{ padding: 0, border: 'none' }} />
            </Field>
          </Section>
        </div>

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.footer}>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Create Avatar'}
          </button>
        </div>
      </form>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: '1.2rem' }}>
      <div style={{ fontFamily: 'var(--font-heading)', fontSize: '0.85rem', color: 'var(--gold-dim)',
        textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '0.6rem',
        borderBottom: '1px solid var(--border)', paddingBottom: '0.3rem' }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function Row({ children }) {
  return <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(140px, 1fr))`, gap: '0.6rem', marginBottom: '0.6rem' }}>{children}</div>
}

function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
      <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</label>
      {children}
    </div>
  )
}
