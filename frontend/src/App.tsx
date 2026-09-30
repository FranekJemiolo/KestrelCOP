import { useEffect, useState, useMemo, useCallback } from 'react'
import { Header } from './components/Header'
import { TacticalMap } from './components/TacticalMap'
import { TelemetryDrawer } from './components/TelemetryDrawer'
import { TacticalWebSocketService } from './services/websocket'
import type { CoTMessage, TacticalEntity, EntityAffiliation } from './types/cot'
import './index.css'

export function App() {
  const [entitiesMap, setEntitiesMap] = useState<Map<string, TacticalEntity>>(new Map())
  const [selectedUid, setSelectedUid] = useState<string | null>(null)
  const [isConnected, setIsConnected] = useState<boolean>(false)
  const [isSimRunning, setIsSimRunning] = useState<boolean>(false)

  // Initialize WebSocket service
  const wsService = useMemo(() => new TacticalWebSocketService(), [])

  // Process incoming CoT message into TacticalEntity state
  const handleCoTMessage = useCallback((msg: CoTMessage) => {
    const evt = msg.event
    if (!evt || !evt.uid) return

    setEntitiesMap((prev) => {
      const next = new Map(prev)
      const existing = next.get(evt.uid)

      let affiliation: EntityAffiliation = 'unknown'
      if (evt.type.startsWith('a-f')) affiliation = 'friendly'
      else if (evt.type.startsWith('a-h')) affiliation = 'hostile'
      else if (evt.type.startsWith('b-m')) affiliation = 'biometric'
      else if (evt.type.startsWith('a-u')) affiliation = 'hostile' // Unknown/Hostile detection

      const callsign = evt.detail?.contact?.callsign || existing?.callsign || evt.uid
      const staleDate = evt.stale ? new Date(evt.stale) : new Date(Date.now() + 30000)

      const updated: TacticalEntity = {
        uid: evt.uid,
        callsign,
        affiliation,
        lat: evt.point.lat,
        lon: evt.point.lon,
        altitude: evt.point.hae || 0,
        circularError: evt.point.ce || 3.0,
        lastUpdated: new Date(),
        staleTime: staleDate,
        isStale: false,
        speed: evt.detail?.track?.speed || existing?.speed,
        course: evt.detail?.track?.course || existing?.course,
        heartRate: evt.detail?.biometrics?.heart_rate_bpm || existing?.heartRate,
        tcccAlert: evt.detail?.biometrics?.tccc_alert || existing?.tcccAlert,
        detectionLabel: evt.detail?.sensor_payload?.label || existing?.detectionLabel,
        confidence: evt.detail?.sensor_payload?.confidence || existing?.confidence,
        rawEvent: evt,
      }

      next.set(evt.uid, updated)
      return next
    })
  }, [])

  // Hook WebSocket and initial REST fetch
  useEffect(() => {
    const unsubMsg = wsService.onMessage(handleCoTMessage)
    const unsubStatus = wsService.onStatus(setIsConnected)

    wsService.connect()

    // Fetch initial active entities snapshot from Go collector
    fetch('/api/v1/entities')
      .then((res) => res.json())
      .then((data) => {
        if (data && Array.isArray(data.entities)) {
          for (const rawEvt of data.entities) {
            handleCoTMessage({ event: rawEvt })
          }
        }
      })
      .catch(() => {
        // Backend might be offline if testing frontend directly
      })

    return () => {
      unsubMsg()
      unsubStatus()
      wsService.disconnect()
    }
  }, [wsService, handleCoTMessage])

  // Periodic Stale-Data Evaluator (Runs every 1 second)
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now()
      setEntitiesMap((prev) => {
        let changed = false
        const next = new Map(prev)

        for (const [uid, entity] of next.entries()) {
          const isNowStale = now > entity.staleTime.getTime()
          const isExpired = now > entity.staleTime.getTime() + 180000 // Remove after 3 minutes

          if (isExpired) {
            next.delete(uid)
            changed = true
          } else if (isNowStale !== entity.isStale) {
            next.set(uid, { ...entity, isStale: isNowStale })
            changed = true
          }
        }

        return changed ? next : prev
      })
    }, 1000)

    return () => clearInterval(timer)
  }, [])

  // Local Tactical Simulation Generator (for manual or air-gapped demo testing)
  useEffect(() => {
    if (!isSimRunning) return

    let lat = 52.2297
    let lon = 21.0122
    let hr = 76

    const simTimer = setInterval(() => {
      lat += (Math.random() - 0.48) * 0.0003
      lon += (Math.random() - 0.48) * 0.0003
      hr = Math.min(175, Math.max(65, hr + Math.floor((Math.random() - 0.45) * 6)))

      // 1. Operator Scout-Alpha GPS track
      handleCoTMessage({
        event: {
          version: '2.0',
          uid: 'kestrel-scout-alpha',
          type: 'a-f-G-U-C',
          how: 'm-g',
          time: new Date().toISOString(),
          start: new Date().toISOString(),
          stale: new Date(Date.now() + 15000).toISOString(),
          point: { lat, lon, hae: 138.0, ce: 2.2 },
          detail: {
            contact: { callsign: 'SCOUT-ALPHA' },
            biometrics: { heart_rate_bpm: hr, tccc_alert: hr > 160 },
          },
        },
      })

      // 2. Recon Drone Target Detection
      if (Math.random() > 0.4) {
        handleCoTMessage({
          event: {
            version: '2.0',
            uid: 'target-overwatch-01',
            type: 'a-u-G-E-V',
            how: 'm-a',
            time: new Date().toISOString(),
            start: new Date().toISOString(),
            stale: new Date(Date.now() + 25000).toISOString(),
            point: { lat: lat + 0.0035, lon: lon + 0.0028, hae: 75.0, ce: 8.0 },
            detail: {
              contact: { callsign: 'UNKNOWN CONTACT #01' },
              sensor_payload: { label: 'armored_vehicle', confidence: 0.94 },
            },
          },
        })
      }
    }, 2000)

    return () => clearInterval(simTimer)
  }, [isSimRunning, handleCoTMessage])

  const entitiesList = useMemo(() => Array.from(entitiesMap.values()), [entitiesMap])
  const staleCount = useMemo(() => entitiesList.filter((e) => e.isStale).length, [entitiesList])
  const alertCount = useMemo(() => entitiesList.filter((e) => e.tcccAlert).length, [entitiesList])

  return (
    <div className="cop-app">
      <Header
        isConnected={isConnected}
        totalEntities={entitiesList.length}
        staleCount={staleCount}
        alertCount={alertCount}
        onToggleSim={() => setIsSimRunning((prev) => !prev)}
        isSimRunning={isSimRunning}
      />

      <div className="cop-body">
        <TacticalMap
          entities={entitiesList}
          selectedUid={selectedUid}
          onSelectEntity={setSelectedUid}
        />
        <TelemetryDrawer
          entities={entitiesList}
          selectedUid={selectedUid}
          onSelectEntity={setSelectedUid}
        />
      </div>
    </div>
  )
}

export default App
