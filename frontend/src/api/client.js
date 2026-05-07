import axios from 'axios'

const API_BASE = '/api'

const TOKEN_KEY = 'access_token'

export const http = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }

    const detail = error?.response?.data?.detail
    const message = typeof detail === 'string' ? detail : error?.message || 'Request failed'
    return Promise.reject(new Error(message))
  },
)

function getDevStreamCandidates() {
  const portsStr = (import.meta.env.VITE_STREAM_PORTS || '8000').trim()
  const ports = portsStr.split(',').map(p => p.trim()).filter(Boolean)
  if (typeof window === 'undefined') {
    return ports.map(p => `http://127.0.0.1:${p}/api`)
  }
  const host = window.location.hostname || '127.0.0.1'
  return ports.map(p => `http://${host}:${p}/api`)
}

function getStreamBase(attempt = 0) {
  const explicit = (import.meta.env.VITE_STREAM_BASE || '').trim()
  if (explicit) return explicit.replace(/\/$/, '')

  // Production: stream from same API origin.
  if (!import.meta.env.DEV) return API_BASE

  // Dev: rotate between common backend ports to avoid hardcoding.
  const candidates = getDevStreamCandidates()
  const idx = Math.abs(Number(attempt) || 0) % candidates.length
  return candidates[idx]
}

async function req(method, path, body, { raw = false, responseType } = {}) {
  const response = await http.request({
    method,
    url: path,
    data: body,
    responseType,
  })
  if (raw) return response
  return response.data
}

export const api = {
  // ── Auth flow (/users/*) ─────────────────────────────────────────────
  register: ({ email, password, phone_number = '' }) =>
    req('POST', '/users/register', { email, password, phone_number }),
  login: ({ email, password }) =>
    req('POST', '/users/login', { email, password }),
  forgotPassword: (email) =>
    req('POST', '/users/forgot-password', { email }),
  resetPasswordWithToken: ({ token, new_password }) =>
    req('POST', '/users/reset-password', { token, new_password }),
  me: () => req('GET', '/users/me'),

  // ── Users (admin) ─────────────────────────────────────────────────────
  getUsers: () => req('GET', '/users/'),
  createUser: (body) => req('POST', '/users/', body),
  updateUser: (id, body) => req('PATCH', `/users/${id}`, body),
  deactivateUser: (id) => req('DELETE', `/users/${id}`),
  resetPassword: (id, new_password) =>
    req('POST', `/users/${id}/reset-password`, { new_password }),

  // ── Cameras ───────────────────────────────────────────────────────────
  getCameras:   () => req('GET', '/cameras/'),
  getCameraMetrics: () => req('GET', '/cameras/metrics'),
  addCamera:    (body) => req('POST', '/cameras/', body),
  updateCamera: (id, body) => req('PUT', `/cameras/${id}`, body),
  deleteCamera: (id) => req('DELETE', `/cameras/${id}`),
  startAll:     () => req('POST', '/cameras/start'),
  stopAll:      () => req('POST', '/cameras/stop'),
  startCamera:  (id) => req('POST', `/cameras/${id}/start`),
  stopCamera:   (id) => req('POST', `/cameras/${id}/stop`),
  streamUrl:    (camId, nonce = 0, attempt = 0) => {
    const streamBase = getStreamBase(attempt)
    return `${streamBase}/stream/${camId}?_=${encodeURIComponent(String(nonce))}`
  },

  // ── Config ────────────────────────────────────────────────────────────
  getConfig:    () => req('GET', '/config/'),
  updateConfig: (data) => req('PATCH', '/config/', data),

  // ── Buzzers ───────────────────────────────────────────────────────────
  getBuzzers:    () => req('GET', '/buzzers/'),
  createBuzzer:  (body) => req('POST', '/buzzers/', body),
  updateBuzzer:  (id, body) => req('PUT', `/buzzers/${id}`, body),
  deleteBuzzer:  (id) => req('DELETE', `/buzzers/${id}`),
  toggleBuzzer:  (id) => req('PATCH', `/buzzers/${id}/toggle`),

  // ── Camera ↔ Buzzer assignments ───────────────────────────────────────
  getCameraBuzzers: (camId) => req('GET', `/camera-buzzers/${camId}`),
  setCameraBuzzers: (camId, buzzer_ids) =>
    req('PUT', `/camera-buzzers/${camId}`, { buzzer_ids }),

  // ── Camera models ─────────────────────────────────────────────────────
  getCameraModels:   (camId) => req('GET', `/camera-models/${camId}`),
  upsertCameraModel: (camId, model_name, is_enabled) =>
    req('POST', `/camera-models/${camId}`, { model_name, is_enabled }),
  toggleCameraModel: (camId, model_name) =>
    req('PATCH', `/camera-models/${camId}/${model_name}`),

  // ── Alerts / Reports ──────────────────────────────────────────────────
  getAlerts: (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
    ).toString()
    return req('GET', `/alerts/${qs ? '?' + qs : ''}`)
  },
  getAlertSummary:  () => req('GET', '/alerts/summary'),
  acknowledgeAlert: (id) => req('PATCH', `/alerts/${id}/acknowledge`),
  exportAlertsCsv:  (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
    ).toString()
    return req('GET', `/alerts/export${qs ? '?' + qs : ''}`, null, { raw: true, responseType: 'blob' })
  },
  exportDailyReportPdf: (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
    ).toString()
    return req('GET', `/alerts/daily-report.pdf${qs ? '?' + qs : ''}`, null, { raw: true, responseType: 'blob' })
  },
  exportDailyReportExcel: (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
    ).toString()
    return req('GET', `/alerts/daily-report.xlsx${qs ? '?' + qs : ''}`, null, { raw: true, responseType: 'blob' })
  },
  sendDailyReportWhatsApp: (body = {}) => req('POST', '/alerts/daily-report/whatsapp', body),

  // ── ROI Zones ─────────────────────────────────────────────────────────
  getRois:         (camId, activeOnly = false) =>
    req('GET', `/rois/camera/${encodeURIComponent(camId)}?active_only=${activeOnly}`),
  createRoi:       (camId, body)  => req('POST',   `/rois/camera/${encodeURIComponent(camId)}`, body),
  updateRoi:       (roiId, body)  => req('PUT',    `/rois/${roiId}`, body),
  deleteRoi:       (roiId)        => req('DELETE',  `/rois/${roiId}`),
  toggleRoi:       (roiId)        => req('PATCH',   `/rois/${roiId}/toggle`),
  bulkReplaceRois: (camId, rois)  => req('PUT',    `/rois/camera/${encodeURIComponent(camId)}/bulk`, { rois }),

  // ── Alarm (legacy) ────────────────────────────────────────────────────
  testAlarm:      () => req('POST', '/alarm/test'),
  getAlarmStatus: () => req('GET', '/alarm/status'),


    // ── Burglar Alarm ─────────────────────────────────────────────────────
  getBurglarAlarmConfigs:  ()           => req('GET',    '/burglar-alarm/'),
  getBurglarAlarmConfig:   (camId)      => req('GET',    `/burglar-alarm/${camId}`),
  upsertBurglarAlarmConfig:(camId, body)=> req('PUT',    `/burglar-alarm/${camId}`, body),
  deleteBurglarAlarmConfig:(camId)      => req('DELETE', `/burglar-alarm/${camId}`),
  getBurglarAlarmStatus:   (camId)      => req('GET',    `/burglar-alarm/${camId}/status`),


  // ── Logs ──────────────────────────────────────────────────────────────
  getLogs:   (lines = 100) => req('GET', `/logs/?lines=${lines}`),
  clearLogs: () => req('DELETE', '/logs/'),
}
