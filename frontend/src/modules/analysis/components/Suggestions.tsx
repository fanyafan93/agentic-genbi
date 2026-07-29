"use client";

import { suggestions } from "../agentClients/scripts/suggestions";

type Props = {
  onSelect: (suggestionId: string, title: string) => void;
};

export function Suggestions({ onSelect }: Props) {
  return (
    <section className="suggestions" aria-label="建议问题">
      <header>
        <span>开始一个会话</span>
        <strong>问一下，或直接输入你的问题</strong>
      </header>
      <ul>
        {suggestions.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelect(item.id, item.title)}
            >
              <strong>{item.title}</strong>
              <small>{item.description}</small>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
