"""Checkpoint Trigger Policy Module

Provides configurable trigger policies for checkpoint creation.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional
from enum import Enum

from .manager import CheckpointTrigger, CheckpointConfig


class TriggerFrequency(Enum):
    ALWAYS = "always"
    ONCE = "once"
    NTH_TIME = "nth_time"
    INTERVAL = "interval"


@dataclass
class TriggerCondition:
    name: str
    condition_func: Callable[[dict[str, Any]], bool]
    frequency: TriggerFrequency = TriggerFrequency.ALWAYS
    nth_value: int = 1
    interval_seconds: Optional[float] = None


class CheckpointTriggerPolicy:
    """Configurable trigger policy for checkpoint creation.
    
    Features:
    - Multiple trigger conditions
    - Frequency control
    - Time-based triggers
    - Error-based triggers
    """
    
    def __init__(self, config: Optional[CheckpointConfig] = None):
        self.config = config or CheckpointConfig()
        self._triggers: list[TriggerCondition] = []
        self._counters: dict[str, int] = {}
        self._last_trigger_time: dict[str, float] = {}
    
    def add_trigger(
        self,
        name: str,
        condition: Callable[[dict[str, Any]], bool],
        frequency: TriggerFrequency = TriggerFrequency.ALWAYS,
        nth_value: int = 1,
        interval_seconds: Optional[float] = None
    ) -> 'CheckpointTriggerPolicy':
        """Add a trigger condition.
        
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
        """Check if any triggers should fire.
        
        Args:
            state: Current workflow state
            node_name: Optional current node name
            
        Returns:
            Tuple of (should_trigger, list of triggered names)
        """
        import time
        
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
                pass
        
        return len(triggered) > 0, triggered
    
    def _check_frequency(self, trigger: TriggerCondition) -> bool:
        """Check if trigger frequency allows execution."""
        import time
        
        if trigger.frequency == TriggerFrequency.ONCE:
            return self._counters.get(trigger.name, 0) == 0
        
        elif trigger.frequency == TriggerFrequency.NTH_TIME:
            count = self._counters.get(trigger.name, 0) + 1
            return count % trigger.nth_value == 0
        
        elif trigger.frequency == TriggerFrequency.INTERVAL:
            last_time = self._last_trigger_time.get(trigger.name, 0)
            if trigger.interval_seconds:
                return (time.time() - last_time) >= trigger.interval_seconds
            return True
        
        return True
    
    def _update_counters(self, name: str) -> None:
        """Update trigger counters."""
        import time
        
        self._counters[name] = self._counters.get(name, 0) + 1
        self._last_trigger_time[name] = time.time()
    
    def reset_counter(self, name: str) -> None:
        """Reset the counter for a trigger.
        
        Args:
            name: Trigger name
        """
        self._counters[name] = 0
    
    def get_counter(self, name: str) -> int:
        """Get the current counter for a trigger.
        
        Args:
            name: Trigger name
            
        Returns:
            Current counter value
        """
        return self._counters.get(name, 0)
    
    def clear(self) -> None:
        """Clear all triggers and counters."""
        self._triggers.clear()
        self._counters.clear()
        self._last_trigger_time.clear()


class StateChangeTrigger:
    """Trigger based on state changes."""
    
    @staticmethod
    def create(
        fields: list[str],
        comparison: str = "changed"
    ) -> Callable[[dict[str, Any]], bool]:
        """Create a state change trigger.
        
        Args:
            fields: List of state fields to monitor
            comparison: Type of comparison ('changed', 'increased', 'decreased')
            
        Returns:
            Condition function
        """
        previous_state = {}
        
        def condition(state: dict[str, Any]) -> bool:
            nonlocal previous_state
            
            for field in fields:
                current_value = state.get(field)
                previous_value = previous_state.get(field)
                
                if previous_value is None:
                    previous_state[field] = current_value
                    continue
                
                if comparison == "changed" and current_value != previous_value:
                    previous_state[field] = current_value
                    return True
                elif comparison == "increased":
                    try:
                        if float(current_value) > float(previous_value):
                            previous_state[field] = current_value
                            return True
                    except (TypeError, ValueError):
                        pass
                elif comparison == "decreased":
                    try:
                        if float(current_value) < float(previous_value):
                            previous_state[field] = current_value
                            return True
                    except (TypeError, ValueError):
                        pass
            
            return False
        
        return condition


class ErrorTrigger:
    """Trigger based on error conditions."""
    
    @staticmethod
    def create(
        error_type: Optional[type] = None,
        error_message_pattern: Optional[str] = None
    ) -> Callable[[dict[str, Any]], bool]:
        """Create an error trigger.
        
        Args:
            error_type: Type of error to trigger on
            error_message_pattern: Pattern to match in error message
            
        Returns:
            Condition function
        """
        import re
        
        pattern = re.compile(error_message_pattern) if error_message_pattern else None
        
        def condition(state: dict[str, Any]) -> bool:
            error = state.get('error') or state.get('_error')
            
            if error is None:
                return False
            
            if error_type and not isinstance(error, error_type):
                return False
            
            if pattern and hasattr(error, 'message'):
                return pattern.search(str(error.message)) is not None
            elif pattern:
                return pattern.search(str(error)) is not None
            
            return True
        
        return condition


class NodeCountTrigger:
    """Trigger based on node execution count."""
    
    @staticmethod
    def create(
        node_name: str,
        threshold: int,
        comparison: str = "gte"
    ) -> Callable[[dict[str, Any]], bool]:
        """Create a node count trigger.
        
        Args:
            node_name: Name of the node to monitor
            threshold: Threshold value
            comparison: Comparison type ('gte', 'lte', 'eq', 'mod')
            
        Returns:
            Condition function
        """
        def condition(state: dict[str, Any]) -> bool:
            node_counts = state.get('node_counts', {})
            count = node_counts.get(node_name, 0)
            
            if comparison == "gte":
                return count >= threshold
            elif comparison == "lte":
                return count <= threshold
            elif comparison == "eq":
                return count == threshold
            elif comparison == "mod":
                return count > 0 and count % threshold == 0
            
            return False
        
        return condition


class TimeBasedTrigger:
    """Time-based checkpoint trigger."""
    
    def __init__(self, interval_seconds: float):
        self.interval_seconds = interval_seconds
        self._last_trigger = 0
    
    def should_trigger(self) -> bool:
        """Check if enough time has passed since last trigger."""
        import time
        
        current_time = time.time()
        if current_time - self._last_trigger >= self.interval_seconds:
            self._last_trigger = current_time
            return True
        return False
    
    def reset(self) -> None:
        """Reset the timer."""
        self._last_trigger = 0


def create_trigger_policy(
    auto_trigger_nodes: Optional[list[str]] = None,
    trigger_on_error: bool = True,
    custom_conditions: Optional[list[dict[str, Any]]] = None
) -> CheckpointTriggerPolicy:
    """Create a trigger policy with common configurations.
    
    Args:
        auto_trigger_nodes: Nodes to auto-trigger checkpoints on
        trigger_on_error: Whether to trigger on errors
        custom_conditions: Custom trigger conditions
        
    Returns:
        Configured CheckpointTriggerPolicy
    """
    policy = CheckpointTriggerPolicy()
    
    if auto_trigger_nodes:
        policy.add_trigger(
            name="node_complete",
            condition=lambda state: state.get('current_node') in auto_trigger_nodes,
            frequency=TriggerFrequency.ALWAYS
        )
    
    if trigger_on_error:
        policy.add_trigger(
            name="on_error",
            condition=ErrorTrigger.create(),
            frequency=TriggerFrequency.ALWAYS
        )
    
    if custom_conditions:
        for cond in custom_conditions:
            policy.add_trigger(
                name=cond.get('name', 'custom'),
                condition=cond.get('condition'),
                frequency=TriggerFrequency(cond.get('frequency', 'always')),
                nth_value=cond.get('nth_value', 1),
                interval_seconds=cond.get('interval_seconds')
            )
    
    return policy


class PeriodicCheckpointTrigger:
    """Time-based periodic checkpoint trigger."""
    
    def __init__(self, interval_seconds: float):
        self.interval_seconds = interval_seconds
        self._last_checkpoint_time = 0
    
    def should_checkpoint(self, current_state: dict[str, Any]) -> bool:
        """Check if a periodic checkpoint should be created."""
        import time
        
        current_time = time.time()
        if current_time - self._last_checkpoint_time >= self.interval_seconds:
            self._last_checkpoint_time = current_time
            return True
        return False
    
    def reset(self) -> None:
        """Reset the periodic timer."""
        self._last_checkpoint_time = 0