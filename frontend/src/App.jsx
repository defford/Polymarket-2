import { useState, useEffect, useCallback } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useApi } from './hooks/useApi'
import StatusBar from './components/StatusBar'
import StatsCards from './components/StatsCards'
import SignalPanel from './components/SignalPanel'
import MarketPanel from './components/MarketPanel'
import TradeHistory from './components/TradeHistory'
import TradeDetailModal from './components/TradeDetailModal'
import ConfigPanel from './components/ConfigPanel'
import SessionsPanel from './components/SessionsPanel'
import PnlChart from './components/PnlChart'

export default function App() {
  const { state: wsState, connected } = useWebSocket()
  const { get, post, put } = useApi()
  const [config, setConfig] = useState(null)
  const [activeTab, setActiveTab] = useState('dashboard')

  // Fetch initial config
  useEffect(() => {
    get('/api/config').then((data) => {
      if (data) setConfig(data)
    })
  }, [get])

  const handleStart = useCallback(async () => {
    await post('/api/bot/start')
  }, [post])

  const handleStop = useCallback(async () => {
    await post('/api/bot/stop')
  }, [post])

  const handleConfigUpdate = useCallback(async (updates) => {
    const data = await put('/api/config', updates)
    if (data) setConfig(data)
  }, [put])

  const state = wsState || {}

  return (
    <div className="min-h-screen bg-surface-0 flex flex-col">
      {/* Top Status Bar */}
      <StatusBar
        status={state.status}
        mode={state.mode}
        connected={connected}
        onStart={handleStart}
        onStop={handleStop}
      />

      {/* Tab Navigation */}
      <nav className="border-b border-surface-3 bg-surface-1/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-[1600px] mx-auto px-4 flex gap-0">
          {['dashboard', 'history', 'config'].map((tab) => (
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

      {/* Main Content */}
      <main className="flex-1 max-w-[1600px] mx-auto w-full p-4">
        {activeTab === 'dashboard' ? (
          <DashboardView state={state} />
        ) : activeTab === 'history' ? (
          <SessionsPanel />
        ) : (
          <ConfigPanel config={config} onUpdate={handleConfigUpdate} />
        )}
      </main>
    </div>
  )
}


function DashboardView({ state }) {
  const [selectedTrade, setSelectedTrade] = useState(null)

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Stats Row */}
      <StatsCards state={state} />

      {/* Main Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Left Column - Signals + Market */}
        <div className="lg:col-span-4 space-y-4">
          <MarketPanel market={state.current_market} />
          <SignalPanel signal={state.current_signal} />
        </div>

        {/* Right Column - Chart + Trades */}
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
  )
}
