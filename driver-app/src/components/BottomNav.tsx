// Bottom tab bar with a central amber mic FAB (the voice trigger). Two flanking
// tabs switch the main view: Drive (live map + green wave) and Impact (stats).

export type Tab = "drive" | "impact";

export default function BottomNav({
  tab,
  onTab,
  onVoice,
}: {
  tab: Tab;
  onTab: (t: Tab) => void;
  onVoice: () => void;
}) {
  return (
    <nav className="bottom-nav" aria-label="Primary">
      <button
        type="button"
        className={`bn-tab ${tab === "drive" ? "on" : ""}`}
        data-testid="tab-drive"
        aria-current={tab === "drive"}
        onClick={() => onTab("drive")}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m9 4 6 2 6-2v14l-6 2-6-2-6 2V6l6-2Zm0 0v14m6-12v14" strokeLinejoin="round" />
        </svg>
        <span>Drive</span>
      </button>

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

      <button
        type="button"
        className={`bn-tab ${tab === "impact" ? "on" : ""}`}
        data-testid="tab-impact"
        aria-current={tab === "impact"}
        onClick={() => onTab("impact")}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" strokeLinecap="round" />
        </svg>
        <span>Impact</span>
      </button>
    </nav>
  );
}
