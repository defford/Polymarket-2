import { useState, useCallback } from 'react'

const BASE = ''

export function useApi() {
  const [loading, setLoading] = useState(false)

  const request = useCallback(async (method, path, body = null) => {
    setLoading(true)
    try {
      const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
      }
      if (body) opts.body = JSON.stringify(body)
      const res = await fetch(`${BASE}${path}`, opts)
      const data = await res.json()
      return data
    } catch (e) {
      console.error(`API ${method} ${path} failed:`, e)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const get = useCallback((path) => request('GET', path), [request])
  const put = useCallback((path, body) => request('PUT', path, body), [request])
  const post = useCallback((path, body) => request('POST', path, body), [request])

  return { get, put, post, loading }
}
