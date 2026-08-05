"use client";

import { useEffect, useMemo, useState } from "react";

import {
  listManagedUsers,
  updateManagedUser,
  type ManagedUser,
} from "../system-api";

export function SystemUsersPanel() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      setUsers(await listManagedUsers());
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "用户加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return users;
    return users.filter((user) =>
      [user.name, user.email, user.role, user.status]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(term)),
    );
  }, [query, users]);

  async function patchUser(
    user: ManagedUser,
    update: Partial<Pick<ManagedUser, "role" | "status">>,
  ) {
    setMessage("正在保存...");
    try {
      const saved = await updateManagedUser(user.id, update);
      setUsers((current) =>
        current.map((entry) => (entry.id === saved.id ? saved : entry)),
      );
      setMessage("更改已生效");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    }
  }

  const activeCount = users.filter((user) => user.status === "active").length;
  const adminCount = users.filter((user) => user.role === "admin").length;

  return (
    <div className="system-domain-panel">
      <div className="system-section-heading">
        <div><span>IDENTITY</span><h2>用户与权限</h2></div>
        <p>维护登录用户、系统角色和账号状态。</p>
      </div>
      <div className="system-stat-strip">
        <div><span>用户总数</span><strong>{users.length}</strong></div>
        <div><span>有效账号</span><strong>{activeCount}</strong></div>
        <div><span>管理员</span><strong>{adminCount}</strong></div>
      </div>
      <div className="system-toolbar">
        <label>
          <span>⌕</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索姓名、邮箱或角色"
          />
        </label>
        <button type="button" onClick={() => void refresh()}>刷新</button>
      </div>
      <div className="system-table" role="table" aria-label="系统用户">
        <div className="system-table-row header" role="row">
          <span>用户</span><span>角色</span><span>状态</span><span>加入时间</span>
        </div>
        {visible.map((user) => (
          <div className="system-table-row" role="row" key={user.id}>
            <div className="system-user-cell">
              <span className="system-user-avatar">
                {user.image ? <img src={user.image} alt="" /> : (user.name || "U").slice(0, 1)}
              </span>
              <span><strong>{user.name || "未命名用户"}</strong><small>{user.email || user.id}</small></span>
            </div>
            <select
              aria-label={`${user.name || user.id}的角色`}
              value={user.role}
              onChange={(event) =>
                void patchUser(user, { role: event.target.value as ManagedUser["role"] })
              }
            >
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
            </select>
            <button
              className={`system-status-action ${user.status}`}
              type="button"
              onClick={() =>
                void patchUser(user, {
                  status: user.status === "active" ? "disabled" : "active",
                })
              }
            >
              <i />{user.status === "active" ? "已启用" : "已停用"}
            </button>
            <time>{new Date(user.createdAt).toLocaleDateString("zh-CN")}</time>
          </div>
        ))}
        {!loading && visible.length === 0 && <div className="system-empty">没有匹配的用户</div>}
        {loading && <div className="system-empty">正在读取用户...</div>}
      </div>
      {message && <p className="system-inline-message" role="status">{message}</p>}
    </div>
  );
}
