import { el } from "../../core/dom.js";
import { state } from "../../core/state.js";

export function renderLogPanel() {
  const root = document.getElementById("log-dock");
  const rows = state.logs.length
    ? [...state.logs].sort((a, b) => logOrder(a) - logOrder(b)).map((log) =>
        el("div", { class: "log-row" }, [
          el("span", { text: log.time }),
          el("span", { class: `log-level-${log.level}`, text: log.level }),
          el("span", { text: `${log.message}${log.context ? ` ${log.context}` : ""}` }),
        ]),
      )
    : [el("div", { class: "muted", text: "业务日志会固定显示在这里。" })];

  root.replaceChildren(
    el("div", { class: "log-header" }, [
      el("strong", { text: "业务日志" }),
      el("span", { text: "最近 100 条" }),
    ]),
    el("div", { class: "log-body" }, rows),
  );

  const body = root.querySelector(".log-body");
  if (body) {
    body.scrollTop = body.scrollHeight;
  }
}

function logOrder(log) {
  if (Number.isFinite(log.timestamp)) return log.timestamp;
  const parts = String(log.time || "").split(":").map((item) => Number(item));
  if (parts.length !== 3 || parts.some((item) => Number.isNaN(item))) return 0;
  return parts[0] * 3600 + parts[1] * 60 + parts[2];
}
