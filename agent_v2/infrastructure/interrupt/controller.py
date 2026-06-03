"""Interrupt Controller Module

Controls workflow interruption and pause functionality.
Following the architecture: Human-in-the-loop (HITL) 支持

Features:
- Manual interruption at any point
- Conditional breakpoints
- State preservation
- Interrupt reason tracking
- User confirmation workflows

This is a key component for implementing the "人工审核" pattern from architecture doc.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
import threading
import uuid
import copy


class InterruptReason(Enum):
    """Reasons for workflow interruption"""
    MANUAL = "manual"
    USER_CONFIRMATION = "user_confirmation"
    CONDITION_NOT_MET = "condition_not_met"
    ERROR = "error"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"
    NODE_COMPLETE = "node_complete"


@dataclass
class InterruptRequest:
    """Request for workflow interruption"""
    reason: InterruptReason
    node_name: Optional[str] = None
    message: Optional[str] = None
    interrupt_data: dict[str, Any] = field(default_factory=dict)
    requested_at: datetime = field(default_factory=datetime.now)
    requested_by: Optional[str] = None


@dataclass
class InterruptResult:
    """Result of an interrupt operation"""
    interrupt_id: str
    success: bool
    workflow_state: Optional['WorkflowState'] = None
    resume_point: Optional[str] = None
    error: Optional[str] = None
    resumed_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeBreakpoint:
    """Breakpoint configuration for a node"""
    node_name: str
    condition: Optional[Callable[[dict], bool]] = None
    pause_on_entry: bool = False
    pause_on_exit: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowState:
    """Workflow state preserved during interruption
    
    Following the architecture: State = source of truth
    This is the state that gets preserved and restored.
    """
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
    """Controls workflow interruption and resumption
    
    Following the architecture: Human-in-the-loop support
    
    Key patterns:
    - High-risk actions trigger interruption
    - User can approve/reject/modify
    - Workflow resumes based on user decision
    
    Usage:
        controller = InterruptController(checkpoint_manager=manager)
        
        # Set breakpoint
        controller.add_breakpoint("delete_node", pause_on_exit=True)
        
        # Request interruption
        interrupt_id = controller.request_interrupt(
            run_id="run_1",
            reason=InterruptReason.USER_CONFIRMATION,
            message="Approve deployment?"
        )
        
        # Get user decision
        decision = controller.get_interrupt_decision(interrupt_id)
    """
    
    def __init__(
        self,
        checkpoint_manager: Optional['CheckpointManager'] = None,
        persistence_manager: Optional['PersistenceManager'] = None
    ):
        self.checkpoint_manager = checkpoint_manager
        self.persistence_manager = persistence_manager
        self._lock = threading.RLock()
        self._interrupted_workflows: dict[str, WorkflowState] = {}
        self._breakpoints: dict[str, list[NodeBreakpoint]] = {}
        self._interrupt_handlers: dict[InterruptReason, list[Callable]] = {}
        self._active_interrupts: dict[str, InterruptRequest] = {}
        self._interrupt_decisions: dict[str, dict] = {}
    
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
        """Request an interruption of a workflow
        
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
        """Interrupt a workflow and preserve its state
        
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
        from ..checkpoint.manager import CheckpointTrigger
        
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
                    run_id=run_id,
                    state_data=workflow_state.to_dict(),
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
        """Check if execution should pause at a breakpoint
        
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
        """Add a breakpoint to a node
        
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
    
    def remove_breakpoint(self, node_name: str, breakpoint_id: str = None) -> bool:
        """Remove a breakpoint
        
        Args:
            node_name: Node name
            breakpoint_id: Optional specific breakpoint ID
            
        Returns:
            True if removed
        """
        with self._lock:
            if node_name not in self._breakpoints:
                return False
            
            if breakpoint_id:
                self._breakpoints[node_name] = [
                    bp for bp in self._breakpoints[node_name]
                    if bp.node_name != breakpoint_id
                ]
            else:
                del self._breakpoints[node_name]
            
            return True
    
    def set_interrupt_decision(
        self,
        interrupt_id: str,
        decision: str,
        data: Optional[dict] = None
    ) -> None:
        """Set the decision for an interrupt
        
        Args:
            interrupt_id: Interrupt ID
            decision: Decision (approve/reject/modify)
            data: Optional decision data
        """
        with self._lock:
            self._interrupt_decisions[interrupt_id] = {
                'decision': decision,
                'data': data or {},
                'timestamp': datetime.now().isoformat()
            }
    
    def get_interrupt_decision(self, interrupt_id: str) -> Optional[dict]:
        """Get the decision for an interrupt
        
        Args:
            interrupt_id: Interrupt ID
            
        Returns:
            Decision dict or None
        """
        with self._lock:
            return self._interrupt_decisions.get(interrupt_id)
    
    def wait_for_decision(
        self,
        interrupt_id: str,
        timeout: Optional[float] = None
    ) -> Optional[dict]:
        """Wait for interrupt decision
        
        Args:
            interrupt_id: Interrupt ID
            timeout: Optional timeout in seconds
            
        Returns:
            Decision dict or None if timeout
        """
        import time
        
        start_time = time.time()
        
        while True:
            decision = self.get_interrupt_decision(interrupt_id)
            if decision:
                return decision
            
            if timeout and (time.time() - start_time) >= timeout:
                return None
            
            time.sleep(0.1)
    
    def get_interrupted_workflow(self, run_id: str) -> Optional[WorkflowState]:
        """Get interrupted workflow state
        
        Args:
            run_id: Run ID
            
        Returns:
            WorkflowState or None
        """
        with self._lock:
            return self._interrupted_workflows.get(run_id)
    
    def list_interrupted_workflows(self) -> list[str]:
        """List all interrupted workflow run IDs
        
        Returns:
            List of run IDs
        """
        with self._lock:
            return list(self._interrupted_workflows.keys())
    
    def register_interrupt_handler(
        self,
        reason: InterruptReason,
        handler: Callable[[WorkflowState], None]
    ) -> None:
        """Register a handler for interrupt events
        
        Args:
            reason: Interrupt reason
            handler: Handler function
        """
        with self._lock:
            if reason not in self._interrupt_handlers:
                self._interrupt_handlers[reason] = []
            self._interrupt_handlers[reason].append(handler)
    
    def _trigger_interrupt_handlers(self, reason: InterruptReason, workflow_state: WorkflowState) -> None:
        """Trigger registered interrupt handlers"""
        handlers = self._interrupt_handlers.get(reason, [])
        for handler in handlers:
            try:
                handler(workflow_state)
            except Exception:
                pass
    
    def resume_workflow(
        self,
        run_id: str,
        resume_point: Optional[str] = None,
        modified_state: Optional[dict] = None
    ) -> WorkflowState:
        """Resume an interrupted workflow
        
        Args:
            run_id: Run ID
            resume_point: Optional node to resume from
            modified_state: Optional modified state
            
        Returns:
            Resumed WorkflowState
        """
        with self._lock:
            if run_id not in self._interrupted_workflows:
                raise ValueError(f"Workflow not found: {run_id}")
            
            workflow_state = self._interrupted_workflows[run_id]
            
            if modified_state:
                workflow_state.state_data = modified_state
            
            workflow_state.execution_history.append({
                'node': resume_point or workflow_state.current_node,
                'action': 'resumed',
                'timestamp': datetime.now().isoformat()
            })
            
            del self._interrupted_workflows[run_id]
            
            return workflow_state
    
    def clear_interrupted_workflow(self, run_id: str) -> bool:
        """Clear an interrupted workflow from memory
        
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


def create_interrupt_controller(
    checkpoint_manager: Optional['CheckpointManager'] = None,
    persistence_manager: Optional['PersistenceManager'] = None
) -> InterruptController:
    """Factory function to create interrupt controller
    
    Args:
        checkpoint_manager: Optional checkpoint manager
        persistence_manager: Optional persistence manager
        
    Returns:
        InterruptController instance
    """
    return InterruptController(
        checkpoint_manager=checkpoint_manager,
        persistence_manager=persistence_manager
    )