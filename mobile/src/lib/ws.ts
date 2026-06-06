// WebSocket client for live updates. Connects to <api>/ws, hydrates from the
// initial `state` event, then applies incremental events. Reconnects with
// exponential backoff (1→2→4→8s cap). Clients only READ the socket; all commands
// go through REST (see api.ts), so this is dispatch-only.

import { wsUrl } from "./config";
import { useStore } from "./store";

let socket: WebSocket | null = null;
let backoff = 1000;
let stopped = false;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function handle(msg: any) {
  const store = useStore.getState();
  switch (msg?.type) {
    case "state":
      store.hydrateSnapshot(msg.payload);
      break;
    case "job_created":
      if (msg.payload) store.upsertJob(msg.payload);
      break;
    case "plan_updated":
      if (msg.payload) store.setPlan(msg.payload);
      break;
    // disruption / notification / agent_log are surfaced elsewhere; no-op here
    default:
      break;
  }
}

export function connectWs() {
  stopped = false;
  open();
}

function open() {
  if (stopped) return;
  try {
    socket = new WebSocket(wsUrl());
  } catch {
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    backoff = 1000;
    useStore.getState().setConnected(true);
  };
  socket.onmessage = (e) => {
    try {
      handle(JSON.parse(e.data as string));
    } catch {
      // ignore malformed frames
    }
  };
  socket.onerror = () => {
    // onclose will follow and trigger reconnect
  };
  socket.onclose = () => {
    useStore.getState().setConnected(false);
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  if (stopped) return;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(() => {
    backoff = Math.min(backoff * 2, 8000);
    open();
  }, backoff);
}

export function disconnectWs() {
  stopped = true;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
  if (socket) {
    socket.onclose = null;
    socket.close();
    socket = null;
  }
  useStore.getState().setConnected(false);
}
