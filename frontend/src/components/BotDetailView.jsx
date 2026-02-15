import { useState, useEffect, useCallback } from 'react'
import { ArrowLeft, Play, Square, Settings, Pencil } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import StatsCards from './StatsCards'
import SignalPanel from './SignalPanel'
import MarketPanel from './MarketPanel'
import TradeHistory from './TradeHistory'
import TradeDetailModal from './TradeDetailModal'
import ConfigPanel from './ConfigPanel'
import SessionsPanel from './SessionsPanel'
import PnlChart from './PnlChart'

const STATUS_BADGES = {
  running: { label: 'LIVE', cls: 'badge-green' },
  dry_run: { label: 'DRY RUN', cls: 'badge-yellow' },
  stopped: { label: 'STOPPED', cls: 'badge-muted' },
  error: { label: 'ERROR', cls: 'badge-red' },
  cooldown: { label: 'COOLDOWN', cls: 'badge-blue' },
}

export default function BotDetailView({ botId, botState, onBack }) {
  const { get, post, put } = useApi()
  const [botInfo, setBotInfo] = useState(null)
  const [config, setConfig] = useState(null)
  const [activeTab, setActiveTab] = useState('dashboard')
  const [selectedTrade, setSelectedTrade] = useState(null)
  const [isEditingName, setIsEditingName] = useState(false)
  const [editName, setEditName] = useState('')

  // Fetch bot info from the list endpoint
  useEffect(() => {
    get('/api/swarm').then(data => {
      if (data) {
        const bot = data.find(b => b.id === botId)
        if (bot) setBotInfo(bot)
      }
    })
  }, [get, botId])

  // Fetch config
  useEffect(() => {
    get(`/api/swarm/${botId}/config`).then(data => {
      if (data) setConfig(data)
    })
  }, [get, botId])

  const state = botState || {}
  const status = state.status || botInfo?.status || 'stopped'
  const isRunning = status === 'running' || status === 'dry_run'
  const badge = STATUS_BADGES[status] || STATUS_BADGES.stopped

  const handleStart = useCallback(async () => {
    await post(`/api/swarm/${botId}/start`)
  }, [post, botId])

  const handleStop = useCallback(async () => {
    await post(`/api/swarm/${botId}/stop`)
  }, [post, botId])

  const handleConfigUpdate = useCallback(async (updates) => {
    const data = await put(`/api/swarm/${botId}/config`, updates)
    if (data) setConfig(data)
  }, [put, botId])

  const handleEditName = () => {
    setEditName(botInfo?.name || '')
    setIsEditingName(true)
  }

  const handleSaveName = async () => {
    const trimmedName = editName.trim()
    if (!trimmedName || trimmedName === botInfo?.name) {
      setIsEditingName(false)
      return
    }
    const data = await put(`/api/swarm/${botId}`, { name: trimmedName })
    if (data) {
      setBotInfo(prev => prev ? { ...prev, name: trimmedName } : prev)
    }
    setIsEditingName(false)
  }

  const handleNameKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleSaveName()
    } else if (e.key === 'Escape') {
      setIsEditingName(false)
    }
  }

  return (
    <div className="space-y-0 animate-fade-in">
      {/* Bot Header */}
      <div className="bg-surface-1 border-b border-surface-3 px-4 py-2.5">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={onBack}
              className="p-1.5 rounded-lg hover:bg-surface-2 text-text-dim hover:text-text-secondary transition-colors cursor-pointer"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div>
              <div className="flex items-center gap-2">
                {isEditingName ? (
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onBlur={handleSaveName}
                    onKeyDown={handleNameKeyDown}
                    autoFocus
                    className="text-sm font-display font-bold text-text-primary bg-surface-2 border border-accent-cyan rounded px-1.5 py-0.5 focus:outline-none"
                  />
                ) : (
                  <h2 className="text-sm font-display font-bold text-text-primary">
                    {botInfo?.name || `Bot #${botId}`}
                  </h2>
                )}
                {!isEditingName && (
                  <button
                    onClick={handleEditName}
                    className="p-1 rounded text-text-dim hover:text-accent-cyan hover:bg-accent-cyan/10 transition-colors cursor-pointer"
                    title="Rename bot"
                  >
                    <Pencil className="w-3 h-3" />
                  </button>
                )}
                <span className={badge.cls}>
                  {isRunning && (
                    <span className="relative flex h-1.5 w-1.5 mr-1">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-current opacity-75" />
                      <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-current" />
                    </span>
                  )}
                  {badge.label}
                </span>
              </div>
              {botInfo?.description && (
                <p className="text-2xs text-text-dim font-mono">{botInfo.description}</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {isRunning ? (
              <button onClick={handleStop} className="btn-red text-xs py-1.5 px-3 flex items-center gap-1.5">
                <Square className="w-3 h-3" /> Stop
              </button>
            ) : (
              <button onClick={handleStart} className="btn-green text-xs py-1.5 px-3 flex items-center gap-1.5">
                <Play className="w-3 h-3" /> Start
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Sub-tabs */}
      <nav className="border-b border-surface-3 bg-surface-1/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-[1600px] mx-auto px-4 flex gap-0">
          {['dashboard', 'history', 'config'].map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-5 py-3 text-xs font-display font-semibold uppercase tracking-widest transition-colors relative cursor-pointer
                ${activeTab === tab
                  ? 'text-accent-cyan'
                  : 'text-text-dim hover:text-text-secondary'
                }`}
            >
              {tab}
              {activeTab === tab && (
                <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-accent-cyan" />
              )}
            </button>
          ))}
        </div>
      </nav>

      {/* Content */}
      <main className="max-w-[1600px] mx-auto w-full p-4">
        {activeTab === 'dashboard' ? (
          <div className="space-y-4 animate-fade-in">
            <StatsCards state={state} />
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
              <div className="lg:col-span-4 space-y-4">
                <MarketPanel market={state.current_market} />
                <SignalPanel signal={state.current_signal} />
              </div>
              <div className="lg:col-span-8 space-y-4">
                <PnlChart trades={state.recent_trades} />
                <TradeHistory trades={state.recent_trades} onTradeClick={setSelectedTrade} />
              </div>
            </div>
            {selectedTrade && (
              <TradeDetailModal
                trade={selectedTrade}
                onClose={() => setSelectedTrade(null)}
              />
            )}
          </div>
        ) : activeTab === 'history' ? (
          <SessionsPanel botId={botId} />
        ) : (
          <ConfigPanel config={config} onUpdate={handleConfigUpdate} />
        )}
      </main>
    </div>
  )
}
