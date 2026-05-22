import "dotenv/config";
import path from "node:path";
import { z } from "zod";

const envSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  APP_NAME: z.string().default("Public Node Admin"),
  APP_HOST: z.string().default("0.0.0.0"),
  APP_PORT: z.coerce.number().int().positive().default(3000),
  PUBLIC_BASE_URL: z.string().default("http://localhost:3000"),
  ADMIN_USERNAME: z.string().min(3).default("admin"),
  ADMIN_PASSWORD: z.string().min(8).default("change-this-password-before-deploy"),
  SESSION_SECRET: z.string().min(32).default("dev-session-secret-change-me-please-32"),
  SESSION_TTL_HOURS: z.coerce.number().int().positive().default(8),
  LOGIN_MAX_FAILURES: z.coerce.number().int().positive().default(5),
  LOGIN_LOCK_MINUTES: z.coerce.number().int().positive().default(15),
  DATA_DIR: z.string().default("./data"),
  DATABASE_PATH: z.string().optional(),
  EXPORT_DIR: z.string().optional(),
  LOG_LEVEL: z.enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"]).default("info")
});

const parsed = envSchema.parse(process.env);
const dataDir = path.resolve(parsed.DATA_DIR);

export const config = {
  ...parsed,
  DATA_DIR: dataDir,
  DATABASE_PATH: path.resolve(parsed.DATABASE_PATH ?? path.join(dataDir, "app.db")),
  EXPORT_DIR: path.resolve(parsed.EXPORT_DIR ?? path.join(dataDir, "exports")),
  SESSION_TTL_MS: parsed.SESSION_TTL_HOURS * 60 * 60 * 1000,
  LOGIN_LOCK_MS: parsed.LOGIN_LOCK_MINUTES * 60 * 1000,
  isProduction: parsed.NODE_ENV === "production"
};
