// Small verified/failing/unverified badge bound to a verification claim id.

import type { ClaimStatus } from "../types";

const META: Record<ClaimStatus, { glyph: string; cls: string; word: string }> = {
  verified: { glyph: "✓", cls: "vb-ok", word: "verified" },
  failing: { glyph: "✕", cls: "vb-fail", word: "failing" },
  unverified: { glyph: "○", cls: "vb-unknown", word: "unverified" },
};

interface Props {
  status: ClaimStatus;
  claimId: string;
  statement?: string;
  testid?: string;
  showWord?: boolean;
}

export default function VerifiedBadge({ status, claimId, statement, testid, showWord }: Props) {
  const m = META[status] ?? META.unverified;
  return (
    <span
      className={`vbadge ${m.cls}`}
      data-testid={testid}
      data-claim={claimId}
      data-status={status}
      title={statement ? `${statement} — ${m.word}` : `${claimId}: ${m.word}`}
    >
      <span className="vbadge-glyph">{m.glyph}</span>
      {showWord && <span className="vbadge-word">{m.word}</span>}
    </span>
  );
}
