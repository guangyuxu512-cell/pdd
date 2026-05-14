import { api } from "../../api/client.js";
import { el, formValue } from "../../core/dom.js";
import { addLog } from "../../core/state.js";
import { renderTable } from "../../components/table.js";
import { renderImagePreview, renderThumbButton } from "../../components/media.js";
import { formatTime } from "../../core/format.js";

let selectedShop = "";
let skuCodeQuery = "";
let productIdQuery = "";
let statusFilter = "active";
let skus = [];
let shopOptions = [];
let previewImageUrl = "";
let syncingPrices = false;

export async function renderSkuPage(container) {
  const shops = await api.get("/shops");
  shopOptions = shops;
  if (selectedShop) skus = await loadSkus();
  else skus = [];
  container.replaceChildren(renderSkuPanel(shops));
}

function renderSkuPanel(shops) {
  return el("section", { class: "panel" }, [
    el("div", { class: "panel-header" }, [
      el("div", { class: "panel-heading" }, [
        el("div", { class: "panel-title", text: "SKU表" }),
        el("div", { class: "actions" }, [
          shopSelect(shops),
          el("button", { class: "primary", disabled: syncingPrices, onclick: syncFeishuPrices }, [
            syncingPrices ? "匹配中..." : "匹配飞书价格",
          ]),
        ]),
      ]),
      el("span", { class: "badge", text: `${skus.length} 个SKU` }),
    ]),
    el("div", { class: "panel-body" }, [
      el("div", { class: "sku-toolbar" }, [
        el("input", {
          id: "sku-product-id-query",
          placeholder: "商品ID",
          value: productIdQuery,
          oninput: (event) => {
            productIdQuery = event.target.value.trim();
          },
        }),
        el("input", {
          id: "sku-code-query",
          placeholder: "SKU编码",
          value: skuCodeQuery,
          oninput: (event) => {
            skuCodeQuery = event.target.value.trim();
          },
        }),
        el("button", { class: "primary", onclick: querySkus }, ["查询"]),
        statusSelect(),
      ]),
      renderSkuTable(),
      renderImagePreviewModal(),
    ]),
  ]);
}

async function syncFeishuPrices() {
  syncingPrices = true;
  addLog("info", "开始匹配飞书价格", "全局读取飞书价格表，按 SKU编码 回填所有店铺SKU");
  await window.renderActiveModule();
  try {
    const result = await api.post("/products/skus/prices/sync");
    skus = await loadSkus();
    addLog(
      "success",
      "结束匹配飞书价格",
      `映射 ${result.mapping_upserted} 条，通用价 ${result.global_rows}，店铺价 ${result.shop_rows}，全局更新 ${result.updated_global_skus}，店铺更新 ${result.updated_shop_skus}`,
    );
    if (result.warnings.length) {
      addLog("error", "飞书价格警告", result.warnings.slice(0, 3).join("；"));
    }
  } catch (error) {
    addLog("error", "匹配飞书价格失败", error.message);
    alert(error.message);
  } finally {
    syncingPrices = false;
    await window.renderActiveModule();
  }
}

function renderSkuTable() {
  return renderTable({
    rows: skus,
    emptyText: "暂无SKU。请先在商品列表勾选商品并点击“获取SKUID”。",
    className: "product-table",
    columns: [
      { title: "ID", width: "4%", render: (_sku, index) => String(index + 1) },
      {
        title: "SKU主图",
        width: "7%",
        render: (sku) => renderThumb(sku.image_url),
      },
      { title: "商品ID", key: "product_id", width: "12%" },
      { title: "SKUID", key: "sku_id", width: "12%" },
      { title: "SKU编码", key: "sku_code", width: "13%" },
      { title: "规格", key: "sku_name", width: "18%" },
      { title: "正常售价", width: "8%", render: (sku) => formatNullablePrice(sku.normal_sale_price) },
      { title: "顺手报名价", width: "9%", render: (sku) => formatNullablePrice(sku.shunshou_signup_price) },
      { title: "库存", key: "stock", width: "6%" },
      { title: "状态", width: "6%", render: (sku) => formatStatus(sku.status) },
      {
        title: "最近更新",
        width: "8%",
        render: (sku) => formatTime(sku.last_platform_updated_at || sku.updated_at),
        titleValue: (sku) => formatTime(sku.last_platform_updated_at || sku.updated_at),
      },
    ],
  });
}

async function querySkus() {
  productIdQuery = formValue("sku-product-id-query");
  skuCodeQuery = formValue("sku-code-query");
  statusFilter = formValue("sku-status-filter") || "active";
  skus = await loadSkus();
  addLog("info", "查询SKU", [productIdQuery || "全部商品", skuCodeQuery || "全部编码", statusLabel(statusFilter)].join(" / "));
  await window.renderActiveModule();
}

async function loadSkus() {
  if (!selectedShop) return [];
  const [platform, shop_id] = selectedShop.split("::");
  const params = new URLSearchParams({ platform, shop_id });
  if (productIdQuery) params.set("product_id", productIdQuery);
  if (skuCodeQuery) params.set("sku_code", skuCodeQuery);
  if (statusFilter) params.set("status", statusFilter);
  return api.get(`/products/skus?${params.toString()}`);
}

function shopSelect(shops) {
  return el(
    "select",
    {
      class: "ui-select product-shop-select",
      value: selectedShop,
      onchange: async (event) => {
        selectedShop = event.target.value;
        skus = await loadSkus();
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
      id: "sku-status-filter",
      class: "ui-select sku-status-filter",
      value: statusFilter,
      onchange: async (event) => {
        statusFilter = event.target.value;
        skus = await loadSkus();
        await window.renderActiveModule();
      },
    },
    [
      el("option", { value: "active", selected: statusFilter === "active", text: "有效" }),
      el("option", { value: "inactive", selected: statusFilter === "inactive", text: "失效" }),
      el("option", { value: "product_deleted", selected: statusFilter === "product_deleted", text: "商品已删除" }),
      el("option", { value: "all", selected: statusFilter === "all", text: "全部状态" }),
    ],
  );
}

function renderThumb(url) {
  return renderThumbButton(url, { title: "查看SKU主图", alt: "SKU主图", onOpen: openImagePreview });
}

function renderImagePreviewModal() {
  return renderImagePreview({ url: previewImageUrl, title: "SKU主图预览", alt: "SKU主图预览", onClose: closeImagePreview });
}

async function openImagePreview(url) {
  previewImageUrl = url;
  await window.renderActiveModule();
}

async function closeImagePreview() {
  previewImageUrl = "";
  await window.renderActiveModule();
}

function formatStatus(status) {
  if (status === "active") return "有效";
  if (status === "inactive") return "失效";
  if (status === "product_deleted") return "商品已删除";
  return status || "";
}

function statusLabel(status) {
  if (status === "active") return "有效";
  if (status === "inactive") return "失效";
  if (status === "product_deleted") return "商品已删除";
  return "全部状态";
}

function formatNullablePrice(value) {
  if (value === null || value === undefined || value === "") return "";
  return Number(value).toFixed(2);
}
