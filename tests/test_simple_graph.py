import tempfile
import threading
import time

import pytest
from fastapi.testclient import TestClient

from agent.graphs.simple_graph.api.app import app
from agent.graphs.simple_graph.demo.graph_factory import build_demo_graph
from agent.graphs.simple_graph.executor import GraphExecutor
from agent.graphs.simple_graph.models import EdgeDefinition, InterruptAction
from agent.graphs.simple_graph.runtime.interrupts import InterruptCommand, InterruptController
from agent.graphs.simple_graph.service import GraphService
from agent.graphs.simple_graph.storage.file_store import FileSystemGraphStore
from agent.graphs.simple_graph.validator import GraphValidationError, validate_graph_definition


def test_validate_graph_definition_detects_cycle():
    definition = build_demo_graph()
    definition.edges.append(EdgeDefinition(source="reason_about_result", target="collect_input"))
    definition.nodes[0].depends_on.append("reason_about_result")

    with pytest.raises(GraphValidationError):
        validate_graph_definition(definition)


def test_executor_persists_and_recovers_state():
    with tempfile.TemporaryDirectory() as temp_dir:
        store = FileSystemGraphStore(root_dir=temp_dir)
        executor = GraphExecutor(store=store)
        state = executor.create_state(
            user_id="user-a",
            session_id="session-1",
            definition=build_demo_graph(),
            request_payload={"a": 1, "b": 2, "multiplier": 3, "goal": "解释"},
        )
        final_state = executor.execute(state, InterruptController())
        recovered = executor.load_state("user-a", "session-1")

        assert final_state.status.value == "completed"
        assert recovered.graph_context["sum_result"] == 3
        assert recovered.graph_context["product_result"] == 9
        assert recovered.node_records["reason_about_result"].stream_chunks
        assert executor.list_snapshots("user-a", "session-1")


def test_cross_user_access_is_blocked():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = GraphService(root_dir=temp_dir)
        created = service.create_session(
            "user-a",
            {"a": 1, "b": 2, "multiplier": 3, "goal": "test"},
        )

        with pytest.raises(PermissionError):
            service.executor.load_state("user-a", created["session_id"], requester_user_id="user-b")


def test_interrupt_pause_resume_and_update_inputs():
    with tempfile.TemporaryDirectory() as temp_dir:
        service = GraphService(root_dir=temp_dir)
        created = service.create_session(
            "user-a",
            {"a": 2, "b": 3, "multiplier": 4, "goal": "初始目标"},
        )
        session_id = created["session_id"]
        state = service.executor.load_state("user-a", session_id, requester_user_id="user-a")
        runtime = service.registry.get_or_create("user-a", session_id)

        thread = threading.Thread(
            target=service.executor.execute,
            args=(state, runtime.controller),
            daemon=True,
        )
        thread.start()
        time.sleep(0.05)
        runtime.controller.submit(InterruptCommand(action=InterruptAction.PAUSE))
        time.sleep(0.05)
        runtime.controller.submit(
            InterruptCommand(
                action=InterruptAction.UPDATE_INPUTS,
                payload={"request_updates": {"goal": "已更新目标"}},
            )
        )
        time.sleep(0.05)
        runtime.controller.submit(InterruptCommand(action=InterruptAction.RESUME))
        thread.join(timeout=5)

        final_state = service.get_state("user-a", session_id)
        assert final_state["graph_context"]["request"]["goal"] == "已更新目标"
        assert final_state["status"] == "completed"


def test_fastapi_end_to_end_flow():
    with tempfile.TemporaryDirectory() as temp_dir:
        app.state.graph_service = GraphService(root_dir=temp_dir)
        client = TestClient(app)

        create_resp = client.post(
            "/api/sessions",
            json={"user_id": "user-x", "a": 5, "b": 6, "multiplier": 2, "goal": "说明"},
        )
        assert create_resp.status_code == 200
        created = create_resp.json()

        start_resp = client.post(f"/api/sessions/{created['user_id']}/{created['session_id']}/start")
        assert start_resp.status_code == 200

        for _ in range(50):
            state_resp = client.get(f"/api/sessions/{created['user_id']}/{created['session_id']}")
            state = state_resp.json()
            if state["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)

        assert state["status"] == "completed"
        replay_resp = client.get(f"/api/sessions/{created['user_id']}/{created['session_id']}/replay")
        assert replay_resp.status_code == 200
        assert replay_resp.json()["events"]
