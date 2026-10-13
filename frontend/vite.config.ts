import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue({ template: { transformAssetUrls: { includeAbsolute: false } } })],
  base: '/static/vue/',
  build: {
    outDir: 'dist', manifest: true, sourcemap: false,
    rolldownOptions: { input: 'src/main.ts', preserveEntrySignatures: 'strict' },
  },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
})
