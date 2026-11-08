// GitHub Pages 시연용: sim/sim.py 를 Pyodide로 브라우저 안에서 돌리고, 웹 대시보드가 쓰는 WebSocket을 흉내 낸다.
// 웹 코드(web/index.html)는 그대로 둔다. 배포 때 .github/workflows/pages.yml 이 이 파일을 index.html 머리에 끼운다.
// 주소 뒤 ?cells=2~6 (기본 6), ?speed=배속 (기본 60)
(() => {
  const q = new URLSearchParams(location.search);
  const cells = Math.min(6, Math.max(2, +q.get('cells') || 6));
  const speed = Math.max(1, +q.get('speed') || 60);
  const DT = 100;   // sim.py DT = 0.1s

  const ready = (async () => {
    const { loadPyodide } = await import('https://cdn.jsdelivr.net/pyodide/v0.27.7/full/pyodide.mjs');
    const py = await loadPyodide();
    const src = await (await fetch('sim.py')).text();
    py.globals.set('__file__', '/home/pyodide/sim.py');   // sim.py 가 WEB_DIR 계산에 쓴다
    py.runPython(src.split('\nif __name__ == "__main__":')[0]);   // Pyodide에서도 __name__ 이 "__main__" 이라 서버 실행부를 뺀다
    py.runPython(`import json, random\ndev = Device(Plant(${cells}, random.Random()))`);
    return py;
  })();

  class SimSocket {
    static OPEN = 1;
    constructor() {
      this.readyState = 0;
      ready.then(py => {
        this.py = py;
        this.readyState = 1;
        this.onopen && this.onopen({});
        // status()는 부저 이벤트를 비우므로 보낼 때만 부른다
        const step = py.runPython(`def _tick(n, out):\n    for _ in range(n): dev.step()\n    return json.dumps({**dev.status(), "sim": True}) if out else None\n_tick`);
        let tick = 0;
        setInterval(() => {   // sim.py serve() 와 같이 0.1초마다 speed 스텝, 5Hz 상태 전송
          const out = ++tick % 2 === 0;
          const text = step(speed, out);
          if (out && this.onmessage) this.onmessage({ data: text });
        }, DT);
      }).catch(e => { console.error(e); this.onclose && this.onclose({}); });
    }
    send(text) {
      const err = this.py.globals.get('dev').command(this.py.toPy(JSON.parse(text)));
      if (err && this.onmessage) this.onmessage({ data: JSON.stringify({ type: 'error', msg: err }) });
    }
    close() {}
  }
  window.WebSocket = SimSocket;
})();
