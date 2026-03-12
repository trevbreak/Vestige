const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  // Avatars
  getAvatars: (includeInactive = false) =>
    request(`/avatars/?include_inactive=${includeInactive}`),
  getAvatar: (id) => request(`/avatars/${id}`),
  createAvatar: (data) => request('/avatars/', { method: 'POST', body: data }),
  updateAvatar: (id, data) => request(`/avatars/${id}`, { method: 'PATCH', body: data }),
  deleteAvatar: (id) => request(`/avatars/${id}`, { method: 'DELETE' }),
  setAvatarMode: (id, mode) =>
    request(`/avatars/${id}/mode?mode=${mode}`, { method: 'PATCH' }),
  uploadPortrait: (id, file) => {
    const form = new FormData()
    form.append('file', file)
    return fetch(`${BASE}/avatars/${id}/portrait`, { method: 'POST', body: form }).then((r) =>
      r.json()
    )
  },

  // Sessions
  getSessions: (activeOnly = false) =>
    request(`/sessions/?active_only=${activeOnly}`),
  getSession: (id) => request(`/sessions/${id}`),
  createSession: (data) => request('/sessions/', { method: 'POST', body: data }),
  updateSession: (id, data) => request(`/sessions/${id}`, { method: 'PATCH', body: data }),
  endSession: (id) => request(`/sessions/${id}/end`, { method: 'POST' }),

  // Transcripts
  getTranscripts: (sessionId, limit = 100, offset = 0) =>
    request(`/transcripts/session/${sessionId}?limit=${limit}&offset=${offset}`),

  // Pipeline
  getPipelineStatus: (sessionId) => request(`/pipeline/${sessionId}/status`),
  startPipeline: (sessionId) => request(`/pipeline/${sessionId}/start`, { method: 'POST' }),
  stopPipeline: (sessionId) => request(`/pipeline/${sessionId}/stop`, { method: 'POST' }),

  // Memory (Phase 5)
  summariseSession: (sessionId) =>
    request(`/memory/sessions/${sessionId}/summarise`, { method: 'POST', body: {} }),
  getSessionSummary: (sessionId) =>
    request(`/memory/sessions/${sessionId}/summary`),
  approveSessionSummary: (sessionId) =>
    request(`/memory/sessions/${sessionId}/approve`, { method: 'POST' }),
  getAvatarChunks: (avatarId, includeInactive = false) =>
    request(`/memory/avatars/${avatarId}/chunks?include_inactive=${includeInactive}`),
  deleteChunk: (chunkId) =>
    request(`/memory/chunks/${chunkId}`, { method: 'DELETE' }),
  rollingSessionSummary: (sessionId, transcriptLines) =>
    request(`/memory/sessions/${sessionId}/rolling-summary`, {
      method: 'POST',
      body: { transcript_lines: transcriptLines },
    }),
  attributeSpeakers: (sessionId, attributions) =>
    request(`/sessions/${sessionId}/speakers`, { method: 'POST', body: { attributions } }),
  sheetUpdate: (avatarId, data) =>
    request(`/avatars/${avatarId}/sheet-update`, { method: 'POST', body: data }),
}
