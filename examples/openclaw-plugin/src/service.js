import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const PACKAGE_VERSION = "1.6.1";
const DEFAULT_API_BASE_URL = "http://127.0.0.1:8766";
const BRAINPACK_MOUNTS_FILE = "brainpacks.mounted.json";
const MIND_MOUNTS_FILE = "minds.mounted.json";
const DEFAULT_IDENTITY_FIELDS = Object.freeze({
  canonicalSubjectId: true,
  phoneNumber: true,
  email: true,
  username: true,
});

function _isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function _coerceString(value, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

function _expandUserPath(value) {
  const text = _coerceString(value).trim();
  if (text.startsWith("~/")) {
    return path.join(os.homedir(), text.slice(2));
  }
  return text;
}

function _normalizeBaseUrl(value) {
  const raw = _coerceString(value, DEFAULT_API_BASE_URL).trim() || DEFAULT_API_BASE_URL;
  return raw.replace(/\/+$/, "");
}

function _normalizeIdentityFields(value) {
  const base = { ...DEFAULT_IDENTITY_FIELDS };
  if (!_isObject(value)) {
    return base;
  }
  for (const key of Object.keys(base)) {
    if (typeof value[key] === "boolean") {
      base[key] = value[key];
    }
  }
  return base;
}

function _pushLog(buffer, message) {
  if (!message) {
    return;
  }
  buffer.push(message);
  if (buffer.length > 50) {
    buffer.shift();
  }
}

function _withTimeout(promise, timeoutMs, message) {
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(message)), timeoutMs);
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) {
      clearTimeout(timer);
    }
  });
}

function _maybeCall(fn, ...args) {
  if (typeof fn !== "function") {
    return undefined;
  }
  try {
    return fn(...args);
  } catch {
    return undefined;
  }
}

export function readPluginConfig(api, ctx) {
  const candidates = [
    _maybeCall(api?.getConfig, "cortex"),
    _maybeCall(api?.getConfig),
    api?.pluginConfig,
    api?.config,
    api?.plugin?.config,
    ctx?.pluginConfig,
    ctx?.config,
  ];
  for (const candidate of candidates) {
    if (_isObject(candidate)) {
      return candidate;
    }
  }
  return {};
}

export function normalizePluginConfig(config = {}) {
  const raw = _isObject(config) ? config : {};
  const requestTimeoutMs = Number(raw.requestTimeoutMs);
  const maxContextChars = Number(raw.maxContextChars);
  return {
    storeDir: path.resolve(_expandUserPath(raw.storeDir || "~/.openclaw/cortex")),
    apiBaseUrl: _normalizeBaseUrl(raw.apiBaseUrl || raw.baseUrl),
    apiKey: _coerceString(raw.apiKey).trim(),
    defaultTarget: _coerceString(raw.defaultTarget || "chatgpt", "chatgpt"),
    smartRouting: raw.smartRouting !== false,
    autoSeedThreads: raw.autoSeedThreads !== false,
    projectDirStrategy: _coerceString(raw.projectDirStrategy || "agent-workspace", "agent-workspace"),
    projectDir: raw.projectDir ? path.resolve(_expandUserPath(raw.projectDir)) : "",
    requestTimeoutMs: Number.isFinite(requestTimeoutMs) ? requestTimeoutMs : 15000,
    maxContextChars: Number.isFinite(maxContextChars) ? maxContextChars : 1500,
    failOpen: raw.failOpen !== false,
    namespace: _coerceString(raw.namespace),
    identityFields: _normalizeIdentityFields(raw.identityFields),
  };
}

async function _readMountedBrainpacks(config) {
  const registryPath = path.join(config.storeDir, BRAINPACK_MOUNTS_FILE);
  try {
    const payload = JSON.parse(await fs.readFile(registryPath, "utf-8"));
    const mounts = Array.isArray(payload?.mounts) ? payload.mounts : [];
    return mounts.filter((item) => _coerceString(item?.name).trim() && item?.enabled !== false);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return [];
    }
    throw error;
  }
}

async function _readMountedMinds(config) {
  const registryPath = path.join(config.storeDir, MIND_MOUNTS_FILE);
  try {
    const payload = JSON.parse(await fs.readFile(registryPath, "utf-8"));
    const mounts = Array.isArray(payload?.mounts) ? payload.mounts : [];
    return mounts.filter((item) => _coerceString(item?.name).trim() && item?.enabled !== false);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return [];
    }
    throw error;
  }
}

async function _requestJson(config, { method = "GET", path: endpoint, payload = null, timeoutMs }) {
  if (typeof fetch !== "function") {
    throw new Error("The Cortex OpenClaw plugin requires Node.js 18+ with global fetch support.");
  }
  const controller = new AbortController();
  const headers = {
    Accept: "application/json",
  };
  if (payload !== null) {
    headers["Content-Type"] = "application/json";
  }
  if (config.apiKey) {
    headers.Authorization = `Bearer ${config.apiKey}`;
  }
  if (config.namespace) {
    headers["X-Cortex-Namespace"] = config.namespace;
  }

  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${config.apiBaseUrl}${endpoint}`, {
      method,
      headers,
      body: payload === null ? undefined : JSON.stringify(payload),
      signal: controller.signal,
    });
    const text = await response.text();
    let body = {};
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = { error: text };
      }
    }
    if (!response.ok) {
      const detail = _coerceString(body?.error || body?.message, `HTTP ${response.status}`);
      throw new Error(detail);
    }
    return body;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`Timed out waiting for Cortex API response from ${endpoint}.`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export class CortexApiService {
  constructor(api, initialConfig = {}) {
    this.api = api;
    this.initialConfig = initialConfig;
    this.startPromise = null;
    this.ready = false;
    this.degradedReason = "";
    this.logBuffer = [];
    this.lastConfig = normalizePluginConfig(initialConfig);
  }

  logger() {
    return this.api?.logger || console;
  }

  resolveConfig(ctx = null, overrides = {}) {
    const merged = {
      ...readPluginConfig(this.api, ctx),
      ...this.initialConfig,
      ...overrides,
    };
    const normalized = normalizePluginConfig(merged);
    this.lastConfig = normalized;
    return normalized;
  }

  status() {
    return {
      ready: this.ready,
      degradedReason: this.degradedReason,
      transport: "http-api",
      apiBaseUrl: this.lastConfig.apiBaseUrl,
      version: PACKAGE_VERSION,
      logs: [...this.logBuffer],
    };
  }

  async start(ctx = null, overrides = {}) {
    if (this.startPromise) {
      return this.startPromise;
    }
    if (this.ready) {
      return this.status();
    }
    const config = this.resolveConfig(ctx, overrides);
    this.startPromise = this.health(config.requestTimeoutMs)
      .then(() => {
        this.ready = true;
        this.degradedReason = "";
        _maybeCall(this.logger().info, `[cortex] Cortex API is ready at ${config.apiBaseUrl}.`);
        return this.status();
      })
      .catch((error) => {
        this.ready = false;
        this.degradedReason = error instanceof Error ? error.message : String(error);
        _pushLog(this.logBuffer, `api: ${this.degradedReason}`);
        _maybeCall(this.logger().warn, `[cortex] Cortex API unavailable: ${this.degradedReason}`);
        if (config.failOpen) {
          return this.status();
        }
        throw error;
      })
      .finally(() => {
        this.startPromise = null;
      });
    return this.startPromise;
  }

  async _get(endpoint, timeoutMs = this.lastConfig.requestTimeoutMs) {
    return _withTimeout(
      _requestJson(this.lastConfig, {
        method: "GET",
        path: endpoint,
        timeoutMs,
      }),
      timeoutMs + 250,
      `Timed out waiting for Cortex API response from ${endpoint}.`,
    );
  }

  async _post(endpoint, payload, timeoutMs = this.lastConfig.requestTimeoutMs) {
    return _withTimeout(
      _requestJson(this.lastConfig, {
        method: "POST",
        path: endpoint,
        payload,
        timeoutMs,
      }),
      timeoutMs + 250,
      `Timed out waiting for Cortex API response from ${endpoint}.`,
    );
  }

  async health(timeoutMs = this.lastConfig.requestTimeoutMs) {
    return this._get("/v1/health", timeoutMs);
  }

  async prepareTurn(payload, timeoutMs = this.lastConfig.requestTimeoutMs) {
    return this._post("/v1/channel/prepare-turn", payload, timeoutMs);
  }

  async seedTurnMemory(payload, timeoutMs = this.lastConfig.requestTimeoutMs) {
    return this._post("/v1/channel/seed-turn-memory", payload, timeoutMs);
  }

  async packContext(payload, timeoutMs = this.lastConfig.requestTimeoutMs) {
    return this._post("/v1/packs/context", payload, timeoutMs);
  }

  async mindCompose(payload, timeoutMs = this.lastConfig.requestTimeoutMs) {
    return this._post("/v1/minds/compose", payload, timeoutMs);
  }

  async listMountedBrainpacks(config = this.lastConfig) {
    return _readMountedBrainpacks(config);
  }

  async listMountedMinds(config = this.lastConfig) {
    return _readMountedMinds(config);
  }

  async stop() {
    this.ready = false;
    return undefined;
  }
}

export function createCortexMcpService(api, initialConfig = {}) {
  return new CortexApiService(api, initialConfig);
}
