"""Workflow Resumer Module

Handles workflow resumption from checkpoints and interrupts.
Following the architecture: 断点恢复 from interruptions

Features:
- Resume from checkpoints
- Resume from interrupted states
- State validation
- Node skipping for efficiency
- Custom resumption logic
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional
import copy
import threading


@dataclass
class ResumptionConfig:
    """Configuration for workflow resumption"""
    skip_completed_nodes: bool = True
    replay_from_checkpoint: bool = True
    validate_state: bool = True
    reset_counters: bool = False
    merge_state: bool = True
    recovery_timeout: Optional[int] = None


@dataclass
class ResumptionResult:
    """Result of a resumption operation"""
    success: bool
    run_id: str
    resumed_state: dict[str, Any]
    skipped_nodes: list[str] = field(default_factory=list)
    executed_nodes: list[str] = field(default_factory=list)
    error: Optional[str] = None
    resumed_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkflowResumer:
    """Handles workflow resumption from interrupted or checkpointed states
    
    Following the architecture: 断点恢复 support
    
    Usage:
        resumer = WorkflowResumer(checkpoint_manager=manager)
        
        # Resume from checkpoint
        result = resumer.resume_from_checkpoint(
            checkpoint_id="cp_123",
            graph_executor=execute_graph,
            config=ResumptionConfig()
        )
        
        if result.success:
            state = result.resumed_state
    """
    
    def __init__(
        self,
        checkpoint_manager: Optional['CheckpointManager'] = None,
        persistence_manager: Optional['PersistenceManager'] = None,
        interrupt_controller: Optional['InterruptController'] = None
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
        """Resume workflow from a checkpoint
        
        Args:
            checkpoint_id: Checkpoint ID to resume from
            graph_executor: Function to execute graph nodes
            config: Resumption configuration
            
        Returns:
            ResumptionResult
        """
        config = config or ResumptionConfig()
        
        if not self.checkpoint_manager:
            return ResumptionResult(
                success=False,
                run_id="unknown",
                resumed_state={},
                error="No checkpoint manager configured"
            )
        
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
        
        resumed_state = copy.deepcopy(checkpoint.state)
        
        if config.reset_counters:
            if 'retry_count' in resumed_state:
                resumed_state['retry_count'] = 0
            if 'llm_calls' in resumed_state:
                resumed_state['llm_calls'] = 0
        
        resumed_state['resumed_from'] = checkpoint_id
        resumed_state['resumed_at'] = datetime.now().isoformat()
        
        return ResumptionResult(
            success=True,
            run_id=run_id,
            resumed_state=resumed_state,
            metadata={'checkpoint_id': checkpoint_id}
        )
    
    def resume_from_interrupt(
        self,
        run_id: str,
        decision: str,
        modified_state: Optional[dict] = None
    ) -> ResumptionResult:
        """Resume workflow from an interruption
        
        Args:
            run_id: Run ID
            decision: Resume decision (approve/reject/modify)
            modified_state: Optional modified state
            
        Returns:
            ResumptionResult
        """
        if not self.interrupt_controller:
            return ResumptionResult(
                success=False,
                run_id=run_id,
                resumed_state={},
                error="No interrupt controller configured"
            )
        
        workflow_state = self.interrupt_controller.get_interrupted_workflow(run_id)
        
        if not workflow_state:
            return ResumptionResult(
                success=False,
                run_id=run_id,
                resumed_state={},
                error=f"Interrupted workflow not found: {run_id}"
            )
        
        resumed_state = modified_state or copy.deepcopy(workflow_state.state_data)
        
        resumed_state['resume_decision'] = decision
        resumed_state['resumed_at'] = datetime.now().isoformat()
        
        resumed_workflow = self.interrupt_controller.resume_workflow(
            run_id=run_id,
            modified_state=resumed_state
        )
        
        return ResumptionResult(
            success=True,
            run_id=run_id,
            resumed_state=resumed_state,
            metadata={
                'decision': decision,
                'checkpoint_id': workflow_state.checkpoint_id
            }
        )
    
    def resume_from_state(
        self,
        run_id: str,
        state_data: dict[str, Any],
        thread_id: Optional[str] = None
    ) -> ResumptionResult:
        """Resume workflow from a state record
        
        Args:
            run_id: Run ID
            state_data: State data to resume from
            thread_id: Optional thread ID
            
        Returns:
            ResumptionResult
        """
        if self.persistence_manager:
            state_record = self.persistence_manager.load_latest(run_id, thread_id)
            
            if state_record:
                return ResumptionResult(
                    success=True,
                    run_id=run_id,
                    resumed_state=state_record.state_data,
                    metadata={'state_record_id': state_record.id}
                )
        
        return ResumptionResult(
            success=True,
            run_id=run_id,
            resumed_state=state_data,
            metadata={}
        )
    
    def _validate_state(self, state: dict) -> tuple[bool, Optional[str]]:
        """Validate state for resumption
        
        Args:
            state: State to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        required_fields = ['messages', 'status']
        
        for field_name in required_fields:
            if field_name not in state:
                return False, f"Missing required field: {field_name}"
        
        if 'status' in state:
            valid_statuses = ['init', 'routing', 'executing', 'reviewing', 'waiting_human', 'finished', 'error']
            if state['status'] not in valid_statuses:
                return False, f"Invalid status: {state['status']}"
        
        return True, None
    
    def register_resumption_hook(
        self,
        name: str,
        hook: Callable[[dict], dict]
    ) -> None:
        """Register a hook to be called during resumption
        
        Args:
            name: Hook name
            hook: Hook function
        """
        with self._lock:
            if name not in self._resumption_hooks:
                self._resumption_hooks[name] = []
            self._resumption_hooks[name].append(hook)
    
    def apply_resumption_hooks(self, state: dict) -> dict:
        """Apply all registered resumption hooks
        
        Args:
            state: State to process
            
        Returns:
            Processed state
        """
        result_state = copy.deepcopy(state)
        
        for hooks in self._resumption_hooks.values():
            for hook in hooks:
                try:
                    result_state = hook(result_state)
                except Exception:
                    pass
        
        return result_state


def create_workflow_resumer(
    checkpoint_manager: Optional['CheckpointManager'] = None,
    persistence_manager: Optional['PersistenceManager'] = None,
    interrupt_controller: Optional['InterruptController'] = None
) -> WorkflowResumer:
    """Factory function to create workflow resumer
    
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