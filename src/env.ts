import { createEnv } from "@t3-oss/env-core";
import { config as loadEnv } from "dotenv";
import { z } from "zod";

loadEnv({ path: ".env", quiet: true, override: true });

export const env = createEnv({
  server: {
    ANTHROPIC_API_KEY: z.string().min(1),
    MGBA_HTTP_BASE_URL: z.url().default("http://127.0.0.1:5000"),
    AI_MODEL: z.string().min(1).default("claude-opus-4-7"),
  },
  runtimeEnv: process.env,
  emptyStringAsUndefined: true,
});
