import { create } from 'zustand'
import { api } from '../api/client'

export const useAvatarStore = create((set, get) => ({
  avatars: [],
  loading: false,
  error: null,

  fetchAvatars: async () => {
    set({ loading: true, error: null })
    try {
      const avatars = await api.getAvatars()
      set({ avatars, loading: false })
    } catch (e) {
      set({ error: e.message, loading: false })
    }
  },

  addAvatar: (avatar) =>
    set((s) => ({ avatars: [...s.avatars, avatar] })),

  updateAvatar: (updated) =>
    set((s) => ({
      avatars: s.avatars.map((a) => (a.id === updated.id ? updated : a)),
    })),

  removeAvatar: (id) =>
    set((s) => ({ avatars: s.avatars.filter((a) => a.id !== id) })),
}))
