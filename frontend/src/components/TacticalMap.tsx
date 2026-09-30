import React, { useEffect, useRef } from 'react'
import * as maplibregl from 'maplibre-gl'
import type { Map as MapLibreMap, Marker } from 'maplibre-gl'
import * as pmtiles from 'pmtiles'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { TacticalEntity } from '../types/cot'

// Register PMTiles offline protocol for local vector map archives
const protocol = new pmtiles.Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

interface TacticalMapProps {
  entities: TacticalEntity[]
  selectedUid: string | null
  onSelectEntity: (uid: string | null) => void
}

export const TacticalMap: React.FC<TacticalMapProps> = ({
  entities,
  selectedUid,
  onSelectEntity,
}) => {
  const mapContainer = useRef<HTMLDivElement>(null)
  const mapInstance = useRef<MapLibreMap | null>(null)
  const markersRef = useRef<Map<string, Marker>>(new Map())

  // Initialize MapLibre
  useEffect(() => {
    if (!mapContainer.current || mapInstance.current) return

    // Tactical dark baseline style
    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors | KestrelCOP Tactical Basemap',
          },
        },
        layers: [
          {
            id: 'background',
            type: 'background',
            paint: { 'background-color': '#0a0e17' },
          },
          {
            id: 'osm-tiles',
            type: 'raster',
            source: 'osm',
            paint: {
              'raster-saturation': -0.85,
              'raster-brightness-max': 0.45,
              'raster-contrast': 0.25,
            },
          },
        ],
      },
      center: [21.0122, 52.2297], // Warsaw Tactical Sector baseline
      zoom: 13,
      pitch: 35,
    })

    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapInstance.current = map

    return () => {
      map.remove()
      mapInstance.current = null
    }
  }, [])

  // Sync entity markers with map
  useEffect(() => {
    const map = mapInstance.current
    if (!map) return

    const currentMarkers = markersRef.current
    const activeUids = new Set<string>()

    for (const entity of entities) {
      activeUids.add(entity.uid)
      let marker = currentMarkers.get(entity.uid)

      if (!marker) {
        // Create custom tactical DOM element
        const el = document.createElement('div')
        el.className = 'tactical-marker'

        const newMarker = new maplibregl.Marker({ element: el })
          .setLngLat([entity.lon, entity.lat])
          .addTo(map)

        el.addEventListener('click', (e) => {
          e.stopPropagation()
          onSelectEntity(entity.uid)
        })

        currentMarkers.set(entity.uid, newMarker)
        marker = newMarker
      } else {
        marker.setLngLat([entity.lon, entity.lat])
      }

      // Update marker styling based on affiliation and stale status
      const el = marker.getElement()
      el.innerHTML = ''
      el.style.opacity = entity.isStale ? '0.35' : '1.0'
      el.style.filter = entity.isStale ? 'grayscale(80%)' : 'none'

      const badge = document.createElement('div')
      badge.className = `marker-glyph ${entity.affiliation} ${entity.isStale ? 'stale' : ''}`

      if (entity.tcccAlert) {
        badge.classList.add('tccc-pulse')
      }

      // Label callsign
      const label = document.createElement('div')
      label.className = 'marker-label'
      label.textContent = entity.isStale ? `${entity.callsign} [STALE]` : entity.callsign

      el.appendChild(badge)
      el.appendChild(label)

      // Attach Popup
      const popupContent = `
        <div class="tactical-popup">
          <div class="popup-header">
            <strong>${entity.callsign}</strong>
            <span class="badge ${entity.affiliation}">${entity.affiliation.toUpperCase()}</span>
          </div>
          <div class="popup-body">
            <div>UID: <code>${entity.uid}</code></div>
            <div>COORDINATES: ${entity.lat.toFixed(6)}, ${entity.lon.toFixed(6)}</div>
            <div>ACCURACY (CE): ±${entity.circularError}m | ALT: ${entity.altitude}m</div>
            ${entity.heartRate ? `<div>HEART RATE: <strong>${entity.heartRate} BPM</strong></div>` : ''}
            ${entity.detectionLabel ? `<div>DETECTION: <strong>${entity.detectionLabel}</strong> (${(entity.confidence! * 100).toFixed(1)}%)</div>` : ''}
            <div>STATUS: <span style="color: ${entity.isStale ? '#ef4444' : '#10b981'}">${entity.isStale ? 'STALE (>30s)' : 'FRESH TRACK'}</span></div>
          </div>
        </div>
      `
      marker.setPopup(new maplibregl.Popup({ offset: 25 }).setHTML(popupContent))
    }

    // Clean up markers for removed entities
    for (const [uid, marker] of currentMarkers.entries()) {
      if (!activeUids.has(uid)) {
        marker.remove()
        currentMarkers.delete(uid)
      }
    }
  }, [entities, onSelectEntity])

  // Center on selected entity and show tactical popup
  useEffect(() => {
    const map = mapInstance.current
    if (!map || !selectedUid) return

    const target = entities.find((e) => e.uid === selectedUid)
    if (target) {
      map.flyTo({
        center: [target.lon, target.lat],
        zoom: Math.max(map.getZoom(), 14.5),
        speed: 1.2,
      })

      const marker = markersRef.current.get(selectedUid)
      if (marker && (!marker.getPopup() || !marker.getPopup().isOpen())) {
        marker.togglePopup()
      }
    }
  }, [selectedUid, entities])

  return (
    <div className="map-wrapper">
      <div ref={mapContainer} className="map-canvas" />
    </div>
  )
}
