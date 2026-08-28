/**
 * pi_bridge.ts — 驱动 pi coding-agent 的评估桥（框架侧适配器）
 *
 * 设计原则：评估不能污染被测对象（第六章隔离精神）。
 * - 本文件属于 agent_eval 框架，不写入被测对象目录；
 * - 通过 PI_ROOT 环境变量定位被测 pi 源码根，用绝对路径动态 import；
 * - 输入/输出走 stdin/stdout JSON，进程隔离。
 *
 * 两种模型决策模式（由 stdin 的 `llm` 字段切换）：
 * 1. plan 模式（默认，无 llm 字段）：确定性注入 —— 按 reference_plan 逐步返回
 *    toolCall，评估 pi 的 Harness 层（工具执行/会话/状态）。
 * 2. llm 模式（stdin.llm = {baseUrl, model, maxSteps}）：真实模型 ——
 *    streamSimple 内调用 OpenAI 兼容端点，把 pi 的 Context/messages/tools
 *    转换为 OpenAI 格式，评估「pi Harness × 真实 LLM」组合体。
 *
 * stdin  : JSON { cwd, instruction, plan?: [...], answer?: str, llm?: {baseUrl, model, maxSteps} }
 * stdout : JSON { ok, trajectory: [{tool, args, isError, error}], answer, error? }
 */
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const PI_ROOT = (process.env.PI_ROOT ?? "D:/MyFiles/agent-harness/pi-main").replace(/\\+$/, "");

async function loadPi() {
  const { AssistantMessageEventStream } = await import(
    pathToFileURL(`${PI_ROOT}/packages/ai/src/index.ts`).href
  );
  const { createAgentSessionFromServices, createAgentSessionServices, SessionManager, SettingsManager } =
    await import(pathToFileURL(`${PI_ROOT}/packages/coding-agent/src/index.ts`).href);
  return { AssistantMessageEventStream, createAgentSessionFromServices, createAgentSessionServices, SessionManager, SettingsManager };
}

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => (data += c));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function mkAssistant(content: any[], stopReason: "stop" | "toolUse" | "error"): any {
  return {
    role: "assistant",
    content,
    api: "openai",
    provider: "openai",
    model: "google/gemma-4-12b-qat",
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0,
             cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason,
    timestamp: Date.now(),
  };
}

// ---- pi Context/messages/tools <-> OpenAI chat.completions conversion ----

function toOpenAIMessages(context: any): any[] {
  const out: any[] = [];
  if (context.systemPrompt) {
    out.push({ role: "system", content: context.systemPrompt });
  }
  const textOf = (content: any): string => {
    if (typeof content === "string") return content;
    return (content ?? []).filter((p: any) => p?.type === "text")
      .map((p: any) => p.text).join("\n");
  };
  for (const m of context.messages ?? []) {
    if (m.role === "user") {
      const t = textOf(m.content);
      if (t) out.push({ role: "user", content: t });
    } else if (m.role === "assistant") {
      const a: any = { role: "assistant" };
      const t = textOf(m.content);
      if (t) a.content = t;
      const calls = (m.content ?? [])
        .filter((p: any) => p?.type === "toolCall")
        .map((p: any) => ({
          id: p.id ?? `call_${Math.random().toString(36).slice(2, 10)}`,
          type: "function",
          function: { name: p.name, arguments: JSON.stringify(p.arguments ?? {}) },
        }));
      if (calls.length) a.tool_calls = calls;
      out.push(a);
    } else if (m.role === "toolResult") {
      const t = textOf(m.content);
      out.push({
        role: "tool",
        tool_call_id: m.toolCallId ?? `call_${Math.random().toString(36).slice(2, 10)}`,
        content: t || (m.isError ? "ERROR" : "ok"),
      });
    }
  }
  return out;
}

function toOpenAITools(tools: any[]): any[] {
  const out: any[] = [];
  for (const t of tools ?? []) {
    if (!t || !t.name) continue;
    out.push({
      type: "function",
      function: {
        name: t.name,
        description: t.description ?? "",
        parameters: JSON.parse(JSON.stringify(t.parameters ?? { type: "object", properties: {} })),
      },
    });
  }
  return out;
}

async function llmStream(context: any, llmCfg: any, AssistantMessageEventStream: any): Promise<any> {
  const messages = toOpenAIMessages(context);
  const tools = toOpenAITools(context.tools);
  const body: any = {
    model: llmCfg.model,
    messages,
    temperature: 0,
    max_tokens: llmCfg.maxTokens ?? 2048,
  };
  if (tools.length) body.tools = tools;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 300_000);
  let resp: Response;
  try {
    resp = await fetch(`${llmCfg.baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (e: any) {
    clearTimeout(timer);
    const stream = new AssistantMessageEventStream();
    stream.push({ type: "done", reason: "error",
                  message: mkAssistant([{ type: "text", text: "" }], "error") });
    return stream;
  }
  clearTimeout(timer);
  const data: any = await resp.json();
  const msg = data?.choices?.[0]?.message ?? {};
  const stream = new AssistantMessageEventStream();

  const calls = (msg.tool_calls ?? []).map((tc: any) => {
    let args: Record<string, any> = {};
    try { args = JSON.parse(tc.function.arguments ?? "{}"); } catch { /* keep {} */ }
    return { type: "toolCall", id: tc.id ?? `call_${Math.random().toString(36).slice(2, 10)}`,
             name: tc.function.name, arguments: args };
  });
  const parts: any[] = [];
  if (msg.content) parts.push({ type: "text", text: msg.content });
  for (const c of calls) parts.push(c);

  if (calls.length > 0) {
    for (const c of calls) {
      stream.push({ type: "toolcall_start", contentIndex: 0, partial: mkAssistant(parts, "toolUse") });
      stream.push({ type: "toolcall_end", contentIndex: 0, toolCall: c, partial: mkAssistant(parts, "toolUse") });
    }
    stream.push({ type: "done", reason: "toolUse", message: mkAssistant(parts, "toolUse") });
  } else {
    stream.push({ type: "done", reason: "stop", message: mkAssistant(parts, "stop") });
  }
  return stream;
}

async function main() {
  const input = JSON.parse(await readStdin());
  const cwd = input.cwd;
  const plan: Array<{ tool: string; args: Record<string, any> }> = input.plan ?? [];
  const answer: string = input.answer ?? "done";
  const llmCfg: any = input.llm ?? null;
  const { AssistantMessageEventStream, createAgentSessionFromServices, createAgentSessionServices,
          SessionManager, SettingsManager } = await loadPi();

  // ---- model runtime: plan-driven (deterministic) OR real LLM (llmCfg) ----
  const fakeModelRuntime: any = {
    registerProvider() {},
    registerNativeProvider() {},
    async refresh() {},
    hasConfiguredAuth() { return true; },
    listModels() { return []; },
    setApiKey() {},
    getModel() {
      return {
        id: llmCfg?.model ?? "mock-model",
        name: llmCfg?.model ?? "mock",
        api: "openai",
        provider: llmCfg ? "openai" : "mock",
        baseUrl: llmCfg?.baseUrl ?? "",
        reasoning: false, input: [],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 0, maxTokens: llmCfg?.maxTokens ?? 0,
      };
    },
    async streamSimple(model: any, context: any) {
      if (llmCfg) {
        return llmStream(context, llmCfg, AssistantMessageEventStream);
      }
      const stream = new AssistantMessageEventStream();
      const toolResults = (context.messages ?? []).filter((m: any) => m.role === "toolResult");
      const stepIndex = toolResults.length;
      const step = plan[stepIndex];
      if (step) {
        const call = { type: "toolCall", id: `call_${stepIndex}`, name: step.tool, arguments: step.args };
        stream.push({ type: "toolcall_start", contentIndex: 0, partial: mkAssistant([call], "toolUse") });
        stream.push({ type: "toolcall_end", contentIndex: 0, toolCall: call, partial: mkAssistant([call], "toolUse") });
        stream.push({ type: "done", reason: "toolUse", message: mkAssistant([call], "toolUse") });
      } else {
        stream.push({ type: "done", reason: "stop", message: mkAssistant([{ type: "text", text: answer }], "stop") });
      }
      return stream;
    },
  };

  const agentDir = mkdtempSync(join(tmpdir(), "pi-eval-agent-"));
  const sessionDir = mkdtempSync(join(tmpdir(), "pi-eval-sessions-"));

  const services = await createAgentSessionServices({
    cwd,
    agentDir,
    modelRuntime: fakeModelRuntime,
    settingsManager: SettingsManager.inMemory(),
  });
  const sessionManager = SessionManager.create(cwd, sessionDir);
  const { session } = await createAgentSessionFromServices({
    services,
    sessionManager,
    model: fakeModelRuntime.getModel(),
    thinkingLevel: "off",
  });

  try {
    await session.prompt(input.instruction ?? "请完成任务。");
  } catch (e) {
    throw new Error(`session.prompt failed: ${String(e?.message ?? e)}`);
  }

  // 轨迹从 session.messages 提取
  const trajectory: any[] = [];
  for (const m of session.messages) {
    if (m.role === "assistant") {
      for (const part of m.content ?? []) {
        if (part.type === "toolCall") {
          trajectory.push({ tool: part.name, args: part.arguments, isError: false });
        }
      }
    } else if (m.role === "toolResult") {
      const last = trajectory[trajectory.length - 1];
      if (last && last.tool === m.toolName) {
        last.isError = m.isError === true;
        last.error = m.isError ? (typeof m.content === "string" ? m.content : JSON.stringify(m.content)) : undefined;
      }
    }
  }
  const output = {
    ok: true,
    trajectory,
    answer: session.getLastAssistantText() ?? "",
  };
  process.stdout.write(JSON.stringify(output));
  try { session.dispose(); } catch { /* noop */ }
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ ok: false, error: String(e?.message ?? e) }));
  process.exit(1);
});
