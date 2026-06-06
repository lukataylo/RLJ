// App shell: wires the WebSocket to the store, hydrates on (re)connect, and lays
// out the "Direction C" command center — a full-screen map with glass panels
// floating over it (provenance pill, nav, efficiency, inspector, NEMOCLAW log,
// priority ticket, verification drawer).

import { useEffect, useState } from "react";
import MapView from "./components/MapView";
import TopBar from "./components/TopBar";
import EfficiencyPanel from "./components/EfficiencyPanel";
import Inspector from "./components/Inspector";
import AgentLog from "./components/AgentLog";
import PriorityTicket from "./components/PriorityTicket";
import VerificationPanel from "./components/VerificationPanel";
import { connectWs, getState } from "./api";
import { useStore } from "./store";
import { useStatus } from "./hooks/useStatus";

export default function App() {
  const status = useStatus();
  const [verifyOpen, setVerifyOpen] = useState(false);

  useEffect(() => {
    const { applyEvent, setConnected, hydrate, pushLog } = useStore.getState();

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
    <div className="cc">
      <MapView />

      <TopBar status={status} onOpenVerification={() => setVerifyOpen(true)} />

      <div className="right-stack">
        <EfficiencyPanel />
        <Inspector />
      </div>

      <AgentLog />
      <PriorityTicket />

      <VerificationPanel status={status} open={verifyOpen} onClose={() => setVerifyOpen(false)} />
    </div>
  );
}
