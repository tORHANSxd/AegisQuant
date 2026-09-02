import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: [
    {
      command: ".\\.venv\\Scripts\\python.exe -m uvicorn aegisquant.api.app:create_app --factory --host 127.0.0.1 --port 8150",
      cwd: "../..",
      url: "http://127.0.0.1:8150/api/v1/health",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "..\\..\\.tools\\node-v24.20.0-win-x64\\node.exe ..\\..\\.tools\\pnpm\\node_modules\\pnpm\\bin\\pnpm.cjs build && ..\\..\\.tools\\node-v24.20.0-win-x64\\node.exe ..\\..\\.tools\\pnpm\\node_modules\\pnpm\\bin\\pnpm.cjs start",
      url: "http://127.0.0.1:3000",
      env: {
        AEGISQUANT_API_URL: "http://127.0.0.1:8150",
        NEXT_PUBLIC_AEGISQUANT_API_URL: "http://127.0.0.1:8150",
      },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
