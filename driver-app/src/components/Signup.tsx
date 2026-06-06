// Onboarding: name + vehicle type + explicit consent toggle -> POST /drivers.
// On success (or graceful offline fallback) the driver id is stored locally and
// the app advances to the live map.

import { useState } from "react";
import type { Driver, VehicleType } from "../types";
import { postDriver } from "../api";
import { useStore } from "../store";

const VEHICLES: { id: VehicleType; label: string; icon: string }[] = [
  { id: "bike", label: "Bike", icon: "🚲" },
  { id: "scooter", label: "Scooter", icon: "🛵" },
  { id: "car", label: "Car", icon: "🚗" },
  { id: "van", label: "Van", icon: "🚐" },
];

function localId() {
  return `drv_${Math.random().toString(36).slice(2, 8)}${Date.now()
    .toString(36)
    .slice(-4)}`;
}

export default function Signup() {
  const setDriver = useStore((s) => s.setDriver);
  const setOnline = useStore((s) => s.setOrchestratorOnline);

  const [name, setName] = useState("");
  const [vehicle, setVehicle] = useState<VehicleType>("bike");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!consent || busy) return;
    setBusy(true);
    setNote(null);

    const payload: Partial<Driver> = {
      name: name.trim() || undefined,
      vehicle_type: vehicle,
      consent: true,
    };

    const res = await postDriver(payload);
    if (res.ok && res.data) {
      setOnline(true);
      setDriver(res.data);
    } else {
      // Graceful fallback — no orchestrator. Mint a local identity so the
      // demo (heat map, green-wave, simulated pings) still works end-to-end.
      setOnline(false);
      setNote(
        res.status === 0
          ? "Orchestrator offline — running in demo mode."
          : `Signup endpoint returned ${res.status} — demo mode.`,
      );
      setDriver({
        id: localId(),
        name: payload.name,
        vehicle_type: vehicle,
        consent: true,
        joined_at: new Date().toISOString(),
        points: 0,
      });
    }
    setBusy(false);
  }

  return (
    <div className="signup-screen">
      <div className="signup-hero">
        <div className="brand-mark">
          <span className="brand-ring" />
          PulseGo <span className="brand-accent">DRIVER</span>
        </div>
        <h1 className="signup-title">Share the road, ride the green wave</h1>
        <p className="signup-sub">
          Your anonymous GPS feeds London&apos;s live congestion map. In return you
          get signal-aware <span className="hl">green-wave</span> routing — fewer
          red lights, faster drops.
        </p>
      </div>

      <form className="glass signup-card" data-testid="signup-form" onSubmit={submit}>
        <label className="field">
          <span className="field-label">Name <em>(optional)</em></span>
          <input
            className="text-input"
            type="text"
            value={name}
            placeholder="e.g. Sam"
            onChange={(e) => setName(e.target.value)}
            autoComplete="given-name"
          />
        </label>

        <div className="field">
          <span className="field-label">Vehicle</span>
          <div className="vehicle-grid">
            {VEHICLES.map((v) => (
              <button
                key={v.id}
                type="button"
                className={`vehicle-chip ${vehicle === v.id ? "active" : ""}`}
                aria-pressed={vehicle === v.id}
                onClick={() => setVehicle(v.id)}
              >
                <span className="vehicle-icon">{v.icon}</span>
                {v.label}
              </button>
            ))}
          </div>
        </div>

        <button
          type="button"
          className={`consent-toggle ${consent ? "on" : ""}`}
          data-testid="btn-consent"
          role="switch"
          aria-checked={consent}
          onClick={() => setConsent((c) => !c)}
        >
          <span className="consent-knob" />
          <span className="consent-text">
            <strong>Share my location</strong>
            <small>
              I consent to sharing anonymised GPS to improve routing for everyone.
            </small>
          </span>
        </button>

        <button
          type="submit"
          className="primary-btn"
          disabled={!consent || busy}
        >
          {busy ? "Joining…" : "Start driving"}
        </button>

        {!consent && (
          <p className="consent-hint">Consent is required to join the flywheel.</p>
        )}
        {note && <p className="form-note">{note}</p>}
      </form>
    </div>
  );
}
