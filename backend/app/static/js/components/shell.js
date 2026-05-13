import { el } from "../core/dom.js";
import { setActiveModule, state } from "../core/state.js";

export const modules = [
  { id: "shops", title: "店铺管理" },
  { id: "products", title: "商品列表" },
  { id: "shunshou", title: "顺手报名工作台" },
  { id: "settings", title: "运行配置" },
];

export function renderShell(root) {
  root.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-title">淘宝工具箱</div>
          <div class="brand-subtitle">报名工作流</div>
        </div>
        <nav class="menu" id="menu"></nav>
        <div class="sidebar-footer">
          <div>Backend: 127.0.0.1:8800</div>
          <div>SQLite / Local Profile</div>
        </div>
      </aside>
      <section class="workspace">
        <section class="task-banner" id="task-banner"></section>
        <main class="operation-area" id="operation-area"></main>
        <section class="log-dock" id="log-dock"></section>
      </section>
    </div>
  `;
}

export function renderTaskBanner() {
  const root = document.getElementById("task-banner");
  if (!root) return;
  const task = state.activeTasks[state.activeTasks.length - 1];
  if (!task) {
    root.className = "task-banner";
    root.replaceChildren();
    return;
  }
  root.className = "task-banner active";
  root.replaceChildren(
    el("span", { class: "task-spinner" }),
    el("strong", { text: task.message }),
    task.context ? el("span", { text: task.context }) : "",
  );
}

export function renderMenu() {
  const menu = document.getElementById("menu");
  menu.replaceChildren(
    ...modules.map((item) =>
      el(
        "button",
        {
          class: item.id === state.activeModule ? "active" : "",
          onclick: () => {
            setActiveModule(item.id);
            window.renderActiveModule();
          },
        },
        [item.title],
      ),
    ),
  );
}

export function setPageTitle(title) {
  document.title = title ? `${title} - 淘宝工具箱` : "淘宝工具箱";
}
