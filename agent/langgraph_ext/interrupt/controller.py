"""Interrupt Controller Module

Controls workflow interruption and pause functionality.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
import threading
import uuid
import copy

from ..checkpoint.manager import Checkpoint, CheckpointTrigger
from ..persistence.persistence_manager import PersistenceManager


class InterruptReason(Enum):
    MANUAL = "manual"
    USER_CONFIRMATION = "user_confirmation"
    CONDITION_NOT_MET = "condition_not_met"
    ERROR = "error"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    NODE_COMPLETE = "node_complete"


@dataclass
class InterruptRequest:
    reason: InterruptReason
    node_name: Optional[str] = None
    message: Optional[str] = None
    interrupt_data: dict[str, Any] = field(default_factory=dict)
    requested_at: datetime = field(default_factory=datetime.now)
    requested_by: Optional[str] = None


@dataclass
class InterruptResult:
    interrupt_id: str
    success: bool
    workflow_state: Optional['WorkflowState'] = None
    resume_point: Optional[str] = None
    error: Optional[str] = None
    resumed_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeBreakpoint:
    node_name: str
    condition: Optional[Callable[[dict], bool]] = None
    pause_on_entry: bool = False
    pause_on_exit: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowState:
    run_id: str
    thread_id: Optional[str]
    current_node: Optional[str]
    state_data: dict[str, Any]
    checkpoint_id: Optional[str] = None
    pending_actions: list[dict[str, Any]] = field(default_factory=list)
    execution_history: list[dict[str, Any]] = field(default_factory=list)
    interrupted_at: Optional[datetime] = None
    interrupt_reason: Optional[InterruptReason] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'run_id': self.run_id,
            'thread_id': self.thread_id,
            'current_node': self.current_node,
            'state_data': self.state_data,
            'checkpoint_id': self.checkpoint_id,
            'pending_actions': self.pending_actions,
            'execution_history': self.execution_history,
            'interrupted_at': self.interrupted_at.isoformat() if self.interrupted_at else None,
            'interrupt_reason': self.interrupt_reason.value if self.interrupt_reason else None,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'WorkflowState':
        return cls(
            run_id=data['run_id'],
            thread_id=data.get('thread_id'),
            current_node=data.get('current_node'),
            state_data=data['state_data'],
            checkpoint_id=data.get('checkpoint_id'),
            pending_actions=data.get('pending_actions', []),
            execution_history=data.get('execution_history', []),
            interrupted_at=datetime.fromisoformat(data['interrupted_at']) if data.get('interrupted_at') else None,
            interrupt_reason=InterruptReason(data['interrupt_reason']) if data.get('interrupt_reason') else None,
            metadata=data.get('metadata', {})
        )


class InterruptController:
    """Controls workflow interruption and resumption.
    
    Features:
    - Manual interruption at any point
    - Conditional breakpoints
    - State preservation
    - Interrupt reason tracking
    - User confirmation workflows
    """
    
    def __init__(
        self,
        checkpoint_manager: Optional['CheckpointManager'] = None,
        persistence_manager: Optional[PersistenceManager] = None
    ):
        self.checkpoint_manager = checkpoint_manager
        self.persistence_manager = persistence_manager
        self._lock = threading.RLock()
        self._interrupted_workflows: dict[str, WorkflowState] = {}
        self._breakpoints: dict[str, list[NodeBreakpoint]] = {}
        self._interrupt_handlers: dict[InterruptReason, list[Callable]] = {}
        self._active_interrupts: dict[str, InterruptRequest] = {}
    
    def request_interrupt(
        self,
        run_id: str,
        reason: InterruptReason,
        thread_id: Optional[str] = None,
        node_name: Optional[str] = None,
        message: Optional[str] = None,
        state_data: Optional[dict[str, Any]] = None,
        interrupt_data: Optional[dict[str, Any]] = None
    ) -> str:
        """Request an interruption of a workflow.
        
        Args:
            run_id: Run ID
            reason: Reason for interruption
            thread_id: Optional thread ID
            node_name: Optional node name
            message: Optional interrupt message
            state_data: Current workflow state
            interrupt_data: Additional interrupt data
            
        Returns:
            Interrupt ID
        """
        interrupt_id = str(uuid.uuid4())
        
        request = InterruptRequest(
            reason=reason,
            node_name=node_name,
            message=message,
            interrupt_data=interrupt_data or {},
            requested_by='system'
        )
        
        with self._lock:
            self._active_interrupts[interrupt_id] = request
        
        return interrupt_id
    
    def interrupt_workflow(
        self,
        run_id: str,
        state: dict[str, Any],
        reason: InterruptReason,
        thread_id: Optional[str] = None,
        current_node: Optional[str] = None,
        message: Optional[str] = None,
        save_checkpoint: bool = True
    ) -> WorkflowState:
        """Interrupt a workflow and preserve its state.
        
        Args:
            run_id: Run ID
            state: Current workflow state
            reason: Reason for interruption
            thread_id: Optional thread ID
            current_node: Current executing node
            message: Optional interrupt message
            save_checkpoint: Whether to save a checkpoint
            
        Returns:
            WorkflowState with preserved data
        """
        with self._lock:
            checkpoint_id = None
            
            if save_checkpoint and self.checkpoint_manager:
                checkpoint = self.checkpoint_manager.create_checkpoint(
                    state=state,
                    run_id=run_id,
                    trigger=CheckpointTrigger.MANUAL,
                    thread_id=thread_id,
                    node_name=current_node,
                    description=f"Interrupt: {reason.value}"
                )
                checkpoint_id = checkpoint.id
            
            workflow_state = WorkflowState(
                run_id=run_id,
                thread_id=thread_id,
                current_node=current_node,
                state_data=copy.deepcopy(state),
                checkpoint_id=checkpoint_id,
                interrupted_at=datetime.now(),
                interrupt_reason=reason,
                metadata={'message': message} if message else {}
            )
            
            workflow_state.execution_history.append({
                'node': current_node,
                'action': 'interrupted',
                'reason': reason.value,
                'timestamp': datetime.now().isoformat()
            })
            
            self._interrupted_workflows[run_id] = workflow_state
            
            if self.persistence_manager:
                self.persistence_manager.save_state(
                    state=workflow_state.to_dict(),
                    run_id=run_id,
                    thread_id=thread_id,
                    node_name=current_node,
                    metadata={'interrupted': True, 'reason': reason.value}
                )
            
            self._trigger_interrupt_handlers(reason, workflow_state)
            
            return workflow_state
    
    def check_breakpoint(
        self,
        node_name: str,
        state: dict[str, Any],
        is_entry: bool = True
    ) -> bool:
        """Check if execution should pause at a breakpoint.
        
        Args:
            node_name: Node name
            state: Current state
            is_entry: Whether this is an entry check
            
        Returns:
            True if should pause
        """
        breakpoints = self._breakpoints.get(node_name, [])
        
        for bp in breakpoints:
            if is_entry and not bp.pause_on_entry:
                continue
            if not is_entry and not bp.pause_on_exit:
                continue
            
            if bp.condition:
                try:
                    if bp.condition(state):
                        return True
                except Exception:
                    pass
            else:
                return True
        
        return False
    
    def add_breakpoint(
        self,
        node_name: str,
        condition: Optional[Callable[[dict], bool]] = None,
        pause_on_entry: bool = False,
        pause_on_exit: bool = True,
        metadata: Optional[dict[str, Any]] = None
    ) -> NodeBreakpoint:
        """Add a breakpoint to a node.
        
        Args:
            node_name: Node name
            condition: Optional condition function
            pause_on_entry: Pause before node execution
            pause_on_exit: Pause after node execution
            metadata: Optional metadata
            
        Returns:
            Created NodeBreakpoint
        """
        breakpoint = NodeBreakpoint(
            node_name=node_name,
            condition=condition,
            pause_on_entry=pause_on_entry,
            pause_on_exit=pause_on_exit,
            metadata=metadata or {}
        )
        
        with self._lock:
            if node_name not in self._breakpoints:
                self._breakpoints[node_name] = []
            self._breakpoints[node_name].append(breakpoint)
        
        return breakpoint
    
    def remove_breakpoint(self, node_name: str, breakpoint_id: Optional[str] = None) -> bool:
        """Remove a breakpoint.
        
        Args:
            node_name: Node name
            breakpoint_id: Optional specific breakpoint ID
            
        Returns:
            True if removed
        """
        with self._lock:
            if node_name in self._breakpoints:
                if breakpoint_id is None:
                    del self._breakpoints[node_name]
                    return True
                
                for i, bp in enumerate(self._breakpoints[node_name]):
                    if str(id(bp)) == breakpoint_id:
                        del self._breakpoints[node_name][i]
                        return True
        
        return False
    
    def get_interrupted_workflow(self, run_id: str) -> Optional[WorkflowState]:
        """Get an interrupted workflow's state.
        
        Args:
            run_id: Run ID
            
        Returns:
            WorkflowState or None
        """
        with self._lock:
            return self._interrupted_workflows.get(run_id)
    
    def list_interrupted_workflows(self) -> list[WorkflowState]:
        """List all interrupted workflows.
        
        Returns:
            List of WorkflowState
        """
        with self._lock:
            return list(self._interrupted_workflows.values())
    
    def clear_interrupt(self, run_id: str) -> bool:
        """Clear an interrupt without resuming.
        
        Args:
            run_id: Run ID
            
        Returns:
            True if cleared
        """
        with self._lock:
            if run_id in self._interrupted_workflows:
                del self._interrupted_workflows[run_id]
                return True
        return False
    
    def register_interrupt_handler(
        self,
        reason: InterruptReason,
        handler: Callable[[WorkflowState], Any]
    ) -> None:
        """Register a handler for specific interrupt reasons.
        
        Args:
            reason: Interrupt reason
            handler: Handler function
        """
        with self._lock:
            if reason.value not in self._interrupt_handlers:
                self._interrupt_handlers[reason.value] = []
            self._interrupt_handlers[reason.value].append(handler)
    
    def _trigger_interrupt_handlers(self, reason: InterruptReason, state: WorkflowState) -> None:
        """Trigger registered handlers for an interrupt."""
        handlers = self._interrupt_handlers.get(reason.value, [])
        
        for handler in handlers:
            try:
                handler(state)
            except Exception:
                pass
    
    def create_resume_point(self, run_id: str) -> Optional[str]:
        """Create a resume point for interrupted workflow.
        
        Args:
            run_id: Run ID
            
        Returns:
            Resume point ID or None
        """
        workflow_state = self.get_interrupted_workflow(run_id)
        
        if not workflow_state:
            return None
        
        resume_point_id = str(uuid.uuid4())
        
        workflow_state.metadata['resume_point_id'] = resume_point_id
        workflow_state.metadata['resumable'] = True
        
        if self.persistence_manager:
            self.persistence_manager.save_state(
                state=workflow_state.to_dict(),
                run_id=run_id,
                thread_id=workflow_state.thread_id,
                metadata={'resume_point': resume_point_id}
            )
        
        return resume_point_id
    
    def validate_resume_point(self, run_id: str) -> tuple[bool, Optional[str]]:
        """Validate that a workflow can be resumed.
        
        Args:
            run_id: Run ID
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        workflow_state = self.get_interrupted_workflow(run_id)
        
        if not workflow_state:
            return False, f"No interrupted workflow found for run_id: {run_id}"
        
        if not workflow_state.metadata.get('resumable', False):
            return False, "Workflow is not marked as resumable"
        
        if not workflow_state.checkpoint_id and not self.checkpoint_manager:
            if not workflow_state.state_data:
                return False, "No state data available for resumption"
        
        return True, None


class WorkflowInterruptionContext:
    """Context manager for workflow interruption."""
    
    def __init__(
        self,
        controller: InterruptController,
        run_id: str,
        thread_id: Optional[str] = None
    ):
        self.controller = controller
        self.run_id = run_id
        self.thread_id = thread_id
        self._state: Optional[dict[str, Any]] = None
        self._current_node: Optional[str] = None
        self._interrupted = False
    
    def __enter__(self) -> 'WorkflowInterruptionContext':
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type and self.controller:
            self.interrupt(reason=InterruptReason.ERROR, state=self._state or {})
        return False
    
    def update_state(self, state: dict[str, Any], node: Optional[str] = None) -> None:
        """Update current workflow state."""
        self._state = state
        if node:
            self._current_node = node
    
    def interrupt(
        self,
        reason: InterruptReason,
        state: Optional[dict[str, Any]] = None,
        message: Optional[str] = None
    ) -> WorkflowState:
        """Interrupt the workflow."""
        self._interrupted = True
        current_state = state or self._state
        
        return self.controller.interrupt_workflow(
            run_id=self.run_id,
            state=current_state or {},
            reason=reason,
            thread_id=self.thread_id,
            current_node=self._current_node,
            message=message
        )
    
    @property
    def is_interrupted(self) -> bool:
        """Check if workflow has been interrupted."""
        return self._interrupted


def create_interrupt_controller(
    checkpoint_manager: Optional['CheckpointManager'] = None,
    persistence_manager: Optional[PersistenceManager] = None
) -> InterruptController:
    """Factory function to create an interrupt controller.
    
    Args:
        checkpoint_manager: Optional checkpoint manager
        persistence_manager: Optional persistence manager
        
    Returns:
        InterruptController instance
    """
    return InterruptController(checkpoint_manager, persistence_manager)