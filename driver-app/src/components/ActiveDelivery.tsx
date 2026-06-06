// Active delivery + turn-by-turn. Bold, minimal, icon-driven: a big maneuver
// banner while navigating, the destination as the hero, one clear primary
// action. Maneuver tracking + speech is driven from App.tsx.

import { postDisruption } from "../api";
import { distancePhrase } from "../lib/geo";
import { PRIORITY_COLOR, PRIORITY_LABEL, STATUS_COLOR, STATUS_LABEL, etaMinutes } from "../lib/format";
import { selectActiveJob, selectActiveRoute, useStore } from "../store";
import { IconAlert, IconNavigate, IconPin, IconSnow, IconStop, ManeuverIcon } from "./icons";

export default function ActiveDelivery() {
  const job = useStore(selectActiveJob);
  const route = useStore(selectActiveRoute);
  const navigating = useStore((s) => s.navigating);
  const maneuver = useStore((s) => s.maneuver);
  const maneuverDist = useStore((s) => s.maneuverDist);
  const lastFix = useStore((s) => s.lastFix);
  const setNavigating = useStore((s) => s.setNavigating);
  const setSharing = useStore((s) => s.setSharing);

  if (!job) {
    return (
      <section className="glass card ad-card ad-card--empty">
        <IconPin size={22} />
        <span>No active delivery</span>
      </section>
    );
  }

  const lastEta = route?.stops?.length ? route.stops[route.stops.length - 1].eta : undefined;
  const eta = etaMinutes(lastEta ?? job.time_window?.due_by);

  const start = () => {
    setSharing(true);
    setNavigating(true);
  };
  const stop = () => {
    setNavigating(false);
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  };
  const report = async () => {
    const here = lastFix ?? { lat: 51.5033, lng: -0.1195 };
    await postDisruption({ kind: "road_closure", source: "manual", geometry: [{ lat: here.lat, lng: here.lng }] });
    if ("speechSynthesis" in window)
      window.speechSynthesis.speak(new SpeechSynthesisUtterance("Blockage reported. Re-planning."));
  };

  return (
    <section className="glass card ad-card">
      {navigating && maneuver && (
        <div className="mb">
          <span className="mb-ico"><ManeuverIcon modifier={maneuver.modifier} type={maneuver.type} size={34} /></span>
          <div className="mb-txt">
            <span className="mb-dist">{distancePhrase(maneuverDist)}</span>
            <strong className="mb-instr">{maneuver.instruction}</strong>
          </div>
        </div>
      )}

      <div className="ad-head">
        <span className="pill" style={{ color: PRIORITY_COLOR[job.priority], borderColor: PRIORITY_COLOR[job.priority] }}>
          {PRIORITY_LABEL[job.priority]}
        </span>
        <span className="pill ghost" style={{ color: STATUS_COLOR[job.status] }}>
          {STATUS_LABEL[job.status]}
        </span>
        {eta && <span className="ad-eta tnum">{eta}</span>}
      </div>

      <div className="ad-hero">
        <span className="ad-from">{job.origin.name ?? "Pickup"}</span>
        <span className="ad-to">
          <IconPin size={18} />
          {job.destination.name ?? "Dropoff"}
        </span>
        {job.cold_chain && <span className="ad-cold"><IconSnow size={14} /> Cold chain</span>}
      </div>

      <div className="ad-actions">
        {navigating ? (
          <button type="button" className="btn btn-stop" onClick={stop}>
            <IconStop size={20} /> End
          </button>
        ) : (
          <button type="button" className="btn btn-go" onClick={start}>
            <IconNavigate size={20} /> Start navigation
          </button>
        )}
        <button type="button" className="btn btn-alert" onClick={report} aria-label="Report blockage">
          <IconAlert size={20} />
        </button>
      </div>
    </section>
  );
}
