import { api } from "../../api/client.js";
import { el, formValue } from "../../core/dom.js";
import { addLog } from "../../core/state.js";
import { renderTable } from "../../components/table.js";

const selectedShopIds = new Set();
let activeLoginSession = null;
let activeReloginShopPk = null;
let activeProfileId = null;

export async function renderShopPage(container) {
  const shops = await api.get("/shops");
  selectedShopIds.forEach((id) => {
    if (!shops.some((shop) => shop.id === id)) selectedShopIds.delete(id);
  });
  container.replaceChildren(renderShopPanel(shops), renderLoginModal());
}

function renderShopPanel(shops) {
  return el("section", { class: "panel" }, [
    el("div", { class: "panel-header" }, [
      el("div", { class: "panel-heading" }, [
        el("div", { class: "panel-title", text: "店铺管理" }),
        el("div", { class: "actions" }, [
          el("button", { class: "primary", onclick: openLoginModal }, ["网页登录"]),
          el("button", { onclick: batchRefreshCookie }, ["批量刷新状态"]),
          el("button", { class: "danger", onclick: batchDelete }, ["批量删除"]),
        ]),
      ]),
      el("span", { class: "badge", text: `${shops.length} 个店铺` }),
    ]),
    el("div", { class: "panel-body" }, [
      renderTable({
        rows: shops,
        emptyText: "暂无店铺。点击“网页登录”打开独立浏览器实例，登录后保存。",
        columns: [
          {
            title: "",
            className: "check-cell",
            width: "3%",
            render: (shop) =>
              el("input", {
                class: "row-check",
                type: "checkbox",
                checked: selectedShopIds.has(shop.id),
                onchange: (event) => toggleShop(shop.id, event.target.checked),
              }),
          },
          { title: "店铺名", key: "shop_name", width: "16%" },
          { title: "旺旺", key: "wangwang", width: "13%" },
          { title: "店铺类型", key: "shop_type", width: "12%" },
          { title: "店铺 ID", key: "shop_id", width: "16%" },
          {
            title: "店铺状态",
            width: "12%",
            render: (shop) =>
              el("span", {
                class: statusClass(shop.cookie_status),
                text: statusText(shop.cookie_status),
              }),
          },
          {
            title: "最后检测",
            width: "12%",
            render: (shop) => formatTime(shop.last_cookie_check_at),
          },
          {
            title: "操作",
            className: "action-cell",
            width: "16%",
            render: (shop) =>
              el("div", { class: "actions" }, [
                el("button", { onclick: () => refreshCookie(shop.id) }, ["检测"]),
                el("button", { onclick: () => reloginShop(shop) }, ["重登"]),
                el("button", { class: "danger", onclick: () => deleteShop(shop.id) }, ["删除"]),
              ]),
          },
        ],
      }),
    ]),
  ]);
}

function renderLoginModal() {
  return el("div", { id: "login-modal", class: "modal-mask" }, [
    el("div", { class: "modal" }, [
      el("div", { class: "modal-header" }, [
        el("strong", { text: "网页登录实例" }),
        el("button", { class: "ghost", onclick: closeLoginModal }, ["关闭"]),
      ]),
      el("div", { class: "modal-body" }, [
        el("div", { id: "login-instance-info", class: "muted", text: "正在等待分配浏览器实例..." }),
        el("div", { style: "height: 12px" }),
        el("div", { class: "form-grid" }, [
          field("登录地址", el("input", { value: "https://myseller.taobao.com/home.htm/SellManage/in_stock?current=1&pageSize=20", disabled: true })),
          field(
            "Cookie 类型",
            el(
              "select",
              { id: "login-cookie-type" },
              [
                el("option", { value: "main", text: "普通 cookie" }),
                el("option", { value: "promotion", text: "推广 cookie（预留）" }),
              ],
            ),
          ),
          field(
            "关闭浏览器",
            el(
              "select",
              { id: "login-close-browser" },
              [
                el("option", { value: "true", text: "保存后关闭" }),
                el("option", { value: "false", text: "保存后保留" }),
              ],
            ),
          ),
          field(
            "完整Cookie",
            el("textarea", {
              id: "login-cookie-header-text",
              rows: "4",
              placeholder: "可选：粘贴影刀/浏览器导出的完整 Cookie 字符串。填写后优先保存这条 Cookie。",
            }),
          ),
        ]),
        el("div", { class: "actions" }, [
          el("button", { class: "primary", onclick: checkBrowserLogin }, ["读取店铺信息并保存"]),
        ]),
        el("p", {
          class: "muted",
          text: "系统会提取浏览器 cookie/storage_state，并自动请求淘宝店铺信息接口抓取店铺名和店铺 ID，后续 HTTP 请求会复用最新 cookie。",
        }),
      ]),
    ]),
  ]);
}

async function openLoginModal() {
  document.getElementById("login-modal").classList.add("open");
  try {
    await startBrowserLogin();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setLoginInstanceInfo(`打开浏览器失败：${message}`);
    addLog("error", "网页登录失败", message);
  }
}

function closeLoginModal() {
  if (activeLoginSession) {
    api.post(`/browser/login-sessions/${activeLoginSession}/close`).catch(() => {});
  }
  activeLoginSession = null;
  activeProfileId = null;
  activeReloginShopPk = null;
  document.getElementById("login-modal").classList.remove("open");
}

async function startBrowserLogin() {
  setLoginInstanceInfo("正在分配独立浏览器实例...");
  const result = await api.post("/browser/login-sessions", {
    shop_pk: activeReloginShopPk,
    cookie_type: formValue("login-cookie-type"),
  });
  activeLoginSession = result.session_id;
  activeProfileId = result.profile_id;
  setLoginInstanceInfo(`已打开实例：${result.profile_id}，Profile：${result.profile_path}`);
  addLog("info", "自动打开网页登录实例", result.profile_id);
}

function reloginShop(shop) {
  activeReloginShopPk = shop.id;
  openLoginModal();
}

async function checkBrowserLogin() {
  if (!activeLoginSession) {
    alert("浏览器实例还未分配完成");
    return;
  }
  if (!activeReloginShopPk && formValue("login-cookie-type") === "promotion") {
    alert("推广 cookie 必须绑定已有店铺，请在店铺行点击“重新登录”后保存");
    return;
  }
  const result = await api.post(`/browser/login-sessions/${activeLoginSession}/check`, {
    cookie_type: formValue("login-cookie-type"),
    close_browser: formValue("login-close-browser") !== "false",
    cookie_header_text: formValue("login-cookie-header-text"),
  });
  const meta = [result.wangwang, result.shop_type].filter(Boolean).join(" / ");
  addLog("success", "保存登录态", `${result.shop_name} ${meta} ${result.shop_id} cookies=${result.cookie_count}`);
  if (result.cookie_missing?.length) {
    addLog("error", "Cookie关键项缺失", result.cookie_missing.join("、"));
  }
  if (result.cookie_missing_recommended?.length) {
    addLog("info", "Cookie建议项缺失", result.cookie_missing_recommended.join("、"));
  }
  activeLoginSession = null;
  activeProfileId = null;
  closeLoginModal();
  await window.renderActiveModule();
}

function setLoginInstanceInfo(text) {
  const node = document.getElementById("login-instance-info");
  if (node) node.textContent = text;
}

function toggleShop(id, checked) {
  if (checked) selectedShopIds.add(id);
  else selectedShopIds.delete(id);
}

async function refreshCookie(id) {
  const result = await api.post(`/shops/${id}/refresh-cookie`);
  addLog("info", "检测 cookie", `${result.shop_name} ${statusText(result.cookie_status)}`);
  await window.renderActiveModule();
}

async function batchRefreshCookie() {
  const ids = [...selectedShopIds];
  if (!ids.length) {
    alert("请先勾选店铺");
    return;
  }
  await api.post("/shops/batch-refresh-cookie", { ids });
  addLog("info", "批量刷新店铺状态", `${ids.length} 个店铺`);
  await window.renderActiveModule();
}

async function deleteShop(id) {
  if (!confirm("确认删除这个店铺？")) return;
  await api.delete(`/shops/${id}`);
  selectedShopIds.delete(id);
  addLog("success", "删除店铺", `ID=${id}`);
  await window.renderActiveModule();
}

async function batchDelete() {
  const ids = [...selectedShopIds];
  if (!ids.length) {
    alert("请先勾选店铺");
    return;
  }
  if (!confirm(`确认删除 ${ids.length} 个店铺？`)) return;
  const result = await api.post("/shops/batch-delete", { ids });
  selectedShopIds.clear();
  addLog("success", "批量删除店铺", `${result.deleted} 个店铺`);
  await window.renderActiveModule();
}

function statusClass(status) {
  if (status === "valid") return "status-valid";
  if (status === "invalid") return "status-invalid";
  return "status-unknown";
}

function statusText(status) {
  if (status === "valid") return "在线/cookie 有效";
  if (status === "invalid") return "失效/需重新登录";
  return "未知";
}

function formatTime(value) {
  if (!value) return "未检测";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function field(label, control) {
  return el("div", { class: "form-row" }, [el("label", { text: label }), control]);
}
