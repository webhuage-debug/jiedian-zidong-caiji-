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
  SESSION_COOKIE_SECURE: z.enum(["auto", "true", "false"]).default("auto"),
  SESSION_TTL_HOURS: z.coerce.number().int().positive().default(8),
  LOGIN_MAX_FAILURES: z.coerce.number().int().positive().default(5),
  LOGIN_LOCK_MINUTES: z.coerce.number().int().positive().default(15),
  DATA_DIR: z.string().default("./data"),
  DATABASE_PATH: z.string().optional(),
  EXPORT_DIR: z.string().optional(),
  LOG_LEVEL: z.enum(["fatal", "error", "warn", "info", "debug", "trace", "silent"]).default("info"),
  COLLECT_MAX_CONCURRENCY: z.coerce.number().int().positive().max(5).default(2),
  COLLECT_MIN_INTERVAL_MINUTES: z.coerce.number().int().positive().default(60),
  COLLECT_DAILY_MAX_RUNS: z.coerce.number().int().positive().default(6),
  HTTP_TIMEOUT_SECONDS: z.coerce.number().int().positive().default(12),
  COLLECT_RETRY_COUNT: z.coerce.number().int().min(0).max(3).default(2),
  COLLECT_MAX_BYTES: z.coerce.number().int().positive().default(1024 * 1024),
  PUBLIC_SOURCE_SEEDS: z.string().default(""),
  TEST_CONNECT_TIMEOUT_SECONDS: z.coerce.number().int().positive().max(30).default(5),
  TEST_BATCH_SIZE: z.coerce.number().int().positive().max(1000).default(100),
  TEST_MAX_CONCURRENCY: z.coerce.number().int().positive().max(100).default(20),
  XRAY_REAL_TEST_ENABLED: z.enum(["true", "false"]).default("false"),
  XRAY_CORE_PATH: z.string().default(""),
  XRAY_REAL_TEST_CONCURRENCY: z.coerce.number().int().positive().max(5).default(2),
  XRAY_REAL_TEST_TIMEOUT_SECONDS: z.coerce.number().int().positive().max(30).default(12),
  XRAY_LOCAL_PORT_MIN: z.coerce.number().int().positive().default(32000),
  XRAY_LOCAL_PORT_MAX: z.coerce.number().int().positive().default(32100),
  XRAY_TEST_URL: z.string().url().default("http://www.gstatic.com/generate_204"),
  AUTOMATION_API_TOKEN: z.string().default(""),
  DOWNLOAD_RATE_LIMIT_PER_MINUTE: z.coerce.number().int().positive().max(120).default(6)
});

const parsed = envSchema.parse(process.env);
const dataDir = path.resolve(parsed.DATA_DIR);
const publicBaseUrl = parsed.PUBLIC_BASE_URL.trim();
const cookieSecure =
  parsed.SESSION_COOKIE_SECURE === "true" ||
  (parsed.SESSION_COOKIE_SECURE === "auto" && publicBaseUrl.toLowerCase().startsWith("https://"));

export const config = {
  ...parsed,
  DATA_DIR: dataDir,
  XRAY_REAL_TEST_ENABLED: parsed.XRAY_REAL_TEST_ENABLED === "true",
  DATABASE_PATH: path.resolve(parsed.DATABASE_PATH ?? path.join(dataDir, "app.db")),
  EXPORT_DIR: path.resolve(parsed.EXPORT_DIR ?? path.join(dataDir, "exports")),
  SESSION_TTL_MS: parsed.SESSION_TTL_HOURS * 60 * 60 * 1000,
  LOGIN_LOCK_MS: parsed.LOGIN_LOCK_MINUTES * 60 * 1000,
  COLLECT_MIN_INTERVAL_MS: parsed.COLLECT_MIN_INTERVAL_MINUTES * 60 * 1000,
  HTTP_TIMEOUT_MS: parsed.HTTP_TIMEOUT_SECONDS * 1000,
  TEST_CONNECT_TIMEOUT_MS: parsed.TEST_CONNECT_TIMEOUT_SECONDS * 1000,
  XRAY_REAL_TEST_TIMEOUT_MS: parsed.XRAY_REAL_TEST_TIMEOUT_SECONDS * 1000,
  PUBLIC_SOURCE_SEEDS: parsed.PUBLIC_SOURCE_SEEDS.split(",")
    .map((value) => value.trim())
    .filter(Boolean),
  COOKIE_SECURE: cookieSecure,
  isProduction: parsed.NODE_ENV === "production"
};
