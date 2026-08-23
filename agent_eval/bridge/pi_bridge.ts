/**
 * pi_bridge.ts — 无 key 驱动 pi coding-agent 的评估桥（框架侧适配器）
 *
 * 设计原则：评估不能污染被测对象（第六章隔离精神）。
 * - 本文件属于 agent_eval 框架，不写入被测对象目录；
 * - 通过 PI_ROOT 环境变量定位被测 pi 源码根，用绝对路径动态 import；
 * - 输入/输出走 stdin/stdout JSON，进程隔离。
 *
 * stdin  : JSON { cwd, instruction, plan: [{tool, args}], answer }
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

function mkAssistant(content: any[], stopReason: "stop" | "toolUse"): any {
  return {
    role: "assistant",
    content,
    api: "mock",
    provider: "mock",
    model: "mock-model",
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0,
             cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason,
    timestamp: Date.now(),
  };
}

async function main() {
  const input = JSON.parse(await readStdin());
  const cwd = input.cwd;
  const plan: Array<{ tool: string; args: Record<string, any> }> = input.plan ?? [];
  const answer: string = input.answer ?? "done";
  const { AssistantMessageEventStream, createAgentSessionFromServices, createAgentSessionServices,
          SessionManager, SettingsManager } = await loadPi();

  // ---- fake ModelRuntime: deterministic stream per plan step ----
  const fakeModelRuntime: any = {
    registerProvider() {},
    registerNativeProvider() {},
    async refresh() {},
    hasConfiguredAuth() { return true; },
    listModels() { return []; },
    setApiKey() {},
    getModel() {
      return {
        id: "mock-model", name: "mock", api: "mock", provider: "mock",
        baseUrl: "", reasoning: false, input: [],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 0, maxTokens: 0,
      };
    },
    async streamSimple(_model: any, context: any) {
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
