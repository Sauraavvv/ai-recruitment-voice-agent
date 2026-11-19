import { defineConfig } from "@playwright/test";

// E2E against a real, isolated stack (tests/e2e/start-backend.sh): backend on 8011 with its own
// database and no provider keys, and `next dev` on 3011 proxying to it.
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3011",
    viewport: { width: 1440, height: 1000 },
    colorScheme: "dark",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "bash tests/e2e/start-backend.sh",
      url: "http://127.0.0.1:8011/health",
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "ignore",
    },
    {
      command: "npx next dev -p 3011",
      url: "http://localhost:3011/login",
      timeout: 180_000,
      reuseExistingServer: false,
      env: { BACKEND_INTERNAL_URL: "http://127.0.0.1:8011" },
    },
  ],
});
