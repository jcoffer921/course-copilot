// Minimal Markdown -> DOM renderer for model-generated chat text. Every
// node is built via createElement/textContent, never innerHTML, so this
// stays safe even though the source text is untrusted model output —
// there is no HTML string for a crafted response to break out of.

const SAFE_LINK_SCHEMES = new Set(["http:", "https:", "mailto:"]);

function safeHref(url) {
  try {
    const parsed = new URL(url, window.location.href);
    return SAFE_LINK_SCHEMES.has(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

// Ordered so code spans are matched before bold/italic (their contents are
// never re-parsed), and **bold**/__bold__ before single */_ so "**x**" isn't
// read as two adjacent italics.
const INLINE_PATTERN = /`([^`]+)`|\*\*(.+?)\*\*|__(.+?)__|\*([^*]+?)\*|_([^_]+?)_|\[([^\]]+?)\]\((\S+?)\)/;

function parseInline(text, depth = 0) {
  const nodes = [];
  let remaining = text;
  while (remaining) {
    const match = depth < 6 ? INLINE_PATTERN.exec(remaining) : null;
    if (!match) { nodes.push(document.createTextNode(remaining)); break; }
    if (match.index > 0) nodes.push(document.createTextNode(remaining.slice(0, match.index)));

    if (match[1] !== undefined) {
      const code = document.createElement("code"); code.textContent = match[1]; nodes.push(code);
    } else if (match[2] !== undefined || match[3] !== undefined) {
      const strong = document.createElement("strong"); strong.append(...parseInline(match[2] ?? match[3], depth + 1)); nodes.push(strong);
    } else if (match[4] !== undefined || match[5] !== undefined) {
      const em = document.createElement("em"); em.append(...parseInline(match[4] ?? match[5], depth + 1)); nodes.push(em);
    } else if (match[6] !== undefined) {
      const href = safeHref(match[7]);
      if (href) {
        const a = document.createElement("a"); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer ugc";
        a.append(...parseInline(match[6], depth + 1)); nodes.push(a);
      } else {
        nodes.push(document.createTextNode(match[0]));
      }
    }
    remaining = remaining.slice(match.index + match[0].length);
  }
  return nodes;
}

function appendInlineWithBreaks(el, lines) {
  lines.forEach((line, index) => {
    if (index > 0) el.append(document.createElement("br"));
    el.append(...parseInline(line));
  });
}

function isFence(line) { return /^\s*```/.test(line); }
function isHeading(line) { return /^#{1,6}\s+\S/.test(line); }
function isRule(line) { return /^\s*([-*_])\s*(\1\s*){2,}$/.test(line); }
function isQuote(line) { return /^\s*>/.test(line); }
function isListItem(line) { return /^\s*([-*+]|\d+[.)])\s+\S/.test(line); }
function isTableRow(line) { return line.includes("|") && line.trim().length > 0; }
function isTableSeparator(line) { return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line); }
function isBlockStart(line) { return !line.trim() || isFence(line) || isHeading(line) || isRule(line) || isQuote(line) || isListItem(line); }

function splitTableRow(line) {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split("|").map(cell => cell.trim());
}

export function renderMarkdown(text) {
  const root = document.createDocumentFragment();
  const lines = String(text ?? "").replace(/\r\n/g, "\n").split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    if (isFence(line)) {
      const lang = line.trim().slice(3).trim();
      const codeLines = [];
      i++;
      while (i < lines.length && !isFence(lines[i])) { codeLines.push(lines[i]); i++; }
      if (i < lines.length) i++; // consume closing fence
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      if (lang) code.className = `language-${lang.replace(/[^a-z0-9+#.-]/gi, "")}`;
      code.textContent = codeLines.join("\n");
      pre.append(code); root.append(pre);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const h = document.createElement(`h${Math.min(heading[1].length, 6)}`);
      h.append(...parseInline(heading[2].trim()));
      root.append(h); i++; continue;
    }

    if (isRule(line)) { root.append(document.createElement("hr")); i++; continue; }

    if (isQuote(line)) {
      const quoteLines = [];
      while (i < lines.length && isQuote(lines[i])) { quoteLines.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
      const blockquote = document.createElement("blockquote");
      blockquote.append(renderMarkdown(quoteLines.join("\n")));
      root.append(blockquote);
      continue;
    }

    if (isTableRow(line) && lines[i + 1] !== undefined && isTableSeparator(lines[i + 1])) {
      const headerCells = splitTableRow(line);
      i += 2;
      const bodyRows = [];
      while (i < lines.length && isTableRow(lines[i])) { bodyRows.push(splitTableRow(lines[i])); i++; }
      const table = document.createElement("table");
      const thead = document.createElement("thead"); const headRow = document.createElement("tr");
      headerCells.forEach(cell => { const th = document.createElement("th"); th.append(...parseInline(cell)); headRow.append(th); });
      thead.append(headRow); table.append(thead);
      const tbody = document.createElement("tbody");
      bodyRows.forEach(row => {
        const tr = document.createElement("tr");
        headerCells.forEach((_, columnIndex) => { const td = document.createElement("td"); td.append(...parseInline(row[columnIndex] ?? "")); tr.append(td); });
        tbody.append(tr);
      });
      table.append(tbody); root.append(table);
      continue;
    }

    if (isListItem(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const itemPattern = ordered ? /^(\s*)\d+[.)]\s+(.*)$/ : /^(\s*)[-*+]\s+(.*)$/;
      const list = document.createElement(ordered ? "ol" : "ul");
      const baseIndent = line.match(/^\s*/)[0].length;
      while (i < lines.length) {
        const match = lines[i].match(itemPattern);
        if (!match || match[1].length !== baseIndent) break;
        const li = document.createElement("li");
        li.append(...parseInline(match[2]));
        i++;
        const nestedLines = [];
        while (i < lines.length && lines[i].trim() && lines[i].match(/^\s*/)[0].length > baseIndent) { nestedLines.push(lines[i].replace(/^ {0,4}/, "")); i++; }
        if (nestedLines.length) li.append(renderMarkdown(nestedLines.join("\n")));
        list.append(li);
      }
      root.append(list);
      continue;
    }

    const paraLines = [];
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i]) && !(isTableRow(lines[i]) && isTableSeparator(lines[i + 1] ?? ""))) { paraLines.push(lines[i]); i++; }
    const p = document.createElement("p");
    appendInlineWithBreaks(p, paraLines);
    root.append(p);
  }

  return root;
}
