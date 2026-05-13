import { useState, useEffect } from 'react'
import { Bell, BellOff, Usb, Wifi, Radio } from 'lucide-react'
import { api } from '../api/client'

const TRANSPORT_META = {
  usb:  { label: 'USB Serial',  Icon: Usb,   color: 'text-emerald-400' },
  http: { label: 'WiFi / HTTP', Icon: Wifi,  color: 'text-green-400' },
  mqtt: { label: 'MQTT',        Icon: Radio, color: 'text-purple-400' },
}

export default function AlarmPanel({ onTest }) {
  const [status, setStatus] = useState(null)
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    api.getAlarmStatus().then(setStatus).catch(console.error)
  }, [])

  const testAlarm = async () => {
    setTesting(true)
    try {
      await api.testAlarm()
      onTest?.()
    } catch (e) {
      console.error('Alarm test failed:', e)
    } finally {
      setTimeout(() => setTesting(false), 1500)
    }
  }

  const transport = status?.transport || 'usb'
  const meta = TRANSPORT_META[transport] || TRANSPORT_META.usb
  const { Icon } = meta

  const isConnected =
    transport === 'usb'  ? status?.serial_connected :
    transport === 'http' ? !!status?.esp_ip :
    transport === 'mqtt' ? !!status?.mqtt_broker :
    false

  return (
    <div className="flex items-start justify-center h-full p-8">
      <div className="w-full max-w-md space-y-5">
        <h2 className="text-lg font-semibold text-zinc-200">Alarm Control</h2>

        {status && (
          <div className="bg-zinc-800 rounded-xl border border-zinc-700 p-5 space-y-3">
            <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">Status</h3>

            <div className="flex items-center justify-between">
              <div className={`flex items-center gap-2 text-sm font-medium ${meta.color}`}>
                <Icon size={16} />
                {meta.label}
              </div>
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                isConnected ? 'bg-green-900/50 text-green-400' : 'bg-red-900/50 text-red-400'
              }`}>
                {isConnected ? 'Ready' : 'Not configured'}
              </span>
            </div>

            <div className="text-xs text-zinc-500 space-y-1">
              {transport === 'usb' && (
                <p>Port: {status.serial_port} — {status.serial_connected ? 'connected' : 'disconnected'}</p>
              )}
              {transport === 'http' && status.esp_ip && (
                <p>ESP32 IP: {status.esp_ip}</p>
              )}
              {transport === 'mqtt' && (
                <>
                  <p>Broker: {status.mqtt_broker || '—'}</p>
                  <p>Topic: {status.mqtt_topic}</p>
                </>
              )}
            </div>
          </div>
        )}

        <button
          onClick={testAlarm}
          disabled={testing}
          className={`w-full flex items-center justify-center gap-3 py-4 rounded-xl font-semibold text-base transition-all ${
            testing ? 'bg-orange-600 scale-95' : 'bg-orange-600 hover:bg-orange-500 active:scale-95'
          } text-white disabled:opacity-80`}
        >
          {testing ? <BellOff size={20} className="animate-pulse" /> : <Bell size={20} />}
          {testing ? 'Triggering...' : 'Test Alarm'}
        </button>

        <p className="text-xs text-zinc-500 text-center">
          Sends a one-time signal via the configured transport to confirm the alarm is wired correctly.
        </p>
      </div>
    </div>
  )
}
