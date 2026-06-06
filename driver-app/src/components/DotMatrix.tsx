// DotMatrix — renders a short numeric string (digits, ":", "-", "–", "%", " ")
// as a clean 3×5 dot-matrix display. The PulseGo display language: lit dots glow,
// unlit dots sit faint in the same grid. Used for the hero/stat numerals.

const GLYPHS: Record<string, string[]> = {
  "0": ["111", "101", "101", "101", "111"],
  "1": ["010", "110", "010", "010", "111"],
  "2": ["111", "001", "111", "100", "111"],
  "3": ["111", "001", "111", "001", "111"],
  "4": ["101", "101", "111", "001", "001"],
  "5": ["111", "100", "111", "001", "111"],
  "6": ["111", "100", "111", "101", "111"],
  "7": ["111", "001", "010", "010", "010"],
  "8": ["111", "101", "111", "101", "111"],
  "9": ["111", "101", "111", "001", "111"],
  ":": ["0", "1", "0", "1", "0"],
  ".": ["0", "0", "0", "0", "1"],
  "-": ["00000", "00000", "01110", "00000", "00000"],
  "–": ["00000", "00000", "01110", "00000", "00000"],
  "%": ["10001", "00010", "00100", "01000", "10001"],
  " ": ["00", "00", "00", "00", "00"],
};

export default function DotMatrix({
  value,
  dot = 5,
  gap = 3,
  charGap = 7,
  className = "",
  tone = "white",
}: {
  value: string | number;
  /** dot diameter in px */
  dot?: number;
  /** gap between dots in px */
  gap?: number;
  /** gap between glyphs in px */
  charGap?: number;
  className?: string;
  /** lit-dot colour theme */
  tone?: "white" | "amber" | "red";
}) {
  const chars = String(value).split("");

  return (
    <span
      className={`dm ${className}`}
      data-tone={tone}
      style={{ gap: `${charGap}px` }}
      aria-label={String(value)}
      role="img"
    >
      {chars.map((ch, ci) => {
        const rows = GLYPHS[ch] ?? GLYPHS[" "];
        const cols = rows[0].length;
        return (
          <span
            key={ci}
            className="dm-char"
            style={{
              gridTemplateColumns: `repeat(${cols}, ${dot}px)`,
              gridAutoRows: `${dot}px`,
              gap: `${gap}px`,
            }}
          >
            {rows.flatMap((row, ri) =>
              row.split("").map((bit, bi) => (
                <span
                  key={`${ri}-${bi}`}
                  className={`dm-dot ${bit === "1" ? "on" : ""}`}
                />
              )),
            )}
          </span>
        );
      })}
    </span>
  );
}
