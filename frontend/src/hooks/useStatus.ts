// Polls /status.json (written by verification/run.py) and exposes the report plus
// a convenient lookup-by-claim-id. Degrades gracefully if the file is absent.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ClaimStatus, VerificationClaim, VerificationReport } from "../types";

const POLL_MS = 10_000;

export interface UseStatus {
  report: VerificationReport | null;
  /** Status for a claim id, or "unverified" if unknown / file missing. */
  statusOf: (claimId: string) => ClaimStatus;
  /** Full claim record by id, if present. */
  claimOf: (claimId: string) => VerificationClaim | undefined;
  loaded: boolean;
}

export function useStatus(): UseStatus {
  const [report, setReport] = useState<VerificationReport | null>(null);
  const [loaded, setLoaded] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`/status.json?t=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) return;
      const ct = res.headers.get("content-type") ?? "";
      if (!ct.includes("json")) return; // dev server may return index.html on 404
      const data = (await res.json()) as VerificationReport;
      if (data && Array.isArray(data.claims)) {
        setReport(data);
        setLoaded(true);
      }
    } catch {
      // No verification artifact yet — stay graceful.
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    timer.current = setInterval(fetchStatus, POLL_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [fetchStatus]);

  const index = useMemo(() => {
    const m = new Map<string, VerificationClaim>();
    for (const c of report?.claims ?? []) m.set(c.id, c);
    return m;
  }, [report]);

  const statusOf = useCallback(
    (id: string): ClaimStatus => index.get(id)?.status ?? "unverified",
    [index],
  );
  const claimOf = useCallback((id: string) => index.get(id), [index]);

  return { report, statusOf, claimOf, loaded };
}
