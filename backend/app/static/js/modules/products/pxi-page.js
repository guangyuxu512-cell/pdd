import { api } from "../../api/client.js";
import { el, formValue } from "../../core/dom.js";
import { addLog } from "../../core/state.js";
import { renderTable } from "../../components/table.js";
import { renderImagePreview, renderThumbButton } from "../../components/media.js";
import { formatTime } from "../../core/format.js";

let selectedShop = "";
let productIdQuery = "";
let updateDateQuery = "";
let statusFilter = "active";
let pxiRows = [];
let shopOptions = [];
let syncing = false;
let pageSize = 50;
let currentPage = 1;
let previewImageUrl = "";

export async function renderPxiPage(container) {
  const shops = await api.get("/shops");
  shopOptions = shops;
  if (selectedShop) pxiRows = await loadPxiRows();
  else pxiRows = [];
  container.replaceChildren(renderPxiPanel(shops));
}

function renderPxiPanel(shops) {
  return el("section", { class: "panel" }, [
    el("div", { class: "panel-header" }, [
      el("div", { class: "panel-heading" }, [
        el("div", { class: "panel-title", text: "PXI分" }),
        el("div", { class: "actions" }, [
          shopSelect(shops),
          el("input", {
            id: "pxi-update-date",
            class: "pxi-date-input",
            placeholder: "更新日期",
            value: updateDateQuery,
            oninput: (event) => {
              updateDateQuery = event.target.value.trim();
            },
          }),
          el("input", {
            id: "pxi-product-id-query",
            class: "pxi-product-id-query",
            placeholder: "商品ID",
            value: productIdQuery,
            oninput: (event) => {
              productIdQuery = event.target.value.trim();
            },
          }),
          el("button", { class: "primary", onclick: queryPxiRows }, ["查询"]),
          el("button", { disabled: syncing, onclick: syncPxiRows }, [syncing ? "获取中..." : "获取PXI"]),
          statusSelect(),
        ]),
      ]),
      el("span", { class: "badge", text: `${pxiRows.length} 条PXI` }),
    ]),
    el("div", { class: "panel-body" }, [renderPxiTable(), renderPager(), renderImagePreviewModal()]),
  ]);
}

function renderPxiTable() {
  return renderTable({
    rows: pagedRows(),
    emptyText: "暂无PXI数据。选择店铺后点击“获取PXI”。",
    className: "product-table",
    columns: [
      { title: "ID", width: "4%", render: (_row, index) => String((currentPage - 1) * pageSize + index + 1) },
      {
        title: "主图",
        width: "7%",
        render: (row) => renderProductThumb(row.product_image_url),
      },
      { title: "商品ID", key: "product_id", width: "14%" },
      { title: "商品标题", key: "product_title", width: "27%" },
      { title: "PXI分", key: "pxi_score", width: "10%" },
      { title: "更新日期", key: "update_date", width: "12%" },
      { title: "统计范围", key: "range_day", width: "10%" },
      { title: "状态", width: "9%", render: (row) => formatStatus(row.status, row.product_status) },
      {
        title: "最近更新时间",
        width: "11%",
        render: (row) => formatTime(row.last_platform_updated_at || row.updated_at),
        titleValue: (row) => formatTime(row.last_platform_updated_at || row.updated_at),
      },
    ],
  });
}

async function syncPxiRows() {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  syncing = true;
  const updateDate = formValue("pxi-update-date");
  const itemId = formValue("pxi-product-id-query");
  addLog("info", "开始获取PXI", `${shopLabel(selectedShop)} / ${updateDate || "自动日期"} / 固定60条每页`);
  await window.renderActiveModule();
  try {
    const result = await api.post("/pxi/sync", {
      platform,
      shop_id,
      update_date: updateDate || null,
      item_id: itemId,
      range_day: "30d",
      filter_type: "all",
    });
    updateDateQuery = result.update_date;
    pxiRows = await loadPxiRows();
    currentPage = 1;
    addLog(
      "success",
      "结束获取PXI",
      `日期 ${result.update_date}，${result.total_pages} 页，新增 ${result.inserted}，更新 ${result.updated}，失效 ${result.inactive}，共 ${result.count} 条`,
    );
  } catch (error) {
    addLog("error", "获取PXI失败", error.message);
    alert(error.message);
  } finally {
    syncing = false;
    await window.renderActiveModule();
  }
}

async function queryPxiRows() {
  updateDateQuery = formValue("pxi-update-date");
  productIdQuery = formValue("pxi-product-id-query");
  statusFilter = formValue("pxi-status-filter") || "active";
  pxiRows = await loadPxiRows();
  currentPage = 1;
  addLog("info", "查询PXI", [productIdQuery || "全部商品", updateDateQuery || "全部日期", statusLabel(statusFilter)].join(" / "));
  await window.renderActiveModule();
}

async function loadPxiRows() {
  if (!selectedShop) return [];
  const [platform, shop_id] = selectedShop.split("::");
  const params = new URLSearchParams({ platform, shop_id });
  if (productIdQuery) params.set("product_id", productIdQuery);
  if (updateDateQuery) params.set("update_date", normalizeDateInput(updateDateQuery));
  if (statusFilter) params.set("status", statusFilter);
  return api.get(`/pxi?${params.toString()}`);
}

function shopSelect(shops) {
  return el(
    "select",
    {
      class: "ui-select product-shop-select",
      value: selectedShop,
      onchange: async (event) => {
        selectedShop = event.target.value;
        pxiRows = await loadPxiRows();
        currentPage = 1;
        await window.renderActiveModule();
      },
    },
    [
      el("option", { value: "", text: shops.length ? "选择店铺" : "请先创建店铺" }),
      ...shops.map((shop) =>
        el("option", {
          value: `${shop.platform}::${shop.shop_id}`,
          selected: selectedShop === `${shop.platform}::${shop.shop_id}`,
          text: shop.shop_name,
        }),
      ),
    ],
  );
}

function statusSelect() {
  return el(
    "select",
    {
      id: "pxi-status-filter",
      class: "ui-select pxi-status-filter",
      value: statusFilter,
      onchange: async (event) => {
        statusFilter = event.target.value;
        pxiRows = await loadPxiRows();
        currentPage = 1;
        await window.renderActiveModule();
      },
    },
    [
      el("option", { value: "active", selected: statusFilter === "active", text: "有效PXI" }),
      el("option", { value: "inactive", selected: statusFilter === "inactive", text: "失效" }),
      el("option", { value: "all", selected: statusFilter === "all", text: "全部状态" }),
    ],
  );
}

function renderPager() {
  const totalPages = Math.max(1, Math.ceil(pxiRows.length / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;
  return el("div", { class: "pager" }, [
    el("span", { class: "muted", text: `共 ${pxiRows.length} 条` }),
    el(
      "select",
      {
        class: "ui-select pager-size",
        onchange: async (event) => {
          pageSize = Number(event.target.value);
          currentPage = 1;
          await window.renderActiveModule();
        },
      },
      [20, 50, 100, 200].map((size) =>
        el("option", { value: String(size), selected: pageSize === size, text: `${size} 条/页` }),
      ),
    ),
    el("button", { disabled: currentPage <= 1, onclick: () => changePage(currentPage - 1) }, ["上一页"]),
    el("span", { text: `${currentPage} / ${totalPages}` }),
    el("button", { disabled: currentPage >= totalPages, onclick: () => changePage(currentPage + 1) }, ["下一页"]),
  ]);
}

async function changePage(page) {
  currentPage = page;
  await window.renderActiveModule();
}

function pagedRows() {
  const start = (currentPage - 1) * pageSize;
  return pxiRows.slice(start, start + pageSize);
}

function renderProductThumb(url) {
  return renderThumbButton(url, { onOpen: openImagePreview });
}

function renderImagePreviewModal() {
  return renderImagePreview({ url: previewImageUrl, onClose: closeImagePreview });
}

async function openImagePreview(url) {
  previewImageUrl = url;
  await window.renderActiveModule();
}

async function closeImagePreview() {
  previewImageUrl = "";
  await window.renderActiveModule();
}

function normalizeDateInput(value) {
  return String(value || "").replace(/\D/g, "");
}

function formatStatus(status, productStatus) {
  if (productStatus === "deleted") return "商品已删除";
  if (status === "active") return "有效";
  if (status === "inactive") return "失效";
  return status || "";
}

function statusLabel(status) {
  if (status === "active") return "有效PXI";
  if (status === "inactive") return "失效";
  if (status === "all") return "全部状态";
  return "";
}

function shopLabel(value) {
  const shop = shopOptions.find((item) => `${item.platform}::${item.shop_id}` === value);
  return shop?.shop_name || value || "";
}
