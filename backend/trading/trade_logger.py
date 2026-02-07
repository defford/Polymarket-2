"""
Trade logging and export functionality.
Handles exporting complete trade logs with market state snapshots to JSON.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import database as db
from models import Trade, TradeLogEntry, OrderStatus

logger = logging.getLogger(__name__)

# Export file location in project root
EXPORT_FILE_PATH = Path(__file__).parent.parent.parent / "trade_log.json"


class TradeLogger:
    """Handles trade log export and retrieval."""

    @staticmethod
    def get_trade_log_entry(trade: Trade) -> Optional[TradeLogEntry]:
        """
        Retrieve complete trade log entry for a trade.
        Reconstructs TradeLogEntry from Trade and stored log data.
        """
        log_data_str = db.get_trade_log_data(trade.id)
        if not log_data_str:
            return None

        try:
            log_data = json.loads(log_data_str)
            
            # Reconstruct TradeLogEntry
            entry = TradeLogEntry(
                trade_id=trade.id,
                timestamp=trade.timestamp,
                market_condition_id=trade.market_condition_id,
                side=trade.side,
                token_id=trade.token_id,
                order_id=trade.order_id,
                price=trade.price,
                size=trade.size,
                cost=trade.cost,
                status=trade.status,
                pnl=trade.pnl,
                fees=trade.fees,
                is_dry_run=trade.is_dry_run,
                signal_score=trade.signal_score,
                notes=trade.notes,
                order_type=log_data.get("order_type"),
                position_size_usd=log_data.get("position_size_usd"),
                position_held_duration_seconds=log_data.get("position_held_duration_seconds"),
            )
            
            # Parse buy_state and sell_state if present
            if "buy_state" in log_data:
                from models import MarketStateSnapshot
                try:
                    entry.buy_state = MarketStateSnapshot(**log_data["buy_state"])
                except Exception as e:
                    logger.debug(f"Error parsing buy_state for trade {trade.id}: {e}")
            
            if "sell_state" in log_data:
                from models import MarketStateSnapshot
                try:
                    entry.sell_state = MarketStateSnapshot(**log_data["sell_state"])
                except Exception as e:
                    logger.debug(f"Error parsing sell_state for trade {trade.id}: {e}")
            
            return entry
            
        except Exception as e:
            logger.error(f"Error reconstructing trade log entry for trade {trade.id}: {e}")
            return None

    @staticmethod
    def format_trade_log(entry: TradeLogEntry) -> dict:
        """
        Format trade log entry for JSON export.
        Converts Pydantic models to dicts with proper serialization.
        """
        try:
            return entry.model_dump(mode="json", exclude_none=True)
        except Exception as e:
            logger.error(f"Error formatting trade log entry: {e}")
            return {}

    @staticmethod
    def export_all_trades_to_json(
        file_path: Optional[Path] = None,
        include_incomplete: bool = True,
    ) -> Path:
        """
        Export all trades with full state to a single JSON file.
        
        Args:
            file_path: Optional custom path. Defaults to project root trade_log.json
            include_incomplete: If True, includes trades without complete log data
        
        Returns:
            Path to the exported file
        """
        if file_path is None:
            file_path = EXPORT_FILE_PATH
        
        logger.info(f"Exporting trade logs to {file_path}")
        
        # Get all trades
        all_trades = db.get_all_trades()
        logger.info(f"Found {len(all_trades)} total trades")
        
        # Build log entries
        log_entries = []
        complete_count = 0
        incomplete_count = 0
        
        for trade in all_trades:
            entry = TradeLogger.get_trade_log_entry(trade)
            
            if entry:
                # Complete entry with log data
                formatted = TradeLogger.format_trade_log(entry)
                log_entries.append(formatted)
                complete_count += 1
            elif include_incomplete:
                # Incomplete entry - just basic trade data
                basic_entry = {
                    "trade_id": trade.id,
                    "timestamp": trade.timestamp.isoformat(),
                    "market_condition_id": trade.market_condition_id,
                    "side": trade.side.value,
                    "token_id": trade.token_id,
                    "order_id": trade.order_id,
                    "price": trade.price,
                    "size": trade.size,
                    "cost": trade.cost,
                    "status": trade.status.value,
                    "pnl": trade.pnl,
                    "fees": trade.fees,
                    "is_dry_run": trade.is_dry_run,
                    "signal_score": trade.signal_score,
                    "notes": trade.notes,
                    "log_data_available": False,
                }
                log_entries.append(basic_entry)
                incomplete_count += 1
        
        # Create export structure
        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "total_trades": len(all_trades),
            "complete_logs": complete_count,
            "incomplete_logs": incomplete_count,
            "trades": log_entries,
        }
        
        # Write to file
        try:
            with open(file_path, "w") as f:
                json.dump(export_data, f, indent=2, default=str)
            
            logger.info(
                f"Successfully exported {len(log_entries)} trades "
                f"({complete_count} complete, {incomplete_count} incomplete) to {file_path}"
            )
            return file_path
            
        except Exception as e:
            logger.error(f"Error writing trade log export: {e}")
            raise

    @staticmethod
    def get_trade_summary() -> dict:
        """Get summary statistics about trade logs."""
        all_trades = db.get_all_trades()
        complete_logs = 0
        incomplete_logs = 0
        
        for trade in all_trades:
            log_data = db.get_trade_log_data(trade.id)
            if log_data:
                complete_logs += 1
            else:
                incomplete_logs += 1
        
        return {
            "total_trades": len(all_trades),
            "complete_logs": complete_logs,
            "incomplete_logs": incomplete_logs,
            "export_file_path": str(EXPORT_FILE_PATH),
        }


# Global singleton
trade_logger = TradeLogger()
