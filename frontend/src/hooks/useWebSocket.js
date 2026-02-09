import { useState, useEffect, useRef, useCallback } from 'react'

const WS_PROTOCOL = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
const WS_URL = `${WS_PROTOCOL}//${window.location.host}/ws/dashboard`

export function useWebSocket() {
  const [swarmState, setSwarmState] = useState({})
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const pingTimer = useRef(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    try {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        pingTimer.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping')
          }
        }, 20000)
      }

      ws.onmessage = (event) => {
        if (event.data === 'pong') return
        try {
          const data = JSON.parse(event.data)

          if (data.type === 'swarm_state' && data.bots) {
            // Full swarm state update
            setSwarmState(data.bots)
          } else if (data.type === 'bot_state' && data.bot_id != null) {
            // Single bot update
            setSwarmState(prev => ({
              ...prev,
              [String(data.bot_id)]: data.state,
            }))
          } else if (!data.type) {
            // Legacy single-bot state (no type field) — assign to key "1"
            setSwarmState(prev => ({
              ...prev,
              '1': data,
            }))
          }
        } catch (e) {
          // ignore parse errors
        }
      }

      ws.onclose = () => {
        setConnected(false)
        clearInterval(pingTimer.current)
        reconnectTimer.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        ws.close()
      }
    } catch (e) {
      reconnectTimer.current = setTimeout(connect, 3000)
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearInterval(pingTimer.current)
      clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [connect])

  return { swarmState, connected }
}
