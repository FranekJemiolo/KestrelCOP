import type { CoTMessage } from '../types/cot'

export type MessageHandler = (message: CoTMessage) => void
export type StatusHandler = (connected: boolean) => void

export class TacticalWebSocketService {
  private ws: WebSocket | null = null
  private url: string
  private messageHandlers: Set<MessageHandler> = new Set()
  private statusHandlers: Set<StatusHandler> = new Set()
  private reconnectTimer: number | null = null
  private isExplicitClose = false

  constructor(url?: string) {
    if (url) {
      this.url = url
    } else {
      const loc = window.location
      const protocol = loc.protocol === 'https:' ? 'wss:' : 'ws:'
      // Fallback to collector port 8080 if running frontend on port 3000/5173
      const host = loc.port === '3000' || loc.port === '5173' ? `${loc.hostname}:8080` : loc.host
      this.url = `${protocol}//${host}/ws`
    }
  }

  public connect(): void {
    this.isExplicitClose = false
    try {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        this.notifyStatus(true)
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer)
          this.reconnectTimer = null
        }
      }

      this.ws.onmessage = (event: MessageEvent) => {
        try {
          const raw = event.data.trim()
          if (!raw) return

          // Handle potentially batched newline-separated payloads
          const lines = raw.split('\n')
          for (const line of lines) {
            if (!line.trim()) continue
            const parsed = JSON.parse(line) as CoTMessage
            if (parsed && parsed.event) {
              this.notifyMessage(parsed)
            }
          }
        } catch (err) {
          console.warn('[WS] Failed parsing incoming payload:', err)
        }
      }

      this.ws.onclose = () => {
        this.notifyStatus(false)
        if (!this.isExplicitClose) {
          this.scheduleReconnect()
        }
      }

      this.ws.onerror = () => {
        this.notifyStatus(false)
        if (this.ws) {
          this.ws.close()
        }
      }
    } catch (err) {
      console.warn('[WS] Connection attempt failed:', err)
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, 2500)
  }

  public disconnect(): void {
    this.isExplicitClose = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  public onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler)
    return () => this.messageHandlers.delete(handler)
  }

  public onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler)
    return () => this.statusHandlers.delete(handler)
  }

  private notifyMessage(msg: CoTMessage): void {
    for (const h of this.messageHandlers) {
      h(msg)
    }
  }

  private notifyStatus(connected: boolean): void {
    for (const h of this.statusHandlers) {
      h(connected)
    }
  }
}
