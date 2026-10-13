import { spawn } from 'node:child_process'
import { resolve } from 'node:path'

export default async function setup() {
  const root = resolve('..')
  // 用合成数据与临时用户目录；stdin 关闭触发正常清理，不依赖真实驱动。
  const code = `import tempfile, os, sys, json
with tempfile.TemporaryDirectory() as directory:
 os.environ['SPRITELENS_DATA_ROOT'] = directory
 from pathlib import Path
 from tools.run_web_demo import build_demo_context
 from spritelens.web.server import LocalServer
 context = build_demo_context(Path(directory), 40)
 server = LocalServer(context, port=0)
 try:
  server.start()
  print(json.dumps({'url': server.url}), flush=True)
  sys.stdin.readline()
 finally:
  server.stop()
  context.close()
`
  const child = spawn(resolve(root, '.venv/Scripts/python.exe'), ['-B', '-u', '-c', code], {
    cwd: root, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, stdio: ['pipe', 'pipe', 'pipe'],
  })
  process.env.SPRITELENS_DEMO_URL = await new Promise<string>((done, reject) => {
    let buffer = ''
    let errors = ''
    child.stderr.on('data', data => { errors += String(data) })
    child.on('error', reject)
    child.on('exit', code => reject(new Error(`demo exited ${code}: ${errors}`)))
    child.stdout.on('data', data => {
      buffer += String(data)
      const line = buffer.split('\n').find(line => line.startsWith('{"url"'))
      if (line) done(JSON.parse(line).url)
    })
  })
  return async () => {
    const exited = new Promise<void>(done => child.once('exit', () => done()))
    child.stdin.end('\n')
    await exited
  }
}
