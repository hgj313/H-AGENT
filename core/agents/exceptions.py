"""
Agent 异常层次结构 - 统一的错误处理。
"""


class AgentError(Exception):
    """Agent 基础异常。"""

    def __init__(self, message: str, agent_id: str = "", details: dict = None):
        self.agent_id = agent_id
        self.details = details or {}
        super().__init__(message)


class AgentNotFoundError(AgentError):
    """Agent 未找到。"""
    pass


class AgentStateError(AgentError):
    """Agent 状态错误（如在运行中尝试执行新任务）。"""
    pass


class AgentTimeoutError(AgentError):
    """Agent 执行超时。"""
    pass


class AgentValidationError(AgentError):
    """Agent 输入验证失败。"""
    pass


class AgentRegistrationError(AgentError):
    """Agent 注册失败。"""
    pass
