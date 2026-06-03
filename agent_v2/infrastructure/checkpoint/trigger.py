"""Checkpoint Trigger Policy Module

Provides configurable trigger policies for checkpoint creation.
Following the architecture: 运行时动态解析 trigger conditions

Features:
- Multiple trigger conditions
- Frequency control (always/once/nth_time/interval)
- Time-based triggers
- Error-based triggers
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional
from enum import Enum
import time

from .manager import CheckpointTrigger, CheckpointConfig


class TriggerFrequency(Enum):
    """Trigger frequency options"""
    ALWAYS = "always"
    ONCE = "once"
    NTH_TIME = "nth_time"
    INTERVAL = "interval"


@dataclass
class TriggerCondition:
    """Trigger condition configuration"""
    name: str
    condition_func: Callable[[dict[str, Any]], bool]
    frequency: TriggerFrequency = TriggerFrequency.ALWAYS
    nth_value: int = 1
    interval_seconds: Optional[float] = None


class CheckpointTriggerPolicy:
    """Configurable trigger policy for checkpoint creation
    
    Following the architecture: 按场景动态解析 trigger conditions
    
    Usage:
        policy = CheckpointTriggerPolicy()
        
        # Always checkpoint on error
        policy.add_trigger(
            name="on_error",
            condition=lambda s: s.get("error") is not None,
            frequency=TriggerFrequency.ONCE
        )
        
        # Checkpoint every 5 node completions
        policy.add_trigger(
            name="periodic",
            condition=lambda s: True,
            frequency=TriggerFrequency.NTH_TIME,
            nth_value=5
        )
        
        should_trigger, names = policy.should_trigger(state, node_name)
    """
    
    def __init__(self, config: Optional[CheckpointConfig] = None):
        self.config = config or CheckpointConfig()
        self._triggers: list[TriggerCondition] = []
        self._counters: dict[str, int] = {}
        self._last_trigger_time: dict[str, float] = {}
        self._triggered_once: dict[str, bool] = {}
    
    def add_trigger(
        self,
        name: str,
        condition: Callable[[dict[str, Any]], bool],
        frequency: TriggerFrequency = TriggerFrequency.ALWAYS,
        nth_value: int = 1,
        interval_seconds: Optional[float] = None
    ) -> 'CheckpointTriggerPolicy':
        """Add a trigger condition
        
        Args:
            name: Trigger name
            condition: Condition function that returns True when checkpoint should be created
            frequency: How often to trigger
            nth_value: For NTH_TIME frequency, trigger every nth time
            interval_seconds: For INTERVAL frequency, minimum seconds between triggers
            
        Returns:
            Self for chaining
        """
        trigger = TriggerCondition(
            name=name,
            condition_func=condition,
            frequency=frequency,
            nth_value=nth_value,
            interval_seconds=interval_seconds
        )
        self._triggers.append(trigger)
        return self
    
    def should_trigger(
        self,
        state: dict[str, Any],
        node_name: Optional[str] = None
    ) -> tuple[bool, list[str]]:
        """Check if any triggers should fire
        
        Args:
            state: Current workflow state
            node_name: Optional current node name
            
        Returns:
            Tuple of (should_trigger, list of triggered names)
        """
        triggered = []
        
        for trigger in self._triggers:
            try:
                if not trigger.condition_func(state):
                    continue
                
                if not self._check_frequency(trigger):
                    continue
                
                triggered.append(trigger.name)
                self._update_counters(trigger.name)
                
            except Exception:
                continue
        
        return len(triggered) > 0, triggered
    
    def _check_frequency(self, trigger: TriggerCondition) -> bool:
        """Check if trigger should fire based on frequency
        
        Args:
            trigger: Trigger condition
            
        Returns:
            True if should trigger
        """
        if trigger.frequency == TriggerFrequency.ALWAYS:
            return True
        
        elif trigger.frequency == TriggerFrequency.ONCE:
            if self._triggered_once.get(trigger.name, False):
                return False
            self._triggered_once[trigger.name] = True
            return True
        
        elif trigger.frequency == TriggerFrequency.NTH_TIME:
            count = self._counters.get(trigger.name, 0) + 1
            self._counters[trigger.name] = count
            return count % trigger.nth_value == 0
        
        elif trigger.frequency == TriggerFrequency.INTERVAL:
            current_time = time.time()
            last_time = self._last_trigger_time.get(trigger.name, 0)
            
            if current_time - last_time >= trigger.interval_seconds:
                self._last_trigger_time[trigger.name] = current_time
                return True
            
            return False
        
        return False
    
    def _update_counters(self, trigger_name: str) -> None:
        """Update trigger counters"""
        if trigger_name not in self._counters:
            self._counters[trigger_name] = 0
        self._counters[trigger_name] += 1
    
    def reset(self) -> None:
        """Reset all trigger counters and states"""
        self._counters.clear()
        self._last_trigger_time.clear()
        self._triggered_once.clear()
    
    def reset_trigger(self, name: str) -> None:
        """Reset a specific trigger's state
        
        Args:
            name: Trigger name
        """
        self._counters.pop(name, None)
        self._last_trigger_time.pop(name, None)
        self._triggered_once.pop(name, None)
    
    def remove_trigger(self, name: str) -> bool:
        """Remove a trigger by name
        
        Args:
            name: Trigger name
            
        Returns:
            True if removed
        """
        for i, trigger in enumerate(self._triggers):
            if trigger.name == name:
                self._triggers.pop(i)
                self.reset_trigger(name)
                return True
        return False
    
    def list_triggers(self) -> list[str]:
        """List all trigger names
        
        Returns:
            List of trigger names
        """
        return [t.name for t in self._triggers]
    
    def get_trigger_info(self, name: str) -> Optional[dict]:
        """Get trigger information
        
        Args:
            name: Trigger name
            
        Returns:
            Trigger info dict or None
        """
        for trigger in self._triggers:
            if trigger.name == name:
                return {
                    'name': trigger.name,
                    'frequency': trigger.frequency.value,
                    'nth_value': trigger.nth_value,
                    'interval_seconds': trigger.interval_seconds,
                    'counter': self._counters.get(name, 0),
                    'triggered_once': self._triggered_once.get(name, False),
                }
        return None


class ConditionalCheckpointPolicy(CheckpointTriggerPolicy):
    """Enhanced trigger policy with common conditions
    
    Pre-built conditions for common checkpoint scenarios.
    """
    
    def add_error_trigger(
        self,
        threshold: int = 3
    ) -> 'ConditionalCheckpointPolicy':
        """Add trigger for errors
        
        Args:
            threshold: Number of errors before triggering
            
        Returns:
            Self for chaining
        """
        error_count = [0]
        
        def condition(state: dict) -> bool:
            if state.get("error"):
                error_count[0] += 1
                return error_count[0] >= threshold
            return False
        
        return self.add_trigger(
            name=f"error_threshold_{threshold}",
            condition=condition,
            frequency=TriggerFrequency.ONCE
        )
    
    def add_state_change_trigger(
        self,
        watched_keys: list[str]
    ) -> 'ConditionalCheckpointPolicy':
        """Add trigger for state changes
        
        Args:
            watched_keys: State keys to watch for changes
            
        Returns:
            Self for chaining
        """
        last_values = {}
        
        def condition(state: dict) -> bool:
            for key in watched_keys:
                current_value = state.get(key)
                if key in last_values and last_values[key] != current_value:
                    last_values[key] = current_value
                    return True
                last_values[key] = current_value
            return False
        
        return self.add_trigger(
            name="state_change",
            condition=condition,
            frequency=TriggerFrequency.ALWAYS
        )
    
    def add_completion_trigger(
        self,
        node_names: list[str]
    ) -> 'ConditionalCheckpointPolicy':
        """Add trigger for node completion
        
        Args:
            node_names: Nodes that trigger checkpoint
            
        Returns:
            Self for chaining
        """
        def condition(state: dict) -> bool:
            return state.get("last_node") in node_names
        
        return self.add_trigger(
            name="node_completion",
            condition=condition,
            frequency=TriggerFrequency.ALWAYS
        )