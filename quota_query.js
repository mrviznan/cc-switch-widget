const fs = require("fs");
const vm = require("vm");

function replacePlaceholders(value, baseUrl, apiKey) {
  if (typeof value === "string") {
    return value.replaceAll("{{baseUrl}}", baseUrl).replaceAll("{{apiKey}}", apiKey);
  }
  if (Array.isArray(value)) return value.map((item) => replacePlaceholders(item, baseUrl, apiKey));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, replacePlaceholders(item, baseUrl, apiKey)]));
  }
  return value;
}

function findValue(value, keys) {
  if (!value || typeof value !== "object") return "";
  for (const [key, item] of Object.entries(value)) {
    if (keys.some((candidate) => key.toLowerCase() === candidate.toLowerCase()) && typeof item === "string" && item) return item;
    const nested = findValue(item, keys);
    if (nested) return nested;
  }
  return "";
}

function findBaseUrl(value) {
  const direct = findValue(value, ["ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "baseUrl", "base_url", "endpoint"]);
  if (direct) return direct;
  if (typeof value === "string") {
    const match = value.match(/(?:base_url|baseUrl|endpoint)\s*=\s*["']([^"']+)["']/i);
    return match ? match[1] : "";
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findBaseUrl(item);
      if (found) return found;
    }
  }
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) {
      const found = findBaseUrl(item);
      if (found) return found;
    }
  }
  return "";
}

async function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const script = input.script || {};
  const code = String(script.code || "").trim().replace(/;+\s*$/, "");
  if (!code) throw new Error("余额查询脚本为空");
  if (script.language && String(script.language).toLowerCase() !== "javascript") throw new Error("仅支持 JavaScript 余额查询脚本");

  const definition = vm.runInNewContext(`(${code})`, { console: { log() {} } }, { timeout: 3000 });
  if (!definition || !definition.request || !definition.request.url) throw new Error("无法解析余额查询请求");

  const baseUrl = findBaseUrl(input.settingsConfig);
  const apiKey = findValue(input.settingsConfig, ["ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "apiKey", "api_key", "token"]);
  const request = replacePlaceholders(definition.request, baseUrl, apiKey);
  let body = request.body;
  const headers = { ...(request.headers || {}) };
  if (body && typeof body === "object") {
    body = JSON.stringify(body);
    if (!Object.keys(headers).some((key) => key.toLowerCase() === "content-type")) headers["Content-Type"] = "application/json";
  }
  const response = await fetch(request.url, {
    method: request.method || "GET",
    headers,
    body,
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(`余额接口返回 HTTP ${response.status}`);
  const result = typeof definition.extractor === "function" ? definition.extractor(payload) : payload;
  process.stdout.write(JSON.stringify({ ok: true, result }));
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message || String(error) }));
  process.exitCode = 1;
});
