"""公司系统会话管理器

定时登录公司系统，自动续期 JSESSIONID。
会话有效期 30 分钟，每 25 分钟自动刷新一次。

使用方式:
    manager = SessionManager(
        base_url="http://47.108.166.14:8081",
        username="chenxueqin",
        password="1234",
    )
    manager.start()  # 启动后台续期线程
    session = manager.get_session()  # 获取带 cookie 的 requests.Session
    # ... 用 session 请求公司系统接口 ...
    manager.stop()  # 停止续期
"""

import logging
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# 默认刷新间隔（秒）— 会话 30 分钟有效，25 分钟刷新留 5 分钟余量
DEFAULT_REFRESH_INTERVAL = 25 * 60


class SessionManager:
    """公司系统会话管理器

    负责登录获取 JSESSIONID，并在后台定时续期。
    线程安全，可在多线程环境中使用。
    """

    def __init__(
        self,
        base_url: str = "http://47.108.166.14:8081",
        username: str = "chenxueqin",
        password: str = "1234",
        refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
    ):
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._refresh_interval = refresh_interval
        self._session: Optional[requests.Session] = None
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._last_login_time: Optional[float] = None

    def login(self) -> bool:
        """登录公司系统，获取 JSESSIONID

        Returns:
            True 登录成功，False 登录失败
        """
        try:
            session = requests.Session()
            resp = session.post(
                f"{self._base_url}/api/doLogin",
                json={
                    "userName": self._username,
                    "password": self._password,
                    "encrypted": False,
                },
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            data = resp.json()
            if data.get("success"):
                with self._lock:
                    self._session = session
                    self._last_login_time = time.time()
                logger.info("公司系统登录成功, JSESSIONID 已刷新")
                return True
            else:
                logger.error("公司系统登录失败: %s", data.get("message"))
                return False
        except Exception as e:
            logger.error("公司系统登录异常: %s", e)
            return False

    def get_session(self) -> Optional[requests.Session]:
        """获取当前已登录的 requests.Session

        Returns:
            带 JSESSIONID cookie 的 Session，未登录时返回 None
        """
        with self._lock:
            return self._session

    def is_active(self) -> bool:
        """检查会话是否有效"""
        with self._lock:
            if self._session is None or self._last_login_time is None:
                return False
            elapsed = time.time() - self._last_login_time
            return elapsed < 30 * 60  # 30 分钟有效

    def _refresh(self):
        """定时刷新回调"""
        if not self._running:
            return
        self.login()
        # 安排下一次刷新
        if self._running:
            self._timer = threading.Timer(self._refresh_interval, self._refresh)
            self._timer.daemon = True
            self._timer.start()

    def start(self):
        """启动后台续期线程

        先立即登录一次，然后每 refresh_interval 秒自动刷新。
        """
        if self._running:
            logger.warning("SessionManager 已在运行")
            return
        self._running = True
        self.login()
        self._timer = threading.Timer(self._refresh_interval, self._refresh)
        self._timer.daemon = True
        self._timer.start()
        logger.info(
            "SessionManager 已启动, 每 %d 秒自动续期", self._refresh_interval
        )

    def stop(self):
        """停止后台续期"""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        logger.info("SessionManager 已停止")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
