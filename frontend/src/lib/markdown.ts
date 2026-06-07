// Minimal, safe Markdown → HTML for chat answers. No external dependency — keeps the
// bundle lean and works offline on the DGX box. The strategy is XSS-safe by construction:
// every character is HTML-escaped FIRST, then a small, fixed subset of Markdown is
// re-introduced as known-good tags. Links are the only place a URL is emitted, and the
// href is restricted to http/https/mailto. Anything outside the subset renders as plain
// (escaped) text — so a model that emits raw HTML or odd syntax can never inject markup.

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeHref(url: string): string | null {
  const u = url.trim();
  if (/^(https?:|mailto:)/i.test(u)) return u;
  return null;
}

// Inline: code spans first (so their contents are not further formatted), then links,
// bold, italic. Operates on already-escaped text.
function inline(escaped: string): string {
  // `code`
  let out = escaped.replace(/`([^`]+)`/g, (_m, c) => `<code>${c}</code>`);
  // [text](url)
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text, url) => {
    const href = safeHref(url);
    return href
      ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`
      : text;
  });
  // **bold**  (before *italic*)
  out = out.replace(/\*\*([^*]+)\*\*/g, (_m, c) => `<strong>${c}</strong>`);
  out = out.replace(/__([^_]+)__/g, (_m, c) => `<strong>${c}</strong>`);
  // *italic* / _italic_
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, (_m, pre, c) => `${pre}<em>${c}</em>`);
  out = out.replace(/(^|[^_])_([^_\n]+)_/g, (_m, pre, c) => `${pre}<em>${c}</em>`);
  return out;
}

/** Render a safe subset of Markdown (headings, bold/italic, code, links, bullet and
 * numbered lists, fenced code blocks, paragraphs/line breaks) to sanitized HTML. */
export function renderMarkdown(src: string): string {
  if (!src) return "";
  const escaped = escapeHtml(src);
  const lines = escaped.split(/\r?\n/);
  const html: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let inCode = false;
  const codeBuf: string[] = [];

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  };

  for (const raw of lines) {
    const line = raw;
    // Fenced code block toggle (``` ... ```)
    if (/^\s*```/.test(line)) {
      if (inCode) {
        html.push(`<pre><code>${codeBuf.join("\n")}</code></pre>`);
        codeBuf.length = 0;
        inCode = false;
      } else {
        closeList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeBuf.push(line);
      continue;
    }
    if (!line.trim()) {
      closeList();
      continue;
    }
    // Headings (#, ##, ### …) → h4..h6 so they sit sensibly inside the card.
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      closeList();
      const level = Math.min(6, Math.max(4, h[1].length + 3));
      html.push(`<h${level}>${inline(h[2])}</h${level}>`);
      continue;
    }
    // Bullet list item
    const ul = /^\s*[-*+]\s+(.*)$/.exec(line);
    if (ul) {
      if (listType !== "ul") {
        closeList();
        html.push("<ul>");
        listType = "ul";
      }
      html.push(`<li>${inline(ul[1])}</li>`);
      continue;
    }
    // Numbered list item
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (ol) {
      if (listType !== "ol") {
        closeList();
        html.push("<ol>");
        listType = "ol";
      }
      html.push(`<li>${inline(ol[1])}</li>`);
      continue;
    }
    // Paragraph
    closeList();
    html.push(`<p>${inline(line)}</p>`);
  }
  if (inCode && codeBuf.length) html.push(`<pre><code>${codeBuf.join("\n")}</code></pre>`);
  closeList();
  return html.join("");
}
