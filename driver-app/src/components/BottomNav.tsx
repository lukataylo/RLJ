// Bottom tab bar with a central amber mic FAB (the voice trigger). Two flanking
// tabs switch the main view: Drive (live map + green wave) and Impact (stats).

export type Tab = "drive" | "jobs" | "impact";

export default function BottomNav({
  tab,
  onTab,
  onVoice,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  onVoice: () => void;
}) {
  const Tab = ({ id, label, d, testid }: { id: Tab; label: string; d: string; testid: string }) => (
    <button
      type="button"
      className={`bn-tab ${tab === id ? "on" : ""}`}
      data-testid={testid}
      aria-current={tab === id}
      onClick={() => onTab(id)}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d={d} strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <span>{label}</span>
    </button>
  );

  return (
    <nav className="bottom-nav" aria-label="Primary">
      <div className="bn-side">
        <Tab id="drive" label="Drive" testid="tab-drive" d="m9 4 6 2 6-2v14l-6 2-6-2-6 2V6l6-2Zm0 0v14m6-12v14" />
        <Tab id="jobs" label="Jobs" testid="tab-jobs" d="M8 6h11M8 12h11M8 18h11M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
      </div>

      <button
        type="button"
        className="bn-fab"
        data-testid="tab-voice"
        aria-label="Talk to PulseGo"
        onClick={onVoice}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
        </svg>
        <span className="bn-fab-label">Voice</span>
      </button>

      <div className="bn-side">
        <Tab id="impact" label="Impact" testid="tab-impact" d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
      </div>
    </nav>
  );
}
