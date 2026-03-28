import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

const PACKAGE_VERSION = "1.4.1";
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

function _normalizeTransport(value) {
  const raw = _coerceString(value, "managed-child").trim().toLowerCase();
  if (raw === "custom-command" || raw === "managed-child") {
    return raw;
  }
  if (raw === "external-mcp") {
    return "custom-command";
  }
  if (raw === "in-process-python") {
    return "managed-child";
  }
  return "managed-child";
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

function _hasConfigArg(args) {
  return args.some((item) => item === "--config");
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
  const configPath = _expandUserPath(raw.configPath || "~/.openclaw/cortex/config.toml");
  const rawArgs = Array.isArray(raw.mcpArgs) && raw.mcpArgs.length > 0 ? raw.mcpArgs : ["--config", configPath];
  const requestTimeoutMs = Number(raw.requestTimeoutMs);
  const healthCheckTimeoutMs = Number(raw.healthCheckTimeoutMs);
  const maxContextChars = Number(raw.maxContextChars);
  const serviceRestartLimit = Number(raw.serviceRestartLimit);
  const serviceRestartBackoffMs = Number(raw.serviceRestartBackoffMs);
  return {
    storeDir: path.resolve(_expandUserPath(raw.storeDir || "~/.openclaw/cortex")),
    configPath: path.resolve(configPath),
    transport: _normalizeTransport(raw.transport),
    mcpCommand: _coerceString(raw.mcpCommand || "cortex-mcp", "cortex-mcp").trim() || "cortex-mcp",
    mcpArgs: rawArgs.map((item) => _expandUserPath(String(item))),
    defaultTarget: _coerceString(raw.defaultTarget || "chatgpt", "chatgpt"),
    smartRouting: raw.smartRouting !== false,
    autoSeedThreads: raw.autoSeedThreads !== false,
    projectDirStrategy: _coerceString(raw.projectDirStrategy || "agent-workspace", "agent-workspace"),
    projectDir: raw.projectDir ? path.resolve(_expandUserPath(raw.projectDir)) : "",
    requestTimeoutMs: Number.isFinite(requestTimeoutMs) ? requestTimeoutMs : 15000,
    healthCheckTimeoutMs: Number.isFinite(healthCheckTimeoutMs) ? healthCheckTimeoutMs : 5000,
    maxContextChars: Number.isFinite(maxContextChars) ? maxContextChars : 1500,
    failOpen: raw.failOpen !== false,
    serviceRestartLimit: Number.isFinite(serviceRestartLimit) ? serviceRestartLimit : 3,
    serviceRestartBackoffMs: Number.isFinite(serviceRestartBackoffMs) ? serviceRestartBackoffMs : 1000,
    namespace: _coerceString(raw.namespace),
    identityFields: _normalizeIdentityFields(raw.identityFields),
  };
}

function _escapeTomlString(value) {
  return String(value).replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

async function _ensureManagedConfig(config) {
  await fs.mkdir(config.storeDir, { recursive: true });
  await fs.mkdir(path.dirname(config.configPath), { recursive: true });
  try {
    await fs.access(config.configPath);
    return;
  } catch {}
  const sections = [
    "[runtime]",
    `store_dir = "${_escapeTomlString(config.storeDir)}"`,
    "",
    "[mcp]",
  ];
  if (config.namespace) {
    sections.push(`namespace = "${_escapeTomlString(config.namespace)}"`);
  } else {
    sections.push('namespace = ""');
  }
  sections.push("");
  await fs.writeFile(config.configPath, sections.join("\n"), "utf-8");
}

export function buildManagedChildCommand(config, options = {}) {
  const normalized = normalizePluginConfig(config);
  const args = Array.isArray(normalized.mcpArgs) ? [...normalized.mcpArgs] : [];
  if (normalized.transport === "managed-child" && !_hasConfigArg(args)) {
    args.push("--config", normalized.configPath);
  }
  if (options.check && !args.includes("--check")) {
    args.push("--check");
  }
  return {
    command: normalized.mcpCommand,
    args,
  };
}

async function _runCheckCommand(command, args, timeoutMs, cwd) {
  const child = spawn(command, args, {
    cwd,
    stdio: ["ignore", "pipe", "pipe"],
    env: process.env,
  });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => {
    stdout += String(chunk);
  });
  child.stderr.on("data", (chunk) => {
    stderr += String(chunk);
  });
  const exitPromise = new Promise((resolve, reject) => {
    child.on("error", reject);
    child.on("exit", (code) => resolve(Number(code ?? 0)));
  });
  const code = await _withTimeout(
    exitPromise,
    timeoutMs,
    `Timed out waiting for Cortex MCP health check after ${timeoutMs}ms.`,
  );
  if (code !== 0) {
    const detail = (stderr || stdout || `exit ${code}`).trim();
    throw new Error(`Cortex MCP health check failed: ${detail}`);
  }
}

export class CortexMcpService {
  constructor(api, initialConfig = {}) {
    this.api = api;
    this.initialConfig = initialConfig;
    this.child = null;
    this.pending = new Map();
    this.nextRequestId = 1;
    this.startPromise = null;
    this.stopPromise = null;
    this.restartTimer = null;
    this.restartCount = 0;
    this.ready = false;
    this.stopRequested = false;
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
      restartCount: this.restartCount,
      transport: this.lastConfig.transport,
      command: this.lastConfig.mcpCommand,
      args: [...this.lastConfig.mcpArgs],
      logs: [...this.logBuffer],
    };
  }

  async start(ctx = null, overrides = {}) {
    if (this.startPromise) {
      return this.startPromise;
    }
    if (this.ready && this.child) {
      return this.status();
    }
    const config = this.resolveConfig(ctx, overrides);
    this.stopRequested = false;
    this.startPromise = this._start(config)
      .then(() => this.status())
      .finally(() => {
        this.startPromise = null;
      });
    return this.startPromise;
  }

  async _start(config) {
    if (config.transport === "managed-child") {
      await _ensureManagedConfig(config);
      const checkCommand = buildManagedChildCommand(config, { check: true });
      await _runCheckCommand(checkCommand.command, checkCommand.args, config.healthCheckTimeoutMs, process.cwd());
    }

    const { command, args } = buildManagedChildCommand(config);
    const child = spawn(command, args, {
      cwd: process.cwd(),
      stdio: ["pipe", "pipe", "pipe"],
      env: process.env,
    });
    this.child = child;
    this.ready = false;
    this.degradedReason = "";

    const stdout = readline.createInterface({ input: child.stdout });
    stdout.on("line", (line) => {
      this._handleStdoutLine(line);
    });

    const stderr = readline.createInterface({ input: child.stderr });
    stderr.on("line", (line) => {
      const trimmed = String(line || "").trim();
      if (!trimmed) {
        return;
      }
      _pushLog(this.logBuffer, `stderr: ${trimmed}`);
      _maybeCall(this.logger().warn, trimmed);
    });

    child.on("error", (error) => {
      this.degradedReason = error.message;
      this._flushPending(error);
      _maybeCall(this.logger().error, `[cortex] MCP process error: ${error.message}`);
    });
    child.on("exit", (code, signal) => {
      this.ready = false;
      this.child = null;
      const reason = `Cortex MCP exited with code ${code ?? "null"}${signal ? ` signal ${signal}` : ""}`.trim();
      this.degradedReason = reason;
      this._flushPending(new Error(reason));
      if (!this.stopRequested && config.transport === "managed-child" && this.restartCount < config.serviceRestartLimit) {
        this.restartCount += 1;
        const delay = config.serviceRestartBackoffMs * this.restartCount;
        _maybeCall(this.logger().warn, `[cortex] ${reason}. Restarting in ${delay}ms.`);
        this.restartTimer = setTimeout(() => {
          this.start(null, config).catch((error) => {
            this.degradedReason = error.message;
            _maybeCall(this.logger().error, `[cortex] restart failed: ${error.message}`);
          });
        }, delay);
      } else if (!this.stopRequested) {
        _maybeCall(this.logger().error, `[cortex] ${reason}`);
      }
    });

    await this._initialize(config.requestTimeoutMs);
    await this.health(config.requestTimeoutMs);
    this.ready = true;
    this.restartCount = 0;
    _maybeCall(this.logger().info, "[cortex] Cortex MCP is ready.");
  }

  _handleStdoutLine(line) {
    const trimmed = String(line || "").trim();
    if (!trimmed) {
      return;
    }
    let payload = null;
    try {
      payload = JSON.parse(trimmed);
    } catch {
      _pushLog(this.logBuffer, `stdout: ${trimmed}`);
      return;
    }
    const requestId = payload?.id;
    if (requestId !== undefined && this.pending.has(requestId)) {
      const pending = this.pending.get(requestId);
      this.pending.delete(requestId);
      if (payload.error) {
        pending.reject(new Error(payload.error.message || "Unknown Cortex MCP error."));
        return;
      }
      pending.resolve(payload.result);
      return;
    }
    _pushLog(this.logBuffer, `stdout-json: ${trimmed}`);
  }

  _flushPending(error) {
    for (const pending of this.pending.values()) {
      pending.reject(error);
    }
    this.pending.clear();
  }

  _writeMessage(payload) {
    if (!this.child?.stdin) {
      throw new Error("Cortex MCP process is not running.");
    }
    this.child.stdin.write(`${JSON.stringify(payload)}\n`);
  }

  async _initialize(timeoutMs) {
    await this._sendRequest(
      "initialize",
      {
        protocolVersion: "2025-11-25",
        clientInfo: { name: "@cortex/openclaw", version: PACKAGE_VERSION },
      },
      timeoutMs,
    );
    this._writeMessage({
      jsonrpc: "2.0",
      method: "notifications/initialized",
    });
  }

  async _sendRequest(method, params = {}, timeoutMs = this.lastConfig.requestTimeoutMs) {
    const requestId = this.nextRequestId++;
    return _withTimeout(
      new Promise((resolve, reject) => {
        this.pending.set(requestId, { resolve, reject });
        this._writeMessage({
          jsonrpc: "2.0",
          id: requestId,
          method,
          params,
        });
      }),
      timeoutMs,
      `Timed out waiting for Cortex MCP response to ${method}.`,
    );
  }

  async callTool(name, argumentsPayload = {}, timeoutMs = this.lastConfig.requestTimeoutMs) {
    if (!this.child) {
      await this.start(null, this.lastConfig);
    }
    const result = await this._sendRequest(
      "tools/call",
      { name, arguments: argumentsPayload },
      timeoutMs,
    );
    if (result?.isError) {
      const structured = result.structuredContent || {};
      throw new Error(structured.error || `Cortex tool ${name} failed.`);
    }
    return result?.structuredContent || {};
  }

  async health(timeoutMs = this.lastConfig.requestTimeoutMs) {
    return this.callTool("health", {}, timeoutMs);
  }

  async prepareTurn(payload, timeoutMs = this.lastConfig.requestTimeoutMs) {
    return this.callTool("channel_prepare_turn", payload, timeoutMs);
  }

  async seedTurnMemory(payload, timeoutMs = this.lastConfig.requestTimeoutMs) {
    return this.callTool("channel_seed_turn_memory", payload, timeoutMs);
  }

  async stop() {
    if (this.stopPromise) {
      return this.stopPromise;
    }
    this.stopRequested = true;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    if (!this.child) {
      this.ready = false;
      return undefined;
    }
    const child = this.child;
    this.stopPromise = new Promise((resolve) => {
      const finalize = () => {
        this.child = null;
        this.ready = false;
        this.stopPromise = null;
        resolve(undefined);
      };
      child.once("exit", finalize);
      child.kill();
      setTimeout(() => {
        if (!child.killed) {
          child.kill("SIGKILL");
        }
      }, 2000);
    });
    return this.stopPromise;
  }
}

export function createCortexMcpService(api, initialConfig = {}) {
  return new CortexMcpService(api, initialConfig);
}
