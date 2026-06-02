"""Workflow Resumer Module

Handles workflow resumption from checkpoints and interrupts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional
import copy
import threading

from .controller import InterruptController, WorkflowState, InterruptReason
from ..checkpoint.manager import CheckpointManager, Checkpoint
from ..persistence.persistence_manager import PersistenceManager


@dataclass
class ResumptionConfig:
    skip_completed_nodes: bool = True
    replay_from_checkpoint: bool = True
    validate_state: bool = True
    reset_counters: bool = False
    merge_state: bool = True
    recovery_timeout: Optional[int] = None


@dataclass
class ResumptionResult:
    success: bool
    run_id: str
    resumed_state: dict[str, Any]
    skipped_nodes: list[str] = field(default_factory=list)
    executed_nodes: list[str] = field(default_factory=list)
    error: Optional[str] = None
    resumed_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkflowResumer:
    """Handles workflow resumption from interrupted or checkpointed states.
    
    Features:
    - Resume from checkpoints
    - Resume from interrupted states
    - State validation
    - Node skipping for efficiency
    - Custom resumption logic
    """
    
    def __init__(
        self,
        checkpoint_manager: Optional[CheckpointManager] = None,
        persistence_manager: Optional[PersistenceManager] = None,
        interrupt_controller: Optional[InterruptController] = None
    ):
        self.checkpoint_manager = checkpoint_manager
        self.persistence_manager = persistence_manager
        self.interrupt_controller = interrupt_controller
        self._lock = threading.RLock()
        self._resumption_hooks: dict[str, list[Callable]] = {}
    
    def resume_from_checkpoint(
        self,
        checkpoint_id: str,
        graph_executor: Callable,
        config: Optional[ResumptionConfig] = None
    ) -> ResumptionResult:
        """Resume workflow from a checkpoint.
        
        Args:
            checkpoint_id: Checkpoint ID to resume from
            graph_executor: Function to execute graph nodes
            config: Resumption configuration
            
        Returns:
            ResumptionResult
        """
        config = config or ResumptionConfig()
        
        checkpoint = self.checkpoint_manager.get_checkpoint(checkpoint_id)
        
        if not checkpoint:
            return ResumptionResult(
                success=False,
                run_id="unknown",
                resumed_state={},
                error=f"Checkpoint not found: {checkpoint_id}"
            )
        
        run_id = checkpoint.metadata.run_id
        
        if config.validate_state:
            is_valid, error = self._validate_state(checkpoint.state)
            if not is_valid:
                return ResumptionResult(
                    success=False,
                    run_id=run_id,
                    resumed_state={},
                    error=f"State validation failed: {error}"
                )
        
        resumed_state = checkpoint.state
        
        if config.reset_counters:
            resumed_state = self._reset_counters(resumed_state)
        
        self._trigger_resumption_hooks('checkpoint', run_id, resumed_state)
        
        return ResumptionResult(
            success=True,
            run_id=run_id,
            resumed_state=resumed_state,
            metadata={
                'checkpoint_id': checkpoint_id,
                'resumed_from': checkpoint.metadata.node_name
            }
        )
    
    def resume_from_interrupt(
        self,
        run_id: str,
        graph_executor: Callable,
        config: Optional[ResumptionConfig] = None
    ) -> ResumptionResult:
        """Resume workflow from an interrupt.
        
        Args:
            run_id: Run ID to resume
            graph_executor: Function to execute graph nodes
            config: Resumption configuration
            
        Returns:
            ResumptionResult
        """
        config = config or ResumptionConfig()
        
        workflow_state = self.interrupt_controller.get_interrupted_workflow(run_id)
        
        if not workflow_state:
            if self.persistence_manager:
                saved_state = self.persistence_manager.load_latest_state(run_id)
                if saved_state:
                    workflow_state = WorkflowState.from_dict(saved_state)
        
        if not workflow_state:
            return ResumptionResult(
                success=False,
                run_id=run_id,
                resumed_state={},
                error=f"No interrupted workflow found: {run_id}"
            )
        
        if config.validate_state:
            is_valid, error = self._validate_state(workflow_state.state_data)
            if not is_valid:
                return ResumptionResult(
                    success=False,
                    run_id=run_id,
                    resumed_state={},
                    error=f"State validation failed: {error}"
                )
        
        resumed_state = copy.deepcopy(workflow_state.state_data)
        
        if config.skip_completed_nodes:
            skipped = self._get_skipped_nodes(workflow_state)
        else:
            skipped = []
        
        if config.reset_counters:
            resumed_state = self._reset_counters(resumed_state)
        
        self._trigger_resumption_hooks('interrupt', run_id, resumed_state)
        
        self.interrupt_controller.clear_interrupt(run_id)
        
        return ResumptionResult(
            success=True,
            run_id=run_id,
            resumed_state=resumed_state,
            skipped_nodes=skipped,
            metadata={
                'interrupt_reason': workflow_state.interrupt_reason.value if workflow_state.interrupt_reason else None,
                'resumed_from': workflow_state.current_node
            }
        )
    
    def resume_from_latest(
        self,
        run_id: str,
        thread_id: Optional[str] = None,
        graph_executor: Callable = None,
        config: Optional[ResumptionConfig] = None
    ) -> ResumptionResult:
        """Resume from the latest available checkpoint or interrupt.
        
        Args:
            run_id: Run ID
            thread_id: Optional thread ID
            graph_executor: Optional graph executor
            config: Resumption configuration
            
        Returns:
            ResumptionResult
        """
        config = config or ResumptionConfig()
        
        if self.interrupt_controller:
            workflow_state = self.interrupt_controller.get_interrupted_workflow(run_id)
            if workflow_state:
                return self.resume_from_interrupt(run_id, graph_executor, config)
        
        if self.checkpoint_manager:
            checkpoint = self.checkpoint_manager.get_latest_checkpoint(run_id, thread_id)
            if checkpoint:
                return self.resume_from_checkpoint(checkpoint.id, graph_executor, config)
        
        if self.persistence_manager:
            state = self.persistence_manager.load_latest_state(run_id, thread_id)
            if state:
                return ResumptionResult(
                    success=True,
                    run_id=run_id,
                    resumed_state=state,
                    metadata={'source': 'persistence'}
                )
        
        return ResumptionResult(
            success=False,
            run_id=run_id,
            resumed_state={},
            error=f"No resumable state found for run: {run_id}"
        )
    
    def _validate_state(self, state: dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Validate that state can be resumed.
        
        Args:
            state: State to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(state, dict):
            return False, "State must be a dictionary"
        
        if 'messages' not in state:
            return False, "State missing required 'messages' field"
        
        return True, None
    
    def _reset_counters(self, state: dict[str, Any]) -> dict[str, Any]:
        """Reset execution counters in state.
        
        Args:
            state: Current state
            
        Returns:
            State with reset counters
        """
        state = copy.deepcopy(state)
        
        if 'llm_calls' in state:
            state['llm_calls'] = 0
        
        if 'node_counts' in state:
            state['node_counts'] = {k: 0 for k in state['node_counts'].keys()}
        
        return state
    
    def _get_skipped_nodes(self, workflow_state: WorkflowState) -> list[str]:
        """Get list of nodes to skip based on execution history.
        
        Args:
            workflow_state: Workflow state with execution history
            
        Returns:
            List of node names to skip
        """
        skipped = []
        
        for entry in workflow_state.execution_history:
            if entry.get('action') == 'completed':
                skipped.append(entry.get('node'))
        
        return [s for s in skipped if s]
    
    def register_resumption_hook(
        self,
        phase: str,
        hook: Callable[[str, dict[str, Any]], Any]
    ) -> None:
        """Register a hook to be called during resumption.
        
        Args:
            phase: Resumption phase ('pre', 'post', 'checkpoint', 'interrupt')
            hook: Hook function
        """
        with self._lock:
            if phase not in self._resumption_hooks:
                self._resumption_hooks[phase] = []
            self._resumption_hooks[phase].append(hook)
    
    def _trigger_resumption_hooks(
        self,
        phase: str,
        run_id: str,
        state: dict[str, Any]
    ) -> None:
        """Trigger registered resumption hooks.
        
        Args:
            phase: Resumption phase
            run_id: Run ID
            state: Current state
        """
        hooks = self._resumption_hooks.get(phase, [])
        
        for hook in hooks:
            try:
                hook(run_id, state)
            except Exception:
                pass
    
    def get_resumable_workflows(
        self,
        run_ids: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
        """Get list of resumable workflows.
        
        Args:
            run_ids: Optional filter by run IDs
            
        Returns:
            List of resumable workflow info
        """
        resumable = []
        
        if self.interrupt_controller:
            interrupted = self.interrupt_controller.list_interrupted_workflows()
            
            for ws in interrupted:
                if run_ids and ws.run_id not in run_ids:
                    continue
                
                resumable.append({
                    'run_id': ws.run_id,
                    'thread_id': ws.thread_id,
                    'type': 'interrupt',
                    'reason': ws.interrupt_reason.value if ws.interrupt_reason else None,
                    'current_node': ws.current_node,
                    'interrupted_at': ws.interrupted_at.isoformat() if ws.interrupted_at else None,
                    'checkpoint_id': ws.checkpoint_id
                })
        
        if self.checkpoint_manager:
            for run_id in (run_ids or []):
                checkpoints = self.checkpoint_manager.list_checkpoints(run_id)
                if checkpoints:
                    latest = checkpoints[-1]
                    resumable.append({
                        'run_id': run_id,
                        'type': 'checkpoint',
                        'checkpoint_id': latest.id,
                        'node_name': latest.metadata.node_name,
                        'created_at': latest.metadata.created_at.isoformat()
                    })
        
        return resumable


class StreamingResumer:
    """Handles resumable streaming execution."""
    
    def __init__(
        self,
        resumer: WorkflowResumer,
        buffer_size: int = 100
    ):
        self.resumer = resumer
        self.buffer_size = buffer_size
        self._stream_buffer: dict[str, list[Any]] = {}
        self._lock = threading.Lock()
    
    def add_to_buffer(
        self,
        run_id: str,
        event: Any
    ) -> None:
        """Add an event to the stream buffer.
        
        Args:
            run_id: Run ID
            event: Event to buffer
        """
        with self._lock:
            if run_id not in self._stream_buffer:
                self._stream_buffer[run_id] = []
            
            self._stream_buffer[run_id].append(event)
            
            if len(self._stream_buffer[run_id]) > self.buffer_size:
                self._stream_buffer[run_id].pop(0)
    
    def get_buffer(self, run_id: str) -> list[Any]:
        """Get the stream buffer for a run.
        
        Args:
            run_id: Run ID
            
        Returns:
            List of buffered events
        """
        with self._lock:
            return list(self._stream_buffer.get(run_id, []))
    
    def clear_buffer(self, run_id: str) -> None:
        """Clear the stream buffer for a run.
        
        Args:
            run_id: Run ID
        """
        with self._lock:
            if run_id in self._stream_buffer:
                self._stream_buffer[run_id].clear()
    
    def resume_stream(
        self,
        run_id: str,
        config: Optional[ResumptionConfig] = None
    ) -> tuple[dict[str, Any], list[Any]]:
        """Resume a stream and get buffered events.
        
        Args:
            run_id: Run ID
            config: Resumption config
            
        Returns:
            Tuple of (resumed_state, buffered_events)
        """
        result = self.resumer.resume_from_latest(run_id, config=config)
        
        if result.success:
            buffer = self.get_buffer(run_id)
            self.clear_buffer(run_id)
            return result.resumed_state, buffer
        
        return {}, []


def create_workflow_resumer(
    checkpoint_manager: Optional[CheckpointManager] = None,
    persistence_manager: Optional[PersistenceManager] = None,
    interrupt_controller: Optional[InterruptController] = None
) -> WorkflowResumer:
    """Factory function to create a workflow resumer.
    
    Args:
        checkpoint_manager: Optional checkpoint manager
        persistence_manager: Optional persistence manager
        interrupt_controller: Optional interrupt controller
        
    Returns:
        WorkflowResumer instance
    """
    return WorkflowResumer(
        checkpoint_manager=checkpoint_manager,
        persistence_manager=persistence_manager,
        interrupt_controller=interrupt_controller
    )