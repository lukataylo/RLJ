// Toggleable layer control for the operations map. Each row is a checkbox with a
// live feature count and a colour swatch, so nothing on the map is a mystery.

export interface LayerDef {
  key: string;
  label: string;
  count: number;
  color: string;
  testid?: string;
  /** false when the underlying dataset is absent — row is shown disabled. */
  present: boolean;
}

interface Props {
  layers: LayerDef[];
  vis: Record<string, boolean>;
  onToggle: (key: string) => void;
}

export default function LayersPanel({ layers, vis, onToggle }: Props) {
  return (
    <div className="layers-panel glass" data-testid="layers-panel">
      <div className="lp-head">Layers</div>
      <div className="lp-list">
        {layers.map((l) => {
          const on = !!vis[l.key] && l.present;
          return (
            <label
              key={l.key}
              className={`lp-row ${on ? "on" : ""} ${l.present ? "" : "absent"}`}
              data-testid={l.testid}
              data-on={on ? "true" : "false"}
              data-count={l.count}
            >
              <input
                type="checkbox"
                checked={on}
                disabled={!l.present}
                onChange={() => onToggle(l.key)}
              />
              <span className="lp-swatch" style={{ background: l.color }} />
              <span className="lp-label">{l.label}</span>
              <span className="lp-count tnum">{l.present ? l.count : "—"}</span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
