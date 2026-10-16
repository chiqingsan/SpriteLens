from __future__ import annotations
import asyncio, base64, json, subprocess, sys, tempfile, time
from dataclasses import replace
from pathlib import Path
import aiohttp
ROOT = Path(r"D:\code\SpriteLens")
sys.path.insert(0, str(ROOT))
from tools.run_web_demo import build_demo_context
from spritelens.web.server import LocalServer

async def capture(server, output, profile):
    for _ in range(100):
        active = profile / 'DevToolsActivePort'
        if active.exists():
            break
        await asyncio.sleep(.1)
    port = int(active.read_text().splitlines()[0])
    async with aiohttp.ClientSession() as session:
        async with session.get(server.url.split('#')[0]) as response:
            print({'HTTP': response.status, 'type': response.headers.get('Content-Type'), 'length': len(await response.read())}, flush=True)
        async with session.get(f'http://127.0.0.1:{port}/json/list') as response:
            targets = await response.json()
        target = next(t for t in targets if t['type'] == 'page')
        async with session.ws_connect(target['webSocketDebuggerUrl']) as ws:
            sequence = 0
            async def command(method, params=None):
                nonlocal sequence
                sequence += 1
                await ws.send_json(dict(id=sequence, method=method, params=params or {}))
                async for message in ws:
                    data = json.loads(message.data)
                    if data.get('id') == sequence:
                        if 'error' in data:
                            raise RuntimeError(data['error'])
                        return data.get('result', {})
            async def js(expression):
                result = await command('Runtime.evaluate', dict(expression=expression, awaitPromise=True, returnByValue=True))
                if 'exceptionDetails' in result:
                    raise RuntimeError(result['exceptionDetails'])
                return result.get('result', {}).get('value')
            async def wait_for(selector):
                await js("new Promise((resolve, reject) => { const stop = Date.now() + 10000; const timer = setInterval(() => { if(document.querySelector(" + json.dumps(selector) + ")){clearInterval(timer);resolve(true)}else if(Date.now()>stop){clearInterval(timer);reject('missing selector')} }, 50) })")
            await command('Page.enable')
            await asyncio.sleep(1)
            await command('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False))
            navigation = await command('Page.navigate', dict(url=server.url))
            print({k:v for k,v in navigation.items() if k!='frameId'}, flush=True)
            await asyncio.sleep(1)
            print(await js('({title:document.title, body:document.body?.innerText.slice(0,400)})'), flush=True)
            await wait_for('.nav-item[data-page="egg-box"]')
            await js('document.querySelector(`.nav-item[data-page="egg-box"]`).click()')
            await wait_for('.eggbox-card')
            await js('Promise.all([...document.querySelectorAll(".eggbox-artwork img")].map(img => img.decode().catch(() => {})))')
            reports = []
            for width, height, theme in [(1871,1052,'miaomiao'), (1440,900,'miaomiao'), (1280,810,'miaomiao'), (1440,900,'huohua'), (1440,900,'shuilanlan'), (960,810,'miaomiao'), (640,900,'miaomiao'), (390,844,'miaomiao')]:
                await command('Emulation.setDeviceMetricsOverride', dict(width=width, height=height, deviceScaleFactor=1, mobile=False))
                await command('Page.bringToFront')
                await js('document.documentElement.dataset.theme=' + json.dumps(theme))
                await js('Promise.all([...document.querySelectorAll(".eggbox-artwork img")].map(img => img.decode().catch(() => {})))')
                await asyncio.sleep(.6)
                if width <= 960:
                    await js('document.querySelector(".eggbox-card").click()')
                    await asyncio.sleep(.15)
                report = await js("""(() => {
                    const box = sel => { const r=document.querySelector(sel)?.getBoundingClientRect(); return r ? {x:r.x,y:r.y,width:r.width,height:r.height}:null };
                    const list = document.querySelector('.eggbox-grid');
                    return {viewport:innerWidth, theme:document.documentElement.dataset.theme,columns:getComputedStyle(list).gridTemplateColumns,card:box('.eggbox-card'),search:box('.eggbox-search'),toolbar:box('.eggbox-list-toolbar'),detail:box('.eggbox-detail-panel'),overflow:[...document.querySelectorAll('.eggbox-card-foot,.eggbox-basic-stat')].filter(x=>x.scrollWidth>x.clientWidth).length,missingImages:[...document.querySelectorAll('.eggbox-artwork img')].filter(x=>!x.naturalWidth).length};
                })()""")
                report['renderedCards'] = await js('document.querySelectorAll(".eggbox-card").length')
                report['listScrollMetrics'] = await js('(() => { const x=document.querySelector(".eggbox-list-scroll"); return {scrollHeight:x.scrollHeight,clientHeight:x.clientHeight,scrollbarWidth:getComputedStyle(x,"::-webkit-scrollbar").width} })()')
                reports.append(report)
                if width == 1871:
                    await js('(() => { const x=document.querySelector(".eggbox-list-scroll"); x.scrollTop=x.scrollHeight; x.dispatchEvent(new Event("scroll")) })()')
                    report['renderedAfterScroll'] = await js('new Promise(resolve => { const start=Date.now(); const poll=()=>{ const n=document.querySelectorAll(".eggbox-card").length; if(n>40 || Date.now()-start>3000) resolve(n); else requestAnimationFrame(poll) }; poll() })')
                shot = await command('Page.captureScreenshot', dict(format='png',captureBeyondViewport=False))
                (output / f'eggbox-{width}-{theme}.png').write_bytes(base64.b64decode(shot['data']))
                if width <= 960:
                    await js('document.querySelector(".eggbox-mobile-close").click()')
                    await asyncio.sleep(.1)
                    shot = await command('Page.captureScreenshot', dict(format='png',captureBeyondViewport=False))
                    (output / f'eggbox-{width}-list.png').write_bytes(base64.b64decode(shot['data']))
            (output / 'layout.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
            print(json.dumps(reports), flush=True)
            await command('Browser.close')

output = ROOT / 'output/eggbox-ui-20261015'
output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='spritelens-egg-ui-') as tmp:
    profile = Path(tmp)/'edge'
    context = build_demo_context(Path(tmp), 24)
    repo = context.egg_box
    seed = next(iter(repo._eggs.values()))
    infos = [x for x in context.egg_catalog.entries() if x.egg_item_id and (ROOT/f'spritelens/web/static/egg-icons/{x.egg_item_id}.png').exists()]
    names = ['恶魔狼', '菊花梨', '小帕尔', '豆丁鱼', '清枝枝', '号儿鱼', '鸭吉吉']
    selected = [next((x for x in infos if x.name==name), infos[i]) for i,name in enumerate(names)]
    repo._eggs.clear()
    repo._hatch_slots.clear()
    for i in range(120):
        info = selected[i % len(selected)]
        repo._eggs[9000+i] = replace(seed, instance_id=9000+i, egg_conf_id=info.egg_item_id, pet_conf_id=info.egg_conf_id, quantity=1,
            obtained_at=1792022400-i*86400, height_cm=round((info.height_low+info.height_high)/2), weight_g=round((info.weight_low+info.weight_high)/2),
            hatched_seconds=0, start_hatch_time=0, special_egg_conf_id=0, appearance_type=0, extension_type=0)
    repo._historical_ids=set(repo._eggs)
    repo._source='historical'
    repo._slots_source='unknown'
    server = LocalServer(context, port=0)
    server.start()
    edge = subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe', '--headless=new','--disable-gpu','--disable-features=CalculateNativeWinOcclusion','--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding','--no-proxy-server','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',f'--user-data-dir={profile}','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        asyncio.run(capture(server, output, profile))
    finally:
        if edge.poll() is None:
            edge.terminate()
            edge.wait(timeout=10)
        server.stop()
        context.close()
print(output)
