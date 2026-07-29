// 模拟用户输入框 encode：发一个中文 question
async function testUserInput() {
  const question = '测试浏览器输入';
  console.log('=== Test 1: 直接发 ===');
  const r1 = await fetch('http://localhost:8000/api/explorations/runs/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  const r = r1.body.getReader();
  const d = new TextDecoder();
  let buf = '';
  for (let i = 0; i < 5; i++) {
    const { done, value } = await r.read();
    if (done) break;
    buf += d.decode(value, { stream: true });
    if (buf.includes('run.created')) {
      const match = buf.match(/data: ({[^}]*"type": "run.created"[^}]*})\n/);
      if (match) {
        const e = JSON.parse(match[1]);
        console.log('Backend received:', e.payload.question);
        break;
      }
    }
  }
}

testUserInput();
