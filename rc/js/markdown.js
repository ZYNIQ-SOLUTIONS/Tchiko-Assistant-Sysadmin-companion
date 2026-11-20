// Tchiko RC — Safe XSS-proof Markdown renderer matching tchiko/ui_theme.py.
// Strips hidden model tags (<think>, <output>), builds code cards with language label + Copy,
// and renders prose headings, lists, blockquotes, tables, inline code, bold, italic, and safe links.

const HIDDEN_BLOCKS = /<(?:think|output|channel\|)>[\s\S]*?(?:<\/(?:think|output)>|$)/gi;
const FENCE_RE = /```([a-zA-Z0-9_+-]*)[ \t]*\n?([\s\S]*?)(?:```|$)/g;

export function stripHiddenBlocks(text) {
  return String(text || '').replace(HIDDEN_BLOCKS, '');
}

export function splitMarkdownBlocks(text) {
  const cleaned = stripHiddenBlocks(text);
  const blocks = [];
  let pos = 0;
  FENCE_RE.lastIndex = 0;
  let match;
  while ((match = FENCE_RE.exec(cleaned)) !== null) {
    const before = cleaned.slice(pos, match.index).trim();
    if (before) blocks.push({ kind: 'text', content: before, lang: '' });
    const code = match[2].replace(/^\n+|\n+$/g, '');
    if (code.trim()) blocks.push({ kind: 'code', content: code, lang: match[1] || '' });
    pos = match.index + match[0].length;
  }
  const tail = cleaned.slice(pos).trim();
  if (tail) blocks.push({ kind: 'text', content: tail, lang: '' });
  return blocks;
}

function appendInline(parent, text) {
  // Tokenize inline code, bold, italic, and https/http links safely via DOM nodes (zero innerHTML).
  const tokenRe = /`([^`]+)`|\*\*(.+?)\*\*|(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
  let last = 0;
  let m;
  while ((m = tokenRe.exec(text)) !== null) {
    if (m.index > last) parent.append(document.createTextNode(text.slice(last, m.index)));
    if (m[1] !== undefined) {
      const code = document.createElement('code');
      code.className = 'md-inline-code';
      code.textContent = m[1];
      parent.append(code);
    } else if (m[2] !== undefined) {
      const strong = document.createElement('strong');
      strong.textContent = m[2];
      parent.append(strong);
    } else if (m[3] !== undefined) {
      const em = document.createElement('em');
      em.textContent = m[3];
      parent.append(em);
    } else if (m[4] !== undefined && m[5] !== undefined) {
      const a = document.createElement('a');
      a.href = m[5];
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.textContent = m[4];
      parent.append(a);
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) parent.append(document.createTextNode(text.slice(last)));
}

function renderProse(text) {
  const frag = document.createDocumentFragment();
  const lines = text.split('\n');
  let listEl = null;
  let listType = null;

  const flushList = () => {
    if (listEl) {
      frag.append(listEl);
      listEl = null;
      listType = null;
    }
  };

  for (const raw of lines) {
    const stripped = raw.trim();
    if (!stripped) {
      flushList();
      continue;
    }

    const heading = stripped.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushList();
      const level = Math.min(4, Math.max(2, heading[1].length));
      const h = document.createElement(`h${level}`);
      h.className = 'md-heading';
      appendInline(h, heading[2]);
      frag.append(h);
      continue;
    }

    if (/^[-*_]{3,}$/.test(stripped)) {
      flushList();
      const hr = document.createElement('hr');
      hr.className = 'md-hr';
      frag.append(hr);
      continue;
    }

    const bullet = stripped.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      if (listType !== 'ul') {
        flushList();
        listEl = document.createElement('ul');
        listEl.className = 'md-list';
        listType = 'ul';
      }
      const li = document.createElement('li');
      appendInline(li, bullet[1]);
      listEl.append(li);
      continue;
    }

    const numbered = stripped.match(/^(\d+)[.)]\s+(.*)$/);
    if (numbered) {
      if (listType !== 'ol') {
        flushList();
        listEl = document.createElement('ol');
        listEl.className = 'md-list';
        listType = 'ol';
      }
      const li = document.createElement('li');
      appendInline(li, numbered[2]);
      listEl.append(li);
      continue;
    }

    flushList();

    if (stripped.startsWith('>')) {
      const bq = document.createElement('blockquote');
      bq.className = 'md-quote';
      appendInline(bq, stripped.replace(/^>\s?/, ''));
      frag.append(bq);
      continue;
    }

    if (stripped.startsWith('|') && stripped.endsWith('|')) {
      if (/^[|\s:-]+$/.test(stripped)) continue;
      const row = document.createElement('div');
      row.className = 'md-table-line';
      row.textContent = stripped;
      frag.append(row);
      continue;
    }

    const p = document.createElement('p');
    p.className = 'md-p';
    appendInline(p, stripped);
    frag.append(p);
  }
  flushList();
  return frag;
}

/**
 * Render Markdown text into `container`.
 * `onCopy(text, btn)` is called when a code card's Copy button is clicked.
 */
export function renderMarkdownInto(container, markdownText, onCopy) {
  container.innerHTML = '';
  const blocks = splitMarkdownBlocks(markdownText);
  if (!blocks.length) {
    const p = document.createElement('p');
    p.className = 'md-p dim';
    p.textContent = '(no reply)';
    container.append(p);
    return;
  }

  for (const blk of blocks) {
    if (blk.kind === 'code') {
      const card = document.createElement('div');
      card.className = 'code-card';

      const head = document.createElement('div');
      head.className = 'code-head';
      const lang = document.createElement('span');
      lang.className = 'caption';
      lang.textContent = (blk.lang === '' || blk.lang === 'text' ? 'output' : blk.lang).toUpperCase();
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'icon-btn code-copy-btn';
      copyBtn.title = 'Copy code';
      copyBtn.innerHTML =
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      copyBtn.addEventListener('click', () => onCopy && onCopy(blk.content, copyBtn));
      head.append(lang, copyBtn);

      const pre = document.createElement('pre');
      pre.className = 'code-body';
      const code = document.createElement('code');
      code.textContent = blk.content;
      pre.append(code);

      card.append(head, pre);
      container.append(card);
    } else {
      container.append(renderProse(blk.content));
    }
  }
}
