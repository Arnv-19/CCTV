/**
 * EmployeesPanel.jsx
 * ------------------
 * Admin panel for managing employee face-recognition enrollment.
 *
 * Features
 * --------
 *  - List all employees with enrollment status + photo thumbnail
 *  - Create new employee record (name, department, employee ID)
 *  - Upload / re-enroll a face photo for a single employee
 *  - Bulk import via CSV + ZIP
 *  - Delete employee (with confirmation)
 *  - View enrolled photo in a full-screen lightbox
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  UserPlus, Upload, Trash2, CheckCircle2, XCircle,
  Eye, Users, FileArchive, RefreshCw, ChevronDown, ChevronUp, X,
  Camera as CameraIcon, AlertCircle, Download
} from 'lucide-react'
import { api } from '../api/client'

// ─── Shared style tokens ──────────────────────────────────────────────────────
const inputCls =
  'w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2 text-sm ' +
  'text-zinc-100 placeholder-zinc-500 focus:outline-none focus:border-emerald-500 transition-colors'

const btnPrimary =
  'flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-500 ' +
  'text-white text-sm font-semibold py-2 px-4 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed'

const btnSecondary =
  'flex items-center justify-center gap-2 bg-zinc-700 hover:bg-zinc-600 ' +
  'text-zinc-200 text-sm font-medium py-2 px-4 rounded-lg transition-colors disabled:opacity-40'

const btnDanger =
  'flex items-center justify-center gap-2 bg-red-700/30 hover:bg-red-600/50 ' +
  'text-red-400 hover:text-red-300 text-sm font-medium py-2 px-4 rounded-lg transition-colors'

// ─── Helpers ──────────────────────────────────────────────────────────────────
const EMPTY_EMP = { name: '', department: '', employee_id: '' }

function EnrollBadge({ enrolled }) {
  return enrolled ? (
    <span className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-900/40 text-emerald-400">
      <CheckCircle2 size={11} /> Enrolled
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-zinc-700 text-zinc-500">
      <XCircle size={11} /> Not enrolled
    </span>
  )
}

// ─── Photo Lightbox ───────────────────────────────────────────────────────────
function PhotoLightbox({ src, onClose }) {
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="relative max-w-lg w-full rounded-2xl overflow-hidden shadow-2xl border border-zinc-700"
        onClick={e => e.stopPropagation()}
      >
        <button
          onClick={onClose}
          className="absolute top-3 right-3 z-10 p-1.5 bg-zinc-900/80 hover:bg-zinc-700 text-zinc-300 rounded-full transition-colors"
        >
          <X size={16} />
        </button>
        <img src={src} alt="Enrolled photo" className="w-full h-auto max-h-[80vh] object-contain bg-zinc-900" />
      </div>
    </div>
  )
}

// ─── Single-employee enroll modal ─────────────────────────────────────────────
function EnrollModal({ employee, onClose, onSuccess }) {
  const [file, setFile]       = useState(null)
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [result, setResult]   = useState(null)
  const inputRef              = useRef()

  const handleFile = (f) => {
    if (!f) return
    setFile(f)
    setPreview(URL.createObjectURL(f))
    setError(null)
    setResult(null)
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const f = e.dataTransfer.files?.[0]
    if (f) handleFile(f)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!file) { setError('Please select a photo'); return }
    setLoading(true); setError(null)
    try {
      const fd = new FormData()
      fd.append('photo', file)
      const res = await api.enrollEmployee(employee.id, fd)
      setResult(res)
      onSuccess()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-zinc-800 border border-zinc-700 rounded-2xl w-full max-w-md shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-700">
          <div>
            <h3 className="font-semibold text-zinc-100 flex items-center gap-2">
              <CameraIcon size={16} className="text-emerald-400" />
              Enroll Face Photo
            </h3>
            <p className="text-xs text-zinc-400 mt-0.5">{employee.name} · {employee.employee_id}</p>
          </div>
          <button onClick={onClose} className="p-1.5 text-zinc-400 hover:text-white hover:bg-zinc-700 rounded-lg transition-colors">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {/* Drop zone */}
          <div
            onDrop={handleDrop}
            onDragOver={e => e.preventDefault()}
            onClick={() => inputRef.current?.click()}
            className="relative border-2 border-dashed border-zinc-600 hover:border-emerald-500 rounded-xl p-6 text-center cursor-pointer transition-colors group"
          >
            <input
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/jpg"
              className="hidden"
              onChange={e => handleFile(e.target.files?.[0])}
            />
            {preview ? (
              <img src={preview} alt="Preview" className="mx-auto h-40 object-contain rounded-lg" />
            ) : (
              <div className="space-y-2">
                <Upload size={32} className="mx-auto text-zinc-500 group-hover:text-emerald-400 transition-colors" />
                <p className="text-sm text-zinc-400 group-hover:text-zinc-300 transition-colors">
                  Drop a face photo here or <span className="text-emerald-400 font-medium">click to browse</span>
                </p>
                <p className="text-xs text-zinc-600">JPEG · PNG · Max 10 MB</p>
              </div>
            )}
          </div>

          {preview && (
            <button
              type="button"
              onClick={() => { setFile(null); setPreview(null); setResult(null) }}
              className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1 transition-colors"
            >
              <X size={12} /> Remove photo
            </button>
          )}

          {error && (
            <div className="flex items-start gap-2 bg-red-900/30 border border-red-700/60 rounded-lg px-3 py-2.5 text-sm text-red-300">
              <AlertCircle size={15} className="shrink-0 mt-0.5" /> {error}
            </div>
          )}

          {result && (
            <div className="bg-emerald-900/30 border border-emerald-700/60 rounded-lg px-3 py-2.5 text-sm text-emerald-300 space-y-1">
              <p className="font-medium">✓ {result.message}</p>
              <p className="text-xs text-emerald-400/80">
                Faces detected: {result.faces_detected} · Augmented embeddings: {result.aug_embeddings}
              </p>
            </div>
          )}

          <div className="flex gap-3 pt-1">
            <button type="button" onClick={onClose} className={btnSecondary + ' flex-1'}>Cancel</button>
            <button type="submit" disabled={loading || !file} className={btnPrimary + ' flex-1'}>
              {loading ? <><RefreshCw size={14} className="animate-spin" /> Enrolling…</> : <><Upload size={14} /> Enroll</>}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Delete confirmation modal ────────────────────────────────────────────────
function DeleteModal({ employee, onClose, onConfirm }) {
  const [loading, setLoading] = useState(false)
  const handleConfirm = async () => {
    setLoading(true)
    await onConfirm()
    setLoading(false)
  }
  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-zinc-800 border border-zinc-700 rounded-2xl w-full max-w-sm shadow-2xl p-6 space-y-5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-red-900/40 flex items-center justify-center shrink-0">
            <Trash2 size={18} className="text-red-400" />
          </div>
          <div>
            <h3 className="font-semibold text-zinc-100">Delete Employee</h3>
            <p className="text-xs text-zinc-400 mt-0.5">This action cannot be undone.</p>
          </div>
        </div>
        <p className="text-sm text-zinc-300">
          Remove <span className="font-semibold text-white">{employee.name}</span> ({employee.employee_id}) and all stored face embeddings?
        </p>
        <div className="flex gap-3">
          <button onClick={onClose} className={btnSecondary + ' flex-1'}>Cancel</button>
          <button onClick={handleConfirm} disabled={loading} className={btnDanger + ' flex-1'}>
            {loading ? <RefreshCw size={14} className="animate-spin" /> : <Trash2 size={14} />}
            {loading ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Bulk Enroll panel (collapsible) ─────────────────────────────────────────
function BulkEnrollSection({ onSuccess }) {
  const [open, setOpen]         = useState(false)
  const [csvFile, setCsvFile]   = useState(null)
  const [zipFile, setZipFile]   = useState(null)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState(null)
  const [result, setResult]     = useState(null)
  const csvRef                  = useRef()
  const zipRef                  = useRef()

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!csvFile || !zipFile) { setError('Both CSV and ZIP files are required'); return }
    setLoading(true); setError(null); setResult(null)
    try {
      const fd = new FormData()
      fd.append('csv_file', csvFile)
      fd.append('photos_zip', zipFile)
      const res = await api.bulkEnrollEmployees(fd)
      setResult(res)
      setCsvFile(null); setZipFile(null)
      onSuccess()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-zinc-800 border border-zinc-700 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-zinc-750 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-zinc-300">
          <FileArchive size={15} className="text-blue-400" />
          Bulk Import (CSV + ZIP)
        </span>
        {open ? <ChevronUp size={15} className="text-zinc-500" /> : <ChevronDown size={15} className="text-zinc-500" />}
      </button>

      {open && (
        <div className="px-5 pb-5 border-t border-zinc-700">
          <p className="text-xs text-zinc-500 mt-4 mb-4 leading-relaxed">
            Upload a <strong className="text-zinc-400">CSV</strong> with columns <code className="bg-zinc-700 px-1 rounded text-emerald-400">name, department, employee_id</code>{' '}
            and a <strong className="text-zinc-400">ZIP</strong> containing photos named{' '}
            <code className="bg-zinc-700 px-1 rounded text-emerald-400">&lt;employee_id&gt;.jpg</code>.
          </p>
          <form onSubmit={handleSubmit} className="space-y-3">
            {/* CSV upload */}
            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1.5">Employee CSV</label>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => csvRef.current?.click()}
                  className="flex items-center gap-2 text-sm bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-3 py-2 rounded-lg transition-colors"
                >
                  <Download size={14} /> Choose CSV
                </button>
                <span className="text-xs text-zinc-500 truncate">{csvFile ? csvFile.name : 'No file chosen'}</span>
                <input ref={csvRef} type="file" accept=".csv" className="hidden" onChange={e => setCsvFile(e.target.files?.[0])} />
              </div>
            </div>

            {/* ZIP upload */}
            <div>
              <label className="block text-xs font-medium text-zinc-400 mb-1.5">Photos ZIP</label>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => zipRef.current?.click()}
                  className="flex items-center gap-2 text-sm bg-zinc-700 hover:bg-zinc-600 text-zinc-300 px-3 py-2 rounded-lg transition-colors"
                >
                  <FileArchive size={14} /> Choose ZIP
                </button>
                <span className="text-xs text-zinc-500 truncate">{zipFile ? zipFile.name : 'No file chosen'}</span>
                <input ref={zipRef} type="file" accept=".zip" className="hidden" onChange={e => setZipFile(e.target.files?.[0])} />
              </div>
            </div>

            {error && (
              <div className="flex items-start gap-2 bg-red-900/30 border border-red-700/60 rounded-lg px-3 py-2 text-sm text-red-300">
                <AlertCircle size={14} className="shrink-0 mt-0.5" /> {error}
              </div>
            )}

            {result && (
              <div className="bg-zinc-700/50 border border-zinc-600 rounded-lg px-4 py-3 text-sm space-y-2">
                <div className="flex gap-4 text-xs font-semibold">
                  <span className="text-zinc-300">Total: {result.total}</span>
                  <span className="text-emerald-400">✓ {result.success} enrolled</span>
                  {result.failed > 0 && <span className="text-red-400">✗ {result.failed} failed</span>}
                </div>
                {result.errors?.length > 0 && (
                  <div className="mt-2 space-y-1 max-h-28 overflow-y-auto">
                    {result.errors.map((e, i) => (
                      <p key={i} className="text-xs text-zinc-400">{e}</p>
                    ))}
                  </div>
                )}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !csvFile || !zipFile}
              className={btnPrimary + ' w-full mt-1'}
            >
              {loading
                ? <><RefreshCw size={14} className="animate-spin" /> Importing…</>
                : <><Upload size={14} /> Start Bulk Import</>}
            </button>
          </form>
        </div>
      )}
    </div>
  )
}

// ─── Main panel ───────────────────────────────────────────────────────────────
export default function EmployeesPanel() {
  const [employees, setEmployees] = useState([])
  const [form, setForm]           = useState(EMPTY_EMP)
  const [loading, setLoading]     = useState(false)
  const [fetching, setFetching]   = useState(true)
  const [error, setError]         = useState(null)
  const [toast, setToast]         = useState(null)
  const [enrollTarget, setEnrollTarget] = useState(null)   // employee to enroll
  const [deleteTarget, setDeleteTarget] = useState(null)   // employee to delete
  const [lightboxSrc, setLightboxSrc]   = useState(null)   // photo lightbox URL
  const [search, setSearch]       = useState('')

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }

  const fetchEmployees = useCallback(async () => {
    try {
      const data = await api.getEmployees()
      setEmployees(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setFetching(false)
    }
  }, [])

  useEffect(() => { fetchEmployees() }, [fetchEmployees])

  const handleCreate = async (e) => {
    e.preventDefault()
    setLoading(true); setError(null)
    try {
      await api.createEmployee(form)
      setForm(EMPTY_EMP)
      showToast(`Employee "${form.name}" created`)
      await fetchEmployees()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async () => {
    try {
      await api.deleteEmployee(deleteTarget.id)
      showToast(`"${deleteTarget.name}" deleted`, 'success')
      setDeleteTarget(null)
      await fetchEmployees()
    } catch (err) {
      setError(err.message)
      setDeleteTarget(null)
    }
  }

  const handleEnrollSuccess = async () => {
    showToast('Face enrolled successfully')
    await fetchEmployees()
  }

  const filtered = employees.filter(emp =>
    emp.name.toLowerCase().includes(search.toLowerCase()) ||
    emp.employee_id.toLowerCase().includes(search.toLowerCase()) ||
    (emp.department || '').toLowerCase().includes(search.toLowerCase())
  )

  const totalEnrolled  = employees.filter(e => e.is_enrolled).length
  const totalPending   = employees.length - totalEnrolled

  return (
    <div className="h-full overflow-y-auto p-3 sm:p-6 space-y-5">

      {/* ── Stats bar ── */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Total Employees', value: employees.length, color: 'text-zinc-200'   },
          { label: 'Enrolled',        value: totalEnrolled,    color: 'text-emerald-400' },
          { label: 'Pending',         value: totalPending,     color: 'text-yellow-400'  },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 text-center">
            <p className={`text-2xl font-bold ${color}`}>{value}</p>
            <p className="text-xs text-zinc-500 mt-0.5">{label}</p>
          </div>
        ))}
      </div>

      {/* ── Global error banner ── */}
      {error && (
        <div className="flex items-start gap-2 bg-red-900/40 border border-red-700 text-red-300 rounded-lg px-4 py-3 text-sm">
          <AlertCircle size={15} className="shrink-0 mt-0.5" />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-200"><X size={14} /></button>
        </div>
      )}

      {/* ── Create Employee form ── */}
      <div className="bg-zinc-800 border border-zinc-700 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider flex items-center gap-2">
          <UserPlus size={15} className="text-emerald-400" /> Add Employee
        </h3>
        <form onSubmit={handleCreate} className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <input
            className={inputCls}
            placeholder="Full name *"
            required
            value={form.name}
            onChange={e => setForm({ ...form, name: e.target.value })}
          />
          <input
            className={inputCls}
            placeholder="Department"
            value={form.department}
            onChange={e => setForm({ ...form, department: e.target.value })}
          />
          <input
            className={inputCls}
            placeholder="Employee ID *"
            required
            value={form.employee_id}
            onChange={e => setForm({ ...form, employee_id: e.target.value })}
          />
          <button
            type="submit"
            disabled={loading}
            className={btnPrimary + ' sm:col-span-3 w-full'}
          >
            {loading
              ? <><RefreshCw size={14} className="animate-spin" /> Creating…</>
              : <><UserPlus size={14} /> Add Employee</>}
          </button>
        </form>
      </div>

      {/* ── Bulk enroll (collapsible) ── */}
      <BulkEnrollSection onSuccess={() => { showToast('Bulk import completed'); fetchEmployees() }} />

      {/* ── Employee list ── */}
      <div className="bg-zinc-800 border border-zinc-700 rounded-xl overflow-hidden">
        {/* Table header + search */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-5 py-4 border-b border-zinc-700">
          <h3 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider flex items-center gap-2">
            <Users size={15} className="text-blue-400" /> Employees
          </h3>
          <div className="flex items-center gap-3">
            <input
              className="bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-emerald-500 w-48 transition-colors"
              placeholder="Search…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            <button
              onClick={fetchEmployees}
              title="Refresh"
              className="p-1.5 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 rounded-lg transition-colors"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        {fetching ? (
          <div className="flex items-center justify-center py-16 text-zinc-500">
            <RefreshCw size={20} className="animate-spin mr-2" /> Loading…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-zinc-500 gap-3">
            <Users size={36} className="opacity-30" />
            <p className="text-sm">{search ? 'No employees match your search' : 'No employees yet — add one above'}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-zinc-700/40">
                <tr className="text-left text-xs text-zinc-400 uppercase tracking-wider">
                  <th className="px-4 py-3 w-12">Photo</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3 hidden sm:table-cell">Employee ID</th>
                  <th className="px-4 py-3 hidden md:table-cell">Department</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 hidden lg:table-cell">Enrolled At</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-700/60">
                {filtered.map(emp => (
                  <tr key={emp.id} className="hover:bg-zinc-700/20 transition-colors group">
                    {/* Avatar / Photo */}
                    <td className="px-4 py-3">
                      {emp.is_enrolled ? (
                        <button
                          onClick={() => setLightboxSrc(api.employeePhotoUrl(emp.id))}
                          title="View photo"
                          className="relative w-9 h-9 rounded-full overflow-hidden bg-zinc-700 border-2 border-emerald-700/60 hover:border-emerald-400 transition-colors"
                        >
                          <img
                            src={api.employeePhotoUrl(emp.id)}
                            alt={emp.name}
                            className="w-full h-full object-cover"
                            onError={e => { e.target.style.display = 'none' }}
                          />
                        </button>
                      ) : (
                        <div className="w-9 h-9 rounded-full bg-zinc-700 border-2 border-zinc-600 flex items-center justify-center">
                          <span className="text-xs font-semibold text-zinc-400">
                            {emp.name.charAt(0).toUpperCase()}
                          </span>
                        </div>
                      )}
                    </td>

                    <td className="px-4 py-3">
                      <p className="font-medium text-zinc-200">{emp.name}</p>
                      <p className="text-xs text-zinc-500 sm:hidden">{emp.employee_id}</p>
                    </td>

                    <td className="px-4 py-3 text-zinc-400 hidden sm:table-cell font-mono text-xs">
                      {emp.employee_id}
                    </td>

                    <td className="px-4 py-3 text-zinc-400 hidden md:table-cell">
                      {emp.department || <span className="text-zinc-600 italic">—</span>}
                    </td>

                    <td className="px-4 py-3">
                      <EnrollBadge enrolled={emp.is_enrolled} />
                    </td>

                    <td className="px-4 py-3 text-zinc-500 text-xs hidden lg:table-cell">
                      {emp.enrolled_at
                        ? new Date(emp.enrolled_at).toLocaleDateString('en-IN', {
                            day: '2-digit', month: 'short', year: 'numeric'
                          })
                        : <span className="italic">—</span>}
                    </td>

                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        {/* View photo */}
                        {emp.is_enrolled && (
                          <button
                            onClick={() => setLightboxSrc(api.employeePhotoUrl(emp.id))}
                            title="View enrolled photo"
                            className="p-1.5 text-zinc-400 hover:text-blue-400 hover:bg-blue-900/30 rounded-lg transition-colors"
                          >
                            <Eye size={14} />
                          </button>
                        )}
                        {/* Enroll / Re-enroll */}
                        <button
                          onClick={() => setEnrollTarget(emp)}
                          title={emp.is_enrolled ? 'Re-enroll face' : 'Enroll face'}
                          className="p-1.5 text-zinc-400 hover:text-emerald-400 hover:bg-emerald-900/30 rounded-lg transition-colors"
                        >
                          <Upload size={14} />
                        </button>
                        {/* Delete */}
                        <button
                          onClick={() => setDeleteTarget(emp)}
                          title="Delete employee"
                          className="p-1.5 text-zinc-400 hover:text-red-400 hover:bg-red-900/30 rounded-lg transition-colors"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Modals ── */}
      {enrollTarget && (
        <EnrollModal
          employee={enrollTarget}
          onClose={() => setEnrollTarget(null)}
          onSuccess={() => { setEnrollTarget(null); handleEnrollSuccess() }}
        />
      )}

      {deleteTarget && (
        <DeleteModal
          employee={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onConfirm={handleDelete}
        />
      )}

      {lightboxSrc && (
        <PhotoLightbox src={lightboxSrc} onClose={() => setLightboxSrc(null)} />
      )}

      {/* ── Toast ── */}
      {toast && (
        <div className={`fixed bottom-6 right-6 px-4 py-3 rounded-lg text-sm font-medium shadow-lg z-50 transition-all ${
          toast.type === 'error' ? 'bg-red-600' : 'bg-emerald-600'
        }`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}
