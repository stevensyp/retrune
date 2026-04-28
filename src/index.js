import { Container } from "@cloudflare/containers";

export class RetruneContainer extends Container {
  defaultPort = 8899;
  requiredPorts = [8899];
  sleepAfter = "30m";
  enableInternet = true;
  pingEndpoint = "/health";
}

function containerEnv(env) {
  const keys = [
    "HOST",
    "PORT",
    "RECLIP_PASSWORD",
    "RECLIP_PASSWORD_SHA256",
    "RECLIP_AUTH_REQUIRED",
    "RECLIP_COOKIE_SECURE",
    "RECLIP_SESSION_HOURS",
    "SECRET_KEY",
    "ASSEMBLYAI_API_KEY",
    "GOOGLE_API_FREE",
    "YTDLP_BIN",
    "FFMPEG_BIN",
  ];
  const values = {};
  for (const key of keys) {
    if (env[key] !== undefined) values[key] = String(env[key]);
  }
  return values;
}

export default {
  async fetch(request, env) {
    const container = env.RETRUNE_CONTAINER.getByName("retrune-main");
    await container.startAndWaitForPorts({
      ports: [8899],
      startOptions: { envVars: containerEnv(env) },
    });
    return container.fetch(request);
  },
};
