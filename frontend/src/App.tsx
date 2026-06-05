// App shell: wires the WebSocket to the store, hydrates on (re)connect, and lays
// out the command-center grid (TopBar / FleetRail / Map+KPIs / Ops rail).

import { useEffect, useState } from "react";
import MapView from "./components/MapView";
import TopBar from "./components/TopBar";
import FleetRail from "./components/FleetRail";
import KpiCards from "./components/KpiCards";
import DemoControls from "./components/DemoControls";
import AgentLog from "./components/AgentLog";
import VerificationPanel from "./components/VerificationPanel";
import BottomStrip from "./components/BottomStrip";
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
    <div className="app">
      <TopBar status={status} onOpenVerification={() => setVerifyOpen(true)} />

      <div className="app-body">
        <FleetRail />

        <main className="main">
          <MapView />
          <div className="main-overlay-top">
            <KpiCards status={status} />
          </div>
          <div className="main-overlay-bottom">
            <BottomStrip />
          </div>
        </main>

        <aside className="ops-rail">
          <DemoControls />
          <AgentLog />
        </aside>
      </div>

      <VerificationPanel status={status} open={verifyOpen} onClose={() => setVerifyOpen(false)} />
    </div>
  );
}
