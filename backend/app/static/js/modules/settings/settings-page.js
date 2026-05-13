import { api } from "../../api/client.js";
import { el } from "../../core/dom.js";
import { addLog } from "../../core/state.js";

export async function renderSettingsPage(container) {
  const configs = await api.get("/config");
  const values = configValues(configs);
  container.replaceChildren(
    el("section", { class: "panel" }, [
      el("div", { class: "panel-header" }, [el("div", { class: "panel-title", text: "运行配置" })]),
      el("div", { class: "panel-body" }, [
        el("div", { class: "form-grid" }, [
          field("最大并发数", el("input", { id: "max-task-workers", type: "number", value: values.max_task_workers ?? "5" })),
          field("飞书 App ID", el("input", { id: "feishu-app-id", value: values.feishu_app_id ?? "" })),
          field("飞书 App Secret", el("input", { id: "feishu-app-secret", type: "password", value: values.feishu_app_secret ?? "" })),
          field("多维表格 ID", el("input", { id: "feishu-bitable-id", value: values.feishu_bitable_id ?? "" })),
          field("Sheet 页 ID", el("input", { id: "feishu-sheet-id", value: values.feishu_sheet_id ?? "" })),
          field("飞书机器人 Webhook", el("input", { id: "feishu-bot-webhook", type: "password", value: values.feishu_bot_webhook ?? "" })),
          field("实例说明", el("input", { value: "单应用独立数据库 / 独立 Profile", disabled: true })),
        ]),
        el("div", { class: "actions" }, [
          el("button", { class: "primary", onclick: saveConfig }, ["保存配置"]),
        ]),
      ]),
    ]),
  );
}

async function saveConfig() {
  const configs = [
    ["max_task_workers", "max-task-workers", "int", false, "本机最大任务并发数"],
    ["feishu_app_id", "feishu-app-id", "string", false, "飞书应用 App ID"],
    ["feishu_app_secret", "feishu-app-secret", "string", true, "飞书应用 App Secret"],
    ["feishu_bitable_id", "feishu-bitable-id", "string", false, "飞书多维表格 ID"],
    ["feishu_sheet_id", "feishu-sheet-id", "string", false, "飞书 Sheet 页 ID"],
    ["feishu_bot_webhook", "feishu-bot-webhook", "string", true, "飞书机器人 Webhook"],
  ];
  for (const [key, id, valueType, sensitive, description] of configs) {
    const value = document.getElementById(id).value || "";
    if (sensitive && value === "***") continue;
    await api.put(`/config/${key}`, {
      value,
      value_type: valueType,
      sensitive,
      description,
    });
  }
  addLog("success", "保存运行配置", "飞书配置已保存");
}

function field(label, control) {
  return el("div", { class: "form-row" }, [el("label", { text: label }), control]);
}

function configValues(configs) {
  return Object.fromEntries(configs.map((item) => [item.key, item.value]));
}
