import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue({ template: { transformAssetUrls: { includeAbsolute: false } } })],
  base: '/static/vue/',
  build: {
    outDir: 'dist', manifest: true, sourcemap: false,
    // 两个稳定入口：主窗口壳与独立雷达窗；共享依赖（Vue 等）由打包器自动拆成公共 chunk。
    rolldownOptions: {
      input: { main: 'src/main.ts', radar: 'src/radar.ts' },
      preserveEntrySignatures: 'strict',
    },
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
})
