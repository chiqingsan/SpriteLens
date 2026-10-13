import { defineConfig } from '@playwright/test'
export default defineConfig({
  testDir: './browser', globalSetup: './browser/setup.ts', workers: 1,
  use: { browserName: 'chromium', headless: true, trace: 'retain-on-failure' },
})
