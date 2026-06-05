// "Data sources" panel — every integrated dataset with its live feature count and
// a verification badge bound to the matching claim in status.json (via useStatus).

import { useStatus } from "../hooks/useStatus";
import VerifiedBadge from "./VerifiedBadge";

export interface SourceDef {
  key: string;
  label: string;
  count: number;
  /** verification claim id in status.json, if one covers this dataset. */
  claimId?: string;
  live?: boolean; // shows a pulsing "live" dot (WS-driven feeds)
}

interface Props {
  sources: SourceDef[];
}

export default function DataSourcePanel({ sources }: Props) {
  const { statusOf, claimOf } = useStatus();
  return (
    <div className="datasource-panel glass" data-testid="datasource-panel">
      <div className="dsp-head">Data Sources</div>
      <div className="dsp-list">
        {sources.map((s) => {
          const claim = s.claimId ? claimOf(s.claimId) : undefined;
          return (
            <div className="dsp-row" key={s.key} data-source={s.key} data-count={s.count}>
              <span className="dsp-label">
                {s.live && <i className="dsp-live" />}
                {s.label}
              </span>
              <span className="dsp-count tnum">{s.count}</span>
              {s.claimId ? (
                <VerifiedBadge
                  status={statusOf(s.claimId)}
                  claimId={s.claimId}
                  statement={claim?.statement}
                />
              ) : (
                <span className="vbadge vb-unknown" title="no verification claim">
                  <span className="vbadge-glyph">○</span>
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
