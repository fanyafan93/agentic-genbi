export function SignInScreen() {
  return (
    <main className="login-screen">
      <section className="login-panel" aria-label="登录">
        <span className="panel-kicker">AGENTIC GENBI</span>
        <h1>登录后进入工作台</h1>
        <p>使用飞书账号登录，用于隔离不同用户的会话、探索和后续资产。</p>
        <a className="login-primary" href="/api/auth/feishu-login">
          使用飞书登录
        </a>
      </section>
    </main>
  );
}
