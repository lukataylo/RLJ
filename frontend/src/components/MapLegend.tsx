// Map legend — explains every colour/glyph on the operations map. Grouped and
// compact so it never buries the map but always decodes it.

import {
  COURIER_HEX,
  DISRUPTION_CLASS_HEX,
  DRIVER_HEX,
  FACILITY_HEX,
  PRIORITY_HEX,
} from "../lib/palette";

function Dot({ c }: { c: string }) {
  return <i className="ldot" style={{ background: c, color: c }} />;
}

export default function MapLegend() {
  return (
    <div className="map-legend glass" data-testid="legend">
      <div className="legend-group">
        <div className="legend-cap">Priority</div>
        <span style={{ color: PRIORITY_HEX.stat }}><Dot c={PRIORITY_HEX.stat} /> STAT</span>
        <span style={{ color: PRIORITY_HEX.urgent }}><Dot c={PRIORITY_HEX.urgent} /> Urgent</span>
        <span style={{ color: PRIORITY_HEX.routine }}><Dot c={PRIORITY_HEX.routine} /> Routine</span>
      </div>

      <div className="legend-group">
        <div className="legend-cap">Couriers</div>
        <span style={{ color: COURIER_HEX.idle }}><Dot c={COURIER_HEX.idle} /> Idle</span>
        <span style={{ color: COURIER_HEX.enroute }}><Dot c={COURIER_HEX.enroute} /> En route</span>
        <span style={{ color: COURIER_HEX.offline }}><Dot c={COURIER_HEX.offline} /> Offline</span>
        <span style={{ color: DRIVER_HEX }}><Dot c={DRIVER_HEX} /> Driver probe</span>
      </div>

      <div className="legend-group">
        <div className="legend-cap">Congestion</div>
        <span className="legend-ramp">
          <i className="ramp-bar" />
          <em>free</em>
          <em>jam</em>
        </span>
      </div>

      <div className="legend-group">
        <div className="legend-cap">Facilities</div>
        <span style={{ color: FACILITY_HEX.hospital }}><Dot c={FACILITY_HEX.hospital} /> Hospital</span>
        <span style={{ color: FACILITY_HEX.lab }}><Dot c={FACILITY_HEX.lab} /> Lab</span>
        <span style={{ color: FACILITY_HEX.gp }}><Dot c={FACILITY_HEX.gp} /> GP/Clinic</span>
        <span style={{ color: FACILITY_HEX.pharmacy }}><Dot c={FACILITY_HEX.pharmacy} /> Pharmacy</span>
      </div>

      <div className="legend-group">
        <div className="legend-cap">Disruptions</div>
        <span style={{ color: DISRUPTION_CLASS_HEX.bridge }}><Dot c={DISRUPTION_CLASS_HEX.bridge} /> Bridge lift</span>
        <span style={{ color: DISRUPTION_CLASS_HEX.event }}><Dot c={DISRUPTION_CLASS_HEX.event} /> Event zone</span>
        <span style={{ color: DISRUPTION_CLASS_HEX.congestion }}><Dot c={DISRUPTION_CLASS_HEX.congestion} /> Congestion</span>
        <span style={{ color: DISRUPTION_CLASS_HEX.manual }}><Dot c={DISRUPTION_CLASS_HEX.manual} /> Road closure</span>
      </div>

      <div className="legend-group">
        <div className="legend-cap">Signals</div>
        <span style={{ color: "#23f0c7" }}><Dot c="#23f0c7" /> Green wave</span>
        <span style={{ color: "#ff3b5c" }}><Dot c="#ff3b5c" /> Red phase</span>
      </div>
    </div>
  );
}
