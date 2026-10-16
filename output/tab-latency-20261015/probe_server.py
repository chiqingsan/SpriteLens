"""只在合成 demo HTML 注入诊断脚本；不改生产文件，不接触真实账号。"""
from pathlib import Path
import json
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from aiohttp import web
from tools.run_web_demo import build_demo_context
from spritelens.web.server import LocalServer

DIRECTORY = Path(__file__).parent
class ProbeServer(LocalServer):
    async def _index(self, request):
        source = (self._static_dir / 'index.html').read_text(encoding='utf-8')
        script = (DIRECTORY / 'probe.js').read_text(encoding='utf-8')
        return web.Response(text=source.replace('</head>', '<script>' + script + '</script></head>'), content_type='text/html')

with tempfile.TemporaryDirectory() as temp:
    context = build_demo_context(Path(temp), 2000)
    server = ProbeServer(context, port=0)
    server.start()
    print(json.dumps({'url': server.url}), flush=True)
    try:
        while not (DIRECTORY / 'stop').exists():
            time.sleep(.25)
    finally:
        server.stop()
        context.close()
