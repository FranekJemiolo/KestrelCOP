export interface CoTPoint {
  lat: number
  lon: number
  hae?: number
  ce?: number
  le?: number
}

export interface CoTDetailContact {
  callsign?: string
  endpoint?: string
}

export interface CoTDetailBiometrics {
  heart_rate_bpm?: number
  spo2_percent?: number
  skin_temp_c?: number
  stress_level?: string
  tccc_alert?: boolean
}

export interface CoTDetailSensorPayload {
  label?: string
  confidence?: number
  bbox?: [number, number, number, number]
  bearing_deg?: number
  range_m?: number
  model?: string
}

export interface CoTDetailTrack {
  speed?: number
  course?: number
}

export interface CoTDetail {
  contact?: CoTDetailContact
  biometrics?: CoTDetailBiometrics
  sensor_payload?: CoTDetailSensorPayload
  track?: CoTDetailTrack
  [key: string]: unknown
}

export interface CoTEvent {
  version: string
  uid: string
  type: string
  how: string
  time: string
  start: string
  stale: string
  point: CoTPoint
  detail?: CoTDetail
}

export interface CoTMessage {
  event: CoTEvent
}

export type EntityAffiliation = 'friendly' | 'hostile' | 'neutral' | 'unknown' | 'biometric'

export interface TacticalEntity {
  uid: string
  callsign: string
  affiliation: EntityAffiliation
  lat: number
  lon: number
  altitude: number
  circularError: number
  lastUpdated: Date
  staleTime: Date
  isStale: boolean
  speed?: number
  course?: number
  heartRate?: number
  tcccAlert?: boolean
  detectionLabel?: string
  confidence?: number
  rawEvent: CoTEvent
}
