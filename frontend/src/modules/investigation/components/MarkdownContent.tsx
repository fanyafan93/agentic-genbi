"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type MarkdownSegment =
  | { type: "markdown"; value: string }
  | { type: "math"; value: string };

export function MarkdownContent({ children }: { children: string }) {
  const segments = splitMarkdownMath(children);

  return (
    <>
      {segments.map((segment, index) =>
        segment.type === "math" ? (
          <FormulaBlock key={`math-${index}`} source={segment.value} />
        ) : (
          <ReactMarkdown key={`markdown-${index}`} remarkPlugins={[remarkGfm]}>
            {segment.value}
          </ReactMarkdown>
        ),
      )}
    </>
  );
}

export function splitMarkdownMath(source: string): MarkdownSegment[] {
  const segments: MarkdownSegment[] = [];
  const pattern = /(?:\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|(^|\n)(?:\*\*)?\s*\[([\s\S]*?\\frac[\s\S]*?)\]\s*(?=\n|$))/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(source))) {
    const prefix = match[3] ?? "";
    const matchStart = match.index + prefix.length;
    if (matchStart > cursor) {
      segments.push({ type: "markdown", value: source.slice(cursor, matchStart) });
    }

    const value = match[1] ?? match[2] ?? match[4] ?? "";
    segments.push({ type: "math", value });
    cursor = pattern.lastIndex;
  }

  if (cursor < source.length) {
    segments.push({ type: "markdown", value: source.slice(cursor) });
  }

  return segments.filter((segment) => segment.value.trim().length > 0);
}

export function parseLatexFormula(source: string) {
  const normalized = source.replace(/\*\*/g, "").replace(/\\left|\\right/g, "").trim();
  const label = normalized.match(/\\boxed\s*\{\s*\\text\s*\{([^}]*)\}\s*\}/)?.[1]?.trim() ?? null;
  const textFraction = normalized.match(/\\frac\s*\{\s*\\text\s*\{([^}]*)\}\s*\}\s*\{\s*\\text\s*\{([^}]*)\}\s*\}/);
  if (textFraction) {
    return {
      label,
      numerator: textFraction[1].trim(),
      denominator: textFraction[2].trim(),
      fallback: cleanupLatexText(normalized),
    };
  }

  const simpleFraction = normalized.match(/\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}/);
  if (simpleFraction) {
    return {
      label,
      numerator: cleanupLatexText(simpleFraction[1]),
      denominator: cleanupLatexText(simpleFraction[2]),
      fallback: cleanupLatexText(normalized),
    };
  }

  return {
    label,
    numerator: null,
    denominator: null,
    fallback: cleanupLatexText(normalized),
  };
}

function FormulaBlock({ source }: { source: string }) {
  const formula = parseLatexFormula(source);

  return (
    <div className="formula-block" aria-label="数学公式">
      {formula.label && <span className="formula-label">{formula.label}</span>}
      {formula.numerator && formula.denominator ? (
        <span className="formula-fraction">
          <span>{formula.numerator}</span>
          <span>{formula.denominator}</span>
        </span>
      ) : (
        <code>{formula.fallback}</code>
      )}
    </div>
  );
}

function cleanupLatexText(value: string) {
  return value
    .replace(/\\text\s*\{([^}]*)\}/g, "$1")
    .replace(/\\boxed\s*\{([^}]*)\}/g, "$1")
    .replace(/\\frac/g, "")
    .replace(/[{}]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}
