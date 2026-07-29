// 模拟前端 SSE decode 测试
async function testSseDecode() {
  const response = await fetch('http://localhost:8000/api/explorations/runs/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question: '抖音 GMV' }),
  });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  const events = [];
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const lines = part.split(/\r?\n/).filter((line) => line.startsWith('data: '));
      if (lines.length > 0) {
        const data = lines.map((line) => line.slice(6)).join('\n');
        try {
          const event = JSON.parse(data);
          events.push(event);
          if (event.type === 'agent.message.created' || event.type === 'agent.title.generated') {
            console.log(`[${event.type}]`, JSON.stringify(event.payload).slice(0, 300));
          }
        } catch (e) { /* ignore */ }
      }
    }
    if (done) break;
    if (events.length > 6) break;
  }
}

testSseDecode().catch(console.error);
