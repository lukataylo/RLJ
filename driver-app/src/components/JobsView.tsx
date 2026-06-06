// Jobs tab: upcoming (route order) and past deliveries. Bold, minimal rows —
// a priority stripe, the destination as the headline, origin + time beneath.

import { useState } from "react";
import { PRIORITY_COLOR, STATUS_COLOR, STATUS_LABEL, etaMinutes, fmtTime } from "../lib/format";
import { selectPast, selectUpcoming, useStore } from "../store";
import type { DeliveryJob } from "../types";
import { IconSnow } from "./icons";

function JobRow({ job, past }: { job: DeliveryJob; past?: boolean }) {
  const due = job.time_window?.due_by;
  const when = past ? fmtTime(job.created_at) : due ? etaMinutes(due) || fmtTime(due) : "";
  return (
    <div className="jr">
      <span className="jr-bar" style={{ background: PRIORITY_COLOR[job.priority] }} />
      <div className="jr-body">
        <span className="jr-to">{job.destination.name ?? "Dropoff"}</span>
        <span className="jr-from">{job.origin.name ?? "Pickup"}</span>
      </div>
      <div className="jr-side">
        {when ? <span className="jr-when tnum">{when}</span> : null}
        <span className="jr-status" style={{ color: STATUS_COLOR[job.status] }}>
          {job.cold_chain && <IconSnow size={13} />} {STATUS_LABEL[job.status]}
        </span>
      </div>
    </div>
  );
}

export default function JobsView() {
  const upcoming = useStore(selectUpcoming);
  const past = useStore(selectPast);
  const [tab, setTab] = useState<"upcoming" | "past">("upcoming");
  const list = tab === "upcoming" ? upcoming : past;

  return (
    <section className="glass card jobs-view">
      <div className="seg">
        <button type="button" className={`seg-btn ${tab === "upcoming" ? "on" : ""}`} onClick={() => setTab("upcoming")}>
          Upcoming <b>{upcoming.length}</b>
        </button>
        <button type="button" className={`seg-btn ${tab === "past" ? "on" : ""}`} onClick={() => setTab("past")}>
          Past <b>{past.length}</b>
        </button>
      </div>

      <div className="jobs-list">
        {list.length === 0 ? (
          <p className="ad-empty">{tab === "upcoming" ? "Nothing upcoming" : "No history yet"}</p>
        ) : (
          list.map((j) => <JobRow key={j.id} job={j} past={tab === "past"} />)
        )}
      </div>
    </section>
  );
}
