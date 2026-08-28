/**
 * opencode_slim.ts — agent_eval 评估用插件：把注入 LLM 的工具面压到本地端点
 * (n_ctx=4096) 能装下的最小集。
 *
 * 工具面对齐评估语义：coding 数据集的任务只需要 write/read/bash，opencode
 * 却默认注入 30+ 工具。本插件通过官方 "tool.definition" hook 裁剪：
 *   - bash/write/read：保留最小 JSON schema（只含任务需要的参数）
 *   - 其余工具：jsonSchema 清空、描述截短（模型看到名字但不知参数格式）
 *
 * ⚠️ 关键约束：只能改 output.jsonSchema（纯 JSON）与 description，绝不能动
 * output.parameters —— 它是 effect Schema 对象，opencode 内部会再
 * fromSchema(parameters) 生成 schema，替换为普通对象会直接崩溃。
 */
export default {
  id: "agent-eval-slim-tools",
  async server() {
    const SLIM_SCHEMAS: Record<string, any> = {
      bash: {
        type: "object",
        properties: {
          command: { type: "string", description: "shell command to execute" },
        },
        required: ["command"],
      },
      write: {
        type: "object",
        properties: {
          filePath: { type: "string", description: "file path to write" },
          content: { type: "string", description: "content to write" },
        },
        required: ["filePath", "content"],
      },
      read: {
        type: "object",
        properties: {
          filePath: { type: "string", description: "file path to read" },
        },
        required: ["filePath"],
      },
    };
    return {
      "tool.definition": async (
        _input: { toolID: string },
        output: { description: string; parameters: any; jsonSchema?: any },
      ) => {
        const slim = SLIM_SCHEMAS[_input.toolID];
        if (slim) {
          output.jsonSchema = slim;
          if (typeof output.description === "string" && output.description.length > 60) {
            output.description = output.description.slice(0, 60) + "...";
          }
          return;
        }
        if (typeof output.description === "string" && output.description.length > 10) {
          output.description = output.description.slice(0, 10) + "...";
        }
        output.jsonSchema = { type: "object", properties: {} };
      },
    };
  },
};
