import { Routes, Route, NavLink } from 'react-router-dom'
import AvatarsPage from './pages/AvatarsPage'
import SessionsPage from './pages/SessionsPage'
import TablePage from './pages/TablePage'
import MemoryReviewPage from './pages/MemoryReviewPage'
import SettingsPage from './pages/SettingsPage'
import styles from './App.module.css'

export default function App() {
  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <span className={styles.logo}>⚔ Vestige</span>
        <nav className={styles.nav}>
          <NavLink to="/" end className={({ isActive }) => isActive ? styles.active : ''}>
            Avatars
          </NavLink>
          <NavLink to="/sessions" className={({ isActive }) => isActive ? styles.active : ''}>
            Sessions
          </NavLink>
          <NavLink to="/table" className={({ isActive }) => isActive ? styles.active : ''}>
            Table
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => isActive ? styles.active : ''}>
            Settings
          </NavLink>
        </nav>
      </header>

      <main className={styles.main}>
        <Routes>
          <Route path="/" element={<AvatarsPage />} />
          <Route path="/sessions" element={<SessionsPage />} />
          <Route path="/table" element={<TablePage />} />
          <Route path="/sessions/:sessionId/memory" element={<MemoryReviewPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}
