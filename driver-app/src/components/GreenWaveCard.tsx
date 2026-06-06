// Green-wave card: the headline driver benefit. Shows the SignalAdvice message
// big, a speedometer gauge (current vs target speed) and a seconds-to-green
// countdown. Hidden entirely if the guidance/advice endpoints are unavailable
// AND there's no demo advice (graceful degradation).

import { useStore } from "../store";
import Speedometer from "./Speedometer";
import DotMatrix from "./DotMatrix";

const mps2kmh = (m: number) => m * 3.6;

export default function GreenWaveCard() {
  const advice = useStore((s) => s.advice);
  const lastFix = useStore((s) => s.lastFix);
  const source = useStore((s) => s.guidanceSource);
  const available = useStore((s) => s.guidanceAvailable);

  // Endpoint 404'd and we have nothing to show -> hide the card.
  if (!available && !advice) return null;
  if (!advice) return null;

  const curKmh = lastFix ? mps2kmh(lastFix.speed_mps) : 0;
  const targetKmh =
    advice.target_speed_mps != null ? mps2kmh(advice.target_speed_mps) : undefined;
  const secs = advice.seconds_to_green;
  const conf = advice.confidence;

  return (
    <section className="glass card greenwave">
      <header className="card-head">
        <h2 className="card-title">
          <span className="pulse-dot" /> Green wave
        </h2>
        <span className={`src-badge ${source}`}>{source}</span>
      </header>

      <p className="greenwave-msg" data-testid="greenwave-advice">
        {advice.message}
      </p>

      <div className="greenwave-body">
        <Speedometer speedKmh={curKmh} targetKmh={targetKmh} />

        <div className="greenwave-stats">
          {secs != null && (
            <div className="gw-stat">
              <DotMatrix value={Math.round(secs)} dot={6} gap={3} charGap={8} tone="amber" />
              <span className="gw-cap">sec to green</span>
            </div>
          )}
          {targetKmh != null && (
            <div className="gw-stat">
              <span className="gw-num">{Math.round(targetKmh)}</span>
              <span className="gw-cap">target km/h</span>
            </div>
          )}
          {conf != null && (
            <div className="gw-stat">
              <span className="gw-num">{Math.round(conf * 100)}%</span>
              <span className="gw-cap">confidence</span>
            </div>
          )}
          {advice.junction?.name && (
            <div className="gw-junction">
              next: <strong>{advice.junction.name}</strong>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
