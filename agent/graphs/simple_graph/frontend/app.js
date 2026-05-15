const form = document.getElementById("session-form");
const eventsEl = document.getElementById("events");
const stateEl = document.getElementById("state");
const metaEl = document.getElementById("meta");
const snapshotsEl = document.getElementById("snapshots");

let currentUserId = null;
let currentSessionId = null;
let eventSource = null;

function appendEvent(event) {
  eventsEl.textContent += `${JSON.stringify(event, null, 2)}\n\n`;
  eventsEl.scrollTop = eventsEl.scrollHeight;
}

async function refreshState() {
  if (!currentUserId || !currentSessionId) return;
  const response = await fetch(`/api/sessions/${currentUserId}/${currentSessionId}`);
  const state = await response.json();
  stateEl.textContent = JSON.stringify(state, null, 2);
}

function startEventStream() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/sessions/${currentUserId}/${currentSessionId}/events`);
  eventSource.onmessage = async (message) => {
    const event = JSON.parse(message.data);
    appendEvent(event);
    await refreshState();
  };
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  eventsEl.textContent = "";
  snapshotsEl.innerHTML = "";
  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  payload.a = Number(payload.a);
  payload.b = Number(payload.b);
  payload.multiplier = Number(payload.multiplier);

  const createResp = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const created = await createResp.json();
  currentUserId = created.user_id;
  currentSessionId = created.session_id;
  metaEl.textContent = `user_id=${currentUserId}, session_id=${currentSessionId}`;

  await fetch(`/api/sessions/${currentUserId}/${currentSessionId}/start`, { method: "POST" });
  startEventStream();
  await refreshState();
});

document.getElementById("pause-btn").addEventListener("click", async () => {
  if (!currentUserId || !currentSessionId) return;
  await fetch(`/api/sessions/${currentUserId}/${currentSessionId}/interrupt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "pause", payload: {} }),
  });
});

document.getElementById("resume-btn").addEventListener("click", async () => {
  if (!currentUserId || !currentSessionId) return;
  await fetch(`/api/sessions/${currentUserId}/${currentSessionId}/interrupt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "resume", payload: {} }),
  });
});

document.getElementById("update-btn").addEventListener("click", async () => {
  if (!currentUserId || !currentSessionId) return;
  const goal = window.prompt("请输入新的 goal", "请生成更详细的解释");
  if (!goal) return;
  await fetch(`/api/sessions/${currentUserId}/${currentSessionId}/interrupt`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: "update_inputs",
      payload: { request_updates: { goal } },
    }),
  });
});

document.getElementById("refresh-btn").addEventListener("click", refreshState);

document.getElementById("snapshots-btn").addEventListener("click", async () => {
  if (!currentUserId || !currentSessionId) return;
  const response = await fetch(`/api/sessions/${currentUserId}/${currentSessionId}/snapshots`);
  const result = await response.json();
  snapshotsEl.innerHTML = "";
  for (const snapshotId of result.snapshots) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.textContent = `回滚 ${snapshotId.slice(0, 8)}`;
    button.onclick = async () => {
      await fetch(`/api/sessions/${currentUserId}/${currentSessionId}/rollback/${snapshotId}`, {
        method: "POST",
      });
      await refreshState();
    };
    item.appendChild(button);
    snapshotsEl.appendChild(item);
  }
});
