// 模拟前端 fetch 发送中文 question
async function testFetchQuestion() {
  const question = '抖音 7 月 GMV 趋势怎么样？';
  console.log('Sending question:', question);
  console.log('Question bytes:', new TextEncoder().encode(question).length);

  const response = await fetch('http://localhost:8000/api/explorations/runs/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  });

  console.log('Response status:', response.status);
  console.log('Response content-type:', response.headers.get('content-type'));

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let events = [];
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
          if (event.type === 'run.created') {
            console.log('\n[run.created] question as received by backend:', event.payload.question);
            console.log('Same bytes:', new TextEncoder().encode(event.payload.question).length);
          }
        } catch (e) {}
      }
    }
    if (done || events.length > 3) break;
  }
}

testFetchQuestion().catch(console.error);
