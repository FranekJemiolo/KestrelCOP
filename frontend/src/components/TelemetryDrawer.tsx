import React from 'react'
import type { TacticalEntity } from '../types/cot'
import { Heart, Crosshair, Navigation, AlertTriangle, ChevronRight } from 'lucide-react'

interface TelemetryDrawerProps {
  entities: TacticalEntity[]
  selectedUid: string | null
  onSelectEntity: (uid: string) => void
}

export const TelemetryDrawer: React.FC<TelemetryDrawerProps> = ({
  entities,
  selectedUid,
  onSelectEntity,
}) => {
  return (
    <aside className="tactical-drawer">
      <div className="drawer-header">
        <h3>TRACKED ASSETS ({entities.length})</h3>
        <span className="drawer-sub">MIL-STD / CoT JSON 2.0</span>
      </div>

      <div className="entity-list">
        {entities.length === 0 ? (
          <div className="empty-state">
            <Navigation size={28} className="icon-muted" />
            <p>Scanning tactical MANET frequency...</p>
            <small>Awaiting Cursor-on-Target telemetry</small>
          </div>
        ) : (
          entities.map((entity) => {
            const isSelected = entity.uid === selectedUid
            return (
              <div
                key={entity.uid}
                className={`entity-card ${entity.affiliation} ${isSelected ? 'selected' : ''} ${entity.isStale ? 'stale' : ''}`}
                onClick={() => onSelectEntity(entity.uid)}
              >
                <div className="card-top">
                  <div className="card-identity">
                    {entity.affiliation === 'biometric' || entity.tcccAlert ? (
                      <Heart size={16} className={entity.tcccAlert ? 'icon-pulse-red' : 'icon-cyan'} />
                    ) : entity.detectionLabel ? (
                      <Crosshair size={16} className="icon-amber" />
                    ) : (
                      <Navigation size={16} className="icon-blue" />
                    )}
                    <span className="callsign">{entity.callsign}</span>
                  </div>

                  <span className={`affiliation-tag ${entity.affiliation}`}>
                    {entity.isStale ? 'STALE' : entity.affiliation.toUpperCase()}
                  </span>
                </div>

                <div className="card-details">
                  <div className="coord-row">
                    <span>{entity.lat.toFixed(5)}, {entity.lon.toFixed(5)}</span>
                    <span className="accuracy">±{entity.circularError}m</span>
                  </div>

                  {entity.heartRate !== undefined && (
                    <div className="vitals-row">
                      <span>HEART RATE:</span>
                      <strong className={entity.tcccAlert ? 'text-alert' : ''}>
                        {entity.heartRate} BPM {entity.tcccAlert && '⚠️ TCCC'}
                      </strong>
                    </div>
                  )}

                  {entity.detectionLabel && (
                    <div className="detection-row">
                      <span>TARGET:</span>
                      <strong>
                        {entity.detectionLabel} ({((entity.confidence || 0) * 100).toFixed(0)}%)
                      </strong>
                    </div>
                  )}
                </div>

                {entity.tcccAlert && (
                  <div className="tccc-banner">
                    <AlertTriangle size={12} />
                    <span>TACTICAL CASUALTY ALERT</span>
                  </div>
                )}

                <ChevronRight size={14} className="card-arrow" />
              </div>
            )
          })
        )}
      </div>
    </aside>
  )
}
