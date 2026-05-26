import path from "node:path";
import Fastify from "fastify";
import cookie from "@fastify/cookie";
import rateLimit from "@fastify/rate-limit";
import fastifyStatic from "@fastify/static";
import { config } from "./config.js";
import { initializeDatabase } from "./db.js";
import { registerAuthRoutes } from "./auth.js";
import { registerApiRoutes } from "./routes.js";
import { registerPublicClaimRoutes } from "./publicClaim.js";
import { startSubscriptionMaintenance } from "./subscription/subscriptionService.js";

initializeDatabase();

const app = Fastify({
  logger: { level: config.LOG_LEVEL }
});

await app.register(cookie, { secret: config.SESSION_SECRET });
await app.register(rateLimit, {
  max: 120,
  timeWindow: "1 minute",
  errorResponseBuilder: () => ({
    statusCode: 429,
    error: "Too Many Requests",
    message: "请求过于频繁，请 1 分钟后再试"
  })
});

registerAuthRoutes(app);
registerApiRoutes(app);
registerPublicClaimRoutes(app);

const stopSubscriptionMaintenance = startSubscriptionMaintenance(app.log);
app.addHook("onClose", async () => {
  stopSubscriptionMaintenance();
});

const webDist = path.resolve(process.cwd(), "apps/web/dist");
await app.register(fastifyStatic, {
  root: webDist,
  prefix: "/"
});

app.setNotFoundHandler((request, reply) => {
  if (request.url.startsWith("/api/")) {
    return reply.code(404).send({ message: "接口不存在。" });
  }
  if (request.url.startsWith("/r/") || request.url.startsWith("/claim/")) {
    reply.header("X-Robots-Tag", "noindex, nofollow");
  }
  return reply.sendFile("index.html");
});

try {
  await app.listen({ host: config.APP_HOST, port: config.APP_PORT });
} catch (error) {
  app.log.error(error);
  process.exit(1);
}
