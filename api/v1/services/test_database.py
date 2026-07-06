"""
数据库功能测试脚本。

用于验证数据库表的创建、数据持久化、撤销等功能是否正常工作。

运行方式:
    python -m api.v1.services.test_database
"""
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from api.v1.services import Database, get_database, SessionService, MessageService, CheckpointService


def test_database_initialization():
    """测试数据库初始化。"""
    print("\n=== 测试 1: 数据库初始化 ===")
    db = get_database()
    assert db is not None, "数据库实例不应为空"
    print(f"✓ 数据库初始化成功: {db.db_path}")
    
    # 验证表是否存在
    tables = db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    table_names = [t["name"] for t in tables]
    print(f"✓ 已创建的表: {table_names}")
    
    assert "sessions" in table_names, "sessions 表应存在"
    assert "messages" in table_names, "messages 表应存在"
    assert "checkpoints" in table_names, "checkpoints 表应存在"
    print("✓ 所有必需的表都已创建")


def test_session_service():
    """测试会话服务。"""
    print("\n=== 测试 2: 会话服务 ===")
    session_service = SessionService()
    
    # 创建会话
    session = session_service.create_session(
        user_id="test_user",
        session_title="测试会话",
    )
    assert session is not None, "会话创建失败"
    assert "session_id" in session, "会话应包含 session_id"
    print(f"✓ 会话创建成功: {session['session_id']}")
    
    # 获取会话
    retrieved = session_service.get_session(session["session_id"])
    assert retrieved is not None, "会话查询失败"
    assert retrieved["session_title"] == "测试会话"
    print(f"✓ 会话查询成功: {retrieved['session_title']}")
    
    # 列出会话
    sessions = session_service.list_sessions(user_id="test_user")
    assert len(sessions) > 0, "会话列表应包含刚创建的会话"
    print(f"✓ 会话列表查询成功，共 {len(sessions)} 条")
    
    # 更新会话
    updated = session_service.update_session(
        session_id=session["session_id"],
        session_title="更新后的标题",
    )
    assert updated["session_title"] == "更新后的标题"
    print(f"✓ 会话更新成功: {updated['session_title']}")
    
    return session["session_id"]


def test_message_service(session_id):
    """测试消息服务。"""
    print("\n=== 测试 3: 消息服务 ===")
    message_service = MessageService()
    
    # 创建用户消息
    user_msg = message_service.create_message(
        session_id=session_id,
        role="user",
        content="你好，AI助手！",
    )
    assert user_msg is not None, "用户消息创建失败"
    print(f"✓ 用户消息创建成功: {user_msg['message_id']}")
    
    # 创建助手消息
    assistant_msg = message_service.create_message(
        session_id=session_id,
        role="assistant",
        content="你好！有什么可以帮助你的吗？",
        parent_message_id=user_msg["message_id"],
    )
    assert assistant_msg is not None, "助手消息创建失败"
    print(f"✓ 助手消息创建成功: {assistant_msg['message_id']}")
    
    # 获取活跃消息
    messages = message_service.get_active_messages(session_id)
    assert len(messages) == 2, f"应包含 2 条消息，实际 {len(messages)} 条"
    print(f"✓ 活跃消息查询成功，共 {len(messages)} 条")
    
    # 获取单条消息
    retrieved = message_service.get_message(user_msg["message_id"])
    assert retrieved is not None, "消息查询失败"
    print(f"✓ 单条消息查询成功: {retrieved['content'][:20]}...")
    
    return user_msg["message_id"], assistant_msg["message_id"]


def test_checkpoint_service(session_id, user_msg_id):
    """测试检查点服务。"""
    print("\n=== 测试 4: 检查点服务 ===")
    checkpoint_service = CheckpointService()
    
    # 创建检查点
    checkpoint = checkpoint_service.create_checkpoint(
        session_id=session_id,
        state_dump={
            "messages": ["你好", "有什么帮助"],
            "context": {"key": "value"},
        },
        message_id=user_msg_id,
        trigger_type="manual",
        description="测试检查点",
    )
    assert checkpoint is not None, "检查点创建失败"
    assert checkpoint["version"] == 1, "初始版本应为 1"
    print(f"✓ 检查点创建成功: {checkpoint['checkpoint_id']}, 版本: {checkpoint['version']}")
    
    # 获取检查点
    retrieved = checkpoint_service.get_checkpoint(checkpoint["checkpoint_id"])
    assert retrieved is not None, "检查点查询失败"
    assert retrieved["state_dump"]["context"]["key"] == "value"
    print(f"✓ 检查点查询成功，状态数据正确")
    
    # 获取会话检查点列表
    checkpoints = checkpoint_service.get_session_checkpoints(session_id)
    assert len(checkpoints) > 0, "检查点列表应包含刚创建的检查点"
    print(f"✓ 检查点列表查询成功，共 {len(checkpoints)} 条")
    
    # 获取最新检查点
    latest = checkpoint_service.get_latest_checkpoint(session_id)
    assert latest is not None, "最新检查点查询失败"
    print(f"✓ 最新检查点查询成功: {latest['checkpoint_id']}")
    
    return checkpoint["checkpoint_id"]


def test_undo_functionality(session_id, assistant_msg_id):
    """测试撤销功能。"""
    print("\n=== 测试 5: 撤销功能 ===")
    message_service = MessageService()
    
    # 创建更多消息用于撤销测试
    msg3 = message_service.create_message(
        session_id=session_id,
        role="user",
        content="这是第三条消息",
        parent_message_id=assistant_msg_id,
    )
    msg4 = message_service.create_message(
        session_id=session_id,
        role="assistant",
        content="这是第四条消息",
        parent_message_id=msg3["message_id"],
    )
    print(f"✓ 创建测试消息: {msg3['message_id']}, {msg4['message_id']}")
    
    # 执行撤销（撤销到 assistant_msg_id）
    deactivated_count = message_service.deactivate_messages_after(
        session_id=session_id,
        message_id=assistant_msg_id,
    )
    print(f"✓ 撤销操作完成，标记了 {deactivated_count} 条消息为非活跃")
    
    # 验证撤销结果
    active_messages = message_service.get_active_messages(session_id)
    print(f"✓ 撤销后活跃消息数量: {len(active_messages)}")
    
    # 验证被撤销的消息
    msg3_retrieved = message_service.get_message(msg3["message_id"])
    assert msg3_retrieved["is_active"] == 0, "msg3 应该被标记为非活跃"
    print("✓ 消息状态验证成功")


def test_persistence():
    """测试数据持久化。"""
    print("\n=== 测试 6: 数据持久化 ===")
    
    # 获取新实例（模拟重启）
    new_db = get_database()
    
    # 查询会话数量
    session_service = SessionService()
    sessions = session_service.list_sessions(user_id="test_user")
    assert len(sessions) > 0, "重启后应能查询到之前创建的会话"
    print(f"✓ 数据持久化验证成功，会话数量: {len(sessions)}")
    
    # 查询消息数量
    message_service = MessageService()
    messages = message_service.get_active_messages(sessions[0]["session_id"])
    print(f"✓ 数据持久化验证成功，消息数量: {len(messages)}")


def cleanup():
    """清理测试数据。"""
    print("\n=== 清理测试数据 ===")
    session_service = SessionService()
    sessions = session_service.list_sessions(user_id="test_user", is_active=1)
    
    for session in sessions:
        session_service.delete_session(session["session_id"], hard_delete=True)
    
    print(f"✓ 已清理 {len(sessions)} 条测试会话")


def run_tests():
    """运行所有测试。"""
    print("=" * 60)
    print("开始数据库功能测试")
    print("=" * 60)
    
    try:
        # 测试数据库初始化
        test_database_initialization()
        
        # 测试会话服务
        session_id = test_session_service()
        
        # 测试消息服务
        user_msg_id, assistant_msg_id = test_message_service(session_id)
        
        # 测试检查点服务
        checkpoint_id = test_checkpoint_service(session_id, user_msg_id)
        
        # 测试撤销功能
        test_undo_functionality(session_id, assistant_msg_id)
        
        # 测试数据持久化
        test_persistence()
        
        print("\n" + "=" * 60)
        print("所有测试通过！✓")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # 可选：清理测试数据
        # cleanup()
        pass


if __name__ == "__main__":
    run_tests()
