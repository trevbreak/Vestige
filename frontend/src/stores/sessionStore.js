import { create } from 'zustand'
import { api } from '../api/client'

export const useSessionStore = create((set) => ({
  sessions: [],
  activeSession: null,
  loading: false,
  error: null,

  fetchSessions: async () => {
    set({ loading: true, error: null })
    try {
      const sessions = await api.getSessions()
      set({ sessions, loading: false })
    } catch (e) {
      set({ error: e.message, loading: false })
    }
  },

  setActiveSession: (session) => set({ activeSession: session }),

  addSession: (session) =>
    set((s) => ({ sessions: [session, ...s.sessions] })),

  updateSession: (updated) =>
    set((s) => ({
      sessions: s.sessions.map((s) => (s.id === updated.id ? updated : s)),
      activeSession: s.activeSession?.id === updated.id ? updated : s.activeSession,
    })),
}))
