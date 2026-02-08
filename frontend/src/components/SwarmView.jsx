import { useState, useEffect, useCallback } from 'react'
import { Plus } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import SwarmSummary from './SwarmSummary'
import BotCard from './BotCard'
import AddBotModal from './AddBotModal'

export default function SwarmView({ swarmState, onSelectBot }) {
  const { get } = useApi()
  const [bots, setBots] = useState([])
  const [showAddModal, setShowAddModal] = useState(false)

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

  return (
    <div className="space-y-4 animate-fade-in">
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
