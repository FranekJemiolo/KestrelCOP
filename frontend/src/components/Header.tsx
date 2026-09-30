import React from 'react'
import { Radio, ShieldAlert, Cpu, Activity } from 'lucide-react'

interface HeaderProps {
  isConnected: boolean
  totalEntities: number
  staleCount: number
  alertCount: number
  onToggleSim: () => void
  isSimRunning: boolean
}

export const Header: React.FC<HeaderProps> = ({
  isConnected,
  totalEntities,
  staleCount,
  alertCount,
  onToggleSim,
  isSimRunning,
}) => {
  return (
    <header className="tactical-header">
      <div className="header-left">
        <div className="title-group">
          <span className="brand-icon">🦅</span>
          <h1 className="brand-title">KESTREL<span>COP</span></h1>
          <span className="hud-badge">TACTICAL COMMAND v0.1.0</span>
        </div>
      </div>

      <div className="header-center">
        <div className="metric-pill">
          <Activity size={14} className="icon-emerald" />
          <span>ACTIVE TRACKS: <strong>{totalEntities - staleCount}</strong></span>
        </div>
        <div className="metric-pill">
          <Cpu size={14} className="icon-cyan" />
          <span>STALE: <strong>{staleCount}</strong></span>
        </div>
        {alertCount > 0 && (
          <div className="metric-pill alert">
            <ShieldAlert size={14} className="icon-red" />
            <span>TCCC ALERTS: <strong>{alertCount}</strong></span>
          </div>
        )}
      </div>

      <div className="header-right">
        <button
          onClick={onToggleSim}
          className={`btn-sim ${isSimRunning ? 'running' : ''}`}
          title="Toggle local synthetic sensor injection"
        >
          {isSimRunning ? 'PAUSE SIMULATION' : 'SIMULATE TELEMETRY'}
        </button>

        <div className={`status-pill ${isConnected ? 'online' : 'offline'}`}>
          <Radio size={14} />
          <span>{isConnected ? 'MESH ONLINE' : 'RF SEVERED (DIL BUFFER)'}</span>
        </div>
      </div>
    </header>
  )
}
