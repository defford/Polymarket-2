import { useState, useEffect, useCallback } from 'react'
import { Plus, Copy, Check } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import SwarmSummary from './SwarmSummary'
import BotCard from './BotCard'
import AddBotModal from './AddBotModal'

export default function SwarmView({ swarmState, onSelectBot }) {
  const { get } = useApi()
  const [bots, setBots] = useState([])
  const [showAddModal, setShowAddModal] = useState(false)
  const [copyStatus, setCopyStatus] = useState('idle') // idle, loading, success, error

  const fetchBots = useCallback(() => {
    get('/api/swarm').then(data => {
      if (data) setBots(data)
    })
  }, [get])

  useEffect(() => {
    fetchBots()
  }, [fetchBots])

  // Refresh bot list periodically
  useEffect(() => {
    const interval = setInterval(fetchBots, 10000)
    return () => clearInterval(interval)
  }, [fetchBots])

  const copyToClipboard = (text) => {
    // Use execCommand fallback as primary — navigator.clipboard.writeText can
    // hang indefinitely when the tab lacks focus (e.g. PWA, unfocused tab)
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    let ok = false
    try { ok = document.execCommand('copy') } catch { /* ignore */ }
    document.body.removeChild(textarea)
    return ok
  }

  const handleCopyForAI = async () => {
    setCopyStatus('loading')
    try {
      const data = await get('/api/swarm/export-latest-sessions')
      if (data && data.export_text) {
        const ok = await copyToClipboard(data.export_text)
        setCopyStatus(ok ? 'success' : 'error')
        setTimeout(() => setCopyStatus('idle'), 2000)
      } else {
        setCopyStatus('error')
        setTimeout(() => setCopyStatus('idle'), 2000)
      }
    } catch (err) {
      console.error('Failed to copy swarm sessions:', err)
      setCopyStatus('error')
      setTimeout(() => setCopyStatus('idle'), 2000)
    }
  }

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="flex justify-end mb-2">
        <button
          onClick={handleCopyForAI}
          disabled={copyStatus === 'loading'}
          className={`
            flex items-center gap-2 px-3 py-1.5 rounded text-xs font-mono font-bold transition-all
            ${copyStatus === 'success' 
              ? 'bg-accent-green/20 text-accent-green border border-accent-green/30' 
              : copyStatus === 'error'
              ? 'bg-red-500/20 text-red-400 border border-red-500/30'
              : 'bg-surface-3 hover:bg-surface-4 text-text-secondary border border-transparent hover:border-surface-4'
            }
          `}
        >
          {copyStatus === 'loading' ? (
            <span className="animate-pulse">Generating...</span>
          ) : copyStatus === 'success' ? (
            <>
              <Check className="w-3.5 h-3.5" />
              Copied!
            </>
          ) : copyStatus === 'error' ? (
            <>Error</>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              Copy Latest Sessions for AI
            </>
          )}
        </button>
      </div>

      <SwarmSummary />

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {bots.map(bot => (
          <BotCard
            key={bot.id}
            bot={bot}
            wsState={swarmState[String(bot.id)]}
            onClick={onSelectBot}
            onRefresh={fetchBots}
          />
        ))}

        {/* Add Bot Card */}
        <button
          onClick={() => setShowAddModal(true)}
          className="card border-dashed border-surface-3 hover:border-accent-cyan/30 transition-all cursor-pointer group min-h-[160px] flex items-center justify-center"
        >
          <div className="text-center">
            <Plus className="w-8 h-8 text-surface-4 group-hover:text-accent-cyan/50 transition-colors mx-auto mb-2" />
            <span className="text-xs font-mono text-text-dim group-hover:text-text-secondary transition-colors">
              Add Bot
            </span>
          </div>
        </button>
      </div>

      {showAddModal && (
        <AddBotModal
          bots={bots}
          onClose={() => setShowAddModal(false)}
          onCreated={() => fetchBots()}
        />
      )}
    </div>
  )
}
