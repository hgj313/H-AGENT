"""
SQLite 数据库连接和初始化模块。

提供数据库连接管理、表结构初始化、外键约束开启等功能。
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

# 数据库文件路径
DB_DIR = Path(__file__).parent.parent.parent.parent / "db"
DB_PATH = DB_DIR / "chat.db"


class Database:
    """
    SQLite 数据库管理器。
    
    特性：
    - 单例模式，全局共享连接
    - 自动开启外键约束
    - WAL模式提升并发性能
    - 连接池管理
    
    使用类方法和模块级变量实现单例。
    """
    
    _instance: Optional["Database"] = None
    _lock = threading.Lock()
    _db_path: Optional[Path] = None
    _initialized: bool = False
    
    def __init__(self, db_path: Optional[str] = None) -> None:
        """初始化数据库连接。"""
        # 防止重复初始化
        if Database._initialized:
            return
        
        # 使用类变量存储路径
        Database._db_path = Path(db_path) if db_path else DB_PATH
        Database._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据库
        self._init_db()
        Database._initialized = True
        
        logger.info(f"数据库初始化完成: {Database._db_path}")
    
    def _init_db(self) -> None:
        """初始化数据库表结构和配置。"""
        with self.connect() as conn:
            # 开启外键约束
            conn.execute("PRAGMA foreign_keys = ON")
            
            # 启用WAL模式提升并发性能
            conn.execute("PRAGMA journal_mode = WAL")
            
            # 创建表结构
            self._create_tables(conn)
            self._create_indexes(conn)
            
            conn.commit()
            logger.info("数据库表结构初始化完成")
    
    def _create_tables(self, conn: sqlite3.Connection) -> None:
        """创建数据库表结构。"""
        
        # 创建 checkpoints 表（需要先创建，因为 sessions 有外键依赖）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                message_id TEXT,
                state_dump BLOB,
                create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                version INTEGER DEFAULT 1,
                trigger_type TEXT DEFAULT 'manual',
                description TEXT,
                metadata JSON,
                
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE SET NULL
            )
        """)
        
        # 创建 sessions 表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_title TEXT,
                create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                update_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                last_checkpoint_id TEXT,
                metadata JSON,
                
                FOREIGN KEY (last_checkpoint_id) REFERENCES checkpoints(checkpoint_id) ON DELETE SET NULL
            )
        """)
        
        # 创建 messages 表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                parent_message_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                message_type TEXT DEFAULT 'text',
                create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                model_params JSON,
                metadata JSON,
                
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
                FOREIGN KEY (parent_message_id) REFERENCES messages(message_id) ON DELETE SET NULL
            )
        """)
    
    def _create_indexes(self, conn: sqlite3.Connection) -> None:
        """创建索引优化查询性能。"""
        
        # sessions 表索引
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_user_update 
            ON sessions(user_id, update_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_active 
            ON sessions(is_active)
        """)
        
        # messages 表索引
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_active 
            ON messages(session_id, is_active)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_parent 
            ON messages(parent_message_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_create 
            ON messages(session_id, create_at)
        """)
        
        # checkpoints 表索引
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_checkpoints_session_message 
            ON checkpoints(session_id, message_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_session_version 
            ON checkpoints(session_id, version)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_checkpoints_session_create 
            ON checkpoints(session_id, create_at)
        """)
    
    @property
    def db_path(self) -> Path:
        """获取数据库文件路径。"""
        return Database._db_path or DB_PATH
    
    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """
        获取数据库连接的上下文管理器。
        
        自动处理：
        - 开启外键约束
        - 事务提交/回滚
        - 连接关闭
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # 返回字典格式结果
        
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise
        finally:
            conn.close()
    
    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """
        事务上下文管理器。
        
        自动提交或回滚事务。
        """
        with self.connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"事务执行失败: {e}")
                raise
    
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行SQL语句。"""
        with self.connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            return conn.execute(sql, params)
    
    def execute_many(self, sql: str, params_list: list[tuple]) -> None:
        """批量执行SQL语句。"""
        with self.connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.executemany(sql, params_list)
    
    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
        """查询单条记录。"""
        with self.connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """查询多条记录。"""
        with self.connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def close(self) -> None:
        """关闭数据库连接（单例模式下通常不需要调用）。"""
        Database._instance = None
        Database._initialized = False
        Database._db_path = None


def get_database(db_path: Optional[str] = None) -> Database:
    """
    获取数据库实例的工厂函数（单例模式）。
    
    第一次调用时会创建数据库实例并初始化表结构。
    后续调用直接返回已创建的实例。
    
    Args:
        db_path: 可选的数据库文件路径（仅第一次调用生效）
        
    Returns:
        Database 实例
    """
    with Database._lock:
        if Database._instance is None:
            Database._instance = Database(db_path)
        return Database._instance
