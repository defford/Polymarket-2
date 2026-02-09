"""
ConfigBuilder — calls Claude API to generate optimized bot configs.

Takes an analysis result from AnalysisEngine, formats it into a prompt,
sends to Claude, parses the JSON response, and validates the config.
"""

import json
import logging
import re
import time
from typing import Optional

from config import BotConfig, ANTHROPIC_API_KEY
from analysis.prompts import SYSTEM_PROMPT, PARAM_RANGES, build_analysis_prompt

logger = logging.getLogger(__name__)


class ConfigBuilder:
    """Generates optimized BotConfig from trade analysis using Claude API."""

    def __init__(self):
        if not ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to your .env file."
            )
        import anthropic
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def generate_config(
        self,
        analysis: dict,
        goal: str = "balanced",
        base_config: Optional[BotConfig] = None,
    ) -> dict:
        """Generate an optimized config recommendation.

        Returns a dict with: config, reasoning, suggested_name, confidence, key_changes.
        """
        if base_config is None:
            base_config = BotConfig()

        base_dict = base_config.to_dict()
        prompt = build_analysis_prompt(analysis, goal, base_dict)

        # Try up to 2 times
        last_error = None
        for attempt in range(2):
            try:
                response = self._client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=60,
                )
                text = response.content[0].text
                parsed = self._parse_json(text)
                validated = self._validate_config(parsed, base_dict)
                return validated

            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                logger.warning(f"Attempt {attempt + 1}: {last_error}")
                if attempt == 0:
                    time.sleep(2)
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Attempt {attempt + 1}: {last_error}")
                if attempt == 0:
                    time.sleep(2)

        raise RuntimeError(f"Config generation failed after 2 attempts: {last_error}")

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from LLM response, trying multiple strategies."""
        # Strategy 1: Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract from markdown code block
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find first { to last }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(text[first_brace : last_brace + 1])
            except json.JSONDecodeError:
                pass

        raise json.JSONDecodeError("Could not extract JSON from response", text, 0)

    def _validate_config(self, parsed: dict, base_dict: dict) -> dict:
        """Validate and clamp config values, then return full recommendation."""
        config_dict = parsed.get("config", {})

        # Ensure all sections exist
        for section in ["signal", "risk", "exit", "trading"]:
            if section not in config_dict:
                config_dict[section] = base_dict.get(section, {})

        # Clamp values to valid ranges
        clamped = []
        for section_name, params in PARAM_RANGES.items():
            section = config_dict.get(section_name, {})
            for param, info in params.items():
                if param not in section:
                    # Use base config value
                    section[param] = base_dict.get(section_name, {}).get(param)
                    continue

                val = section[param]
                if info["type"] in ("int", "float"):
                    lo = info["min"]
                    hi = info["max"]
                    if info["type"] == "int":
                        val = int(round(val)) if isinstance(val, (int, float)) else lo
                    else:
                        val = float(val) if isinstance(val, (int, float)) else lo

                    if val < lo:
                        clamped.append(f"{section_name}.{param}: {section[param]} clamped to {lo}")
                        val = lo
                    elif val > hi:
                        clamped.append(f"{section_name}.{param}: {section[param]} clamped to {hi}")
                        val = hi
                    section[param] = val

                elif info["type"] == "enum":
                    if val not in info.get("values", []):
                        section[param] = base_dict.get(section_name, {}).get(param, info["values"][0])
                        clamped.append(f"{section_name}.{param}: invalid '{val}', using default")

                elif info["type"] == "bool":
                    section[param] = bool(val)

            config_dict[section_name] = section

        if clamped:
            logger.warning(f"Clamped {len(clamped)} parameters: {clamped}")

        # Validate through BotConfig
        config_dict["mode"] = config_dict.get("mode", "dry_run")

        # Handle EMA list fields that aren't in PARAM_RANGES
        for ema_key in ["btc_ema_1m", "btc_ema_5m", "btc_ema_15m", "btc_ema_1h", "btc_ema_4h", "btc_ema_1d"]:
            if ema_key not in config_dict.get("signal", {}):
                config_dict.setdefault("signal", {})[ema_key] = base_dict.get("signal", {}).get(ema_key)

        BotConfig.from_dict(config_dict)  # Raises if invalid

        return {
            "config": config_dict,
            "reasoning": parsed.get("reasoning", "No reasoning provided."),
            "optimization_focus": parsed.get("optimization_focus", "balanced"),
            "suggested_name": parsed.get("suggested_name", "Optimized Bot"),
            "confidence": parsed.get("confidence", "medium"),
            "key_changes": parsed.get("key_changes", []),
        }
