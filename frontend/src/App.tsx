// App shell: wires the WebSocket to the store, hydrates on (re)connect,
// and lays out the map + HUD panel.

import { useEffect } from "react";
import MapView from "./MapView";
import Panel from "./Panel";
import { connectWs, getState } from "./api";
import { useStore } from "./store";

export default function App() {
  useEffect(() => {
    const { applyEvent, setConnected, hydrate, pushLog } = useStore.getState();

    // Initial hydrate before/independent of the socket.
    getState()
      .then((snap) => hydrate(snap))
      .catch(() =>
        pushLog({
          level: "warn",
          message: "Could not reach orchestrator for initial /state.",
          source: "system",
        }),
      );

    const disconnect = connectWs({
      onEvent: (e) => applyEvent(e),
      onOpen: () => {
        setConnected(true);
        // Re-hydrate on every (re)connection so we never show stale state.
        getState()
          .then((snap) => hydrate(snap))
          .catch(() => {});
      },
      onClose: () => {
        setConnected(false);
        pushLog({
          level: "warn",
          message: "WebSocket dropped — reconnecting…",
          source: "system",
        });
      },
    });

    return disconnect;
  }, []);

  return (
    <div className="app">
      <MapView />
      <Panel />
    </div>
  );
}
