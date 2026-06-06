// Contribution / gamification card: pings sent, couriers helped, points, and a
// "you made London faster" hero number. Local ping count is the source of truth
// for pings; couriers_helped/points come from guidance.contribution + driver.

import { useStore } from "../store";
import DotMatrix from "./DotMatrix";

export default function ContributionStats() {
  const pings = useStore((s) => s.pings);
  const guidance = useStore((s) => s.guidance);
  const driver = useStore((s) => s.driver);

  const couriersHelped = guidance?.contribution?.couriers_helped ?? 0;
  // Points: prefer the server's gamified score; fall back to a local estimate
  // so the number still climbs in demo mode (10 pts / ping + 25 / courier).
  const serverPoints = driver?.points ?? 0;
  const points = serverPoints || pings * 10 + couriersHelped * 25;

  // Rough "seconds saved for London" hero — illustrative gamification metric.
  const secondsSaved = couriersHelped * 90 + pings * 3;
  const minutesSaved = Math.max(0, Math.round(secondsSaved / 60));

  return (
    <section className="glass card contribution">
      <header className="card-head">
        <h2 className="card-title">
          <span className="pulse-dot orange" /> Your impact
        </h2>
      </header>

      <div className="hero-impact">
        <span className="hero-dm">
          <DotMatrix value={minutesSaved} dot={8} gap={4} charGap={11} tone="amber" />
          <span className="hero-unit">min</span>
        </span>
        <span className="hero-cap">you made London faster</span>
      </div>

      <div className="stat-grid">
        <div className="stat-cell" data-testid="contribution-pings">
          <DotMatrix value={pings} dot={4} gap={2} charGap={5} tone="white" />
          <span className="stat-cap">pings sent</span>
        </div>
        <div className="stat-cell">
          <DotMatrix value={couriersHelped} dot={4} gap={2} charGap={5} tone="white" />
          <span className="stat-cap">couriers helped</span>
        </div>
        <div className="stat-cell">
          <DotMatrix value={points} dot={4} gap={2} charGap={5} tone="red" />
          <span className="stat-cap">points</span>
        </div>
      </div>
    </section>
  );
}
