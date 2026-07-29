"use client";

import { signOut, useSession } from "next-auth/react";

function getInitial(name?: string | null, email?: string | null) {
  const source = (name || email || "U").trim();
  return source.slice(0, 1).toUpperCase();
}

export function UserChip() {
  const { data: session, status } = useSession();
  const user = session?.user;
  const name = user?.name || user?.email || (status === "loading" ? "读取中" : "未登录");
  const role = user?.role === "admin" ? "管理员" : "用户";

  return (
    <button className="user-chip" type="button" aria-label="账户，点击退出登录" title="退出登录" onClick={() => signOut()}>
      <span className="user-chip-avatar-wrap" aria-hidden="true">
        {user?.image ? (
          <img className="user-chip-avatar" src={user.image} alt="" referrerPolicy="no-referrer" />
        ) : (
          <span className="user-chip-avatar">{getInitial(user?.name, user?.email)}</span>
        )}
        <svg className="user-chip-ring" viewBox="0 0 36 36" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <circle cx="18" cy="18" r="16" />
        </svg>
      </span>
      <span className="user-chip-meta">
        <span className="user-chip-name">{name}</span>
        <span className="user-chip-role">{role}</span>
      </span>
    </button>
  );
}
