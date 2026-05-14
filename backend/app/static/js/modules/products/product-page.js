import { api } from "../../api/client.js";
import { el, formValue } from "../../core/dom.js";
import { addLog, endTask, startTask } from "../../core/state.js";
import { renderTable } from "../../components/table.js";
import { renderImagePreview, renderThumbButton } from "../../components/media.js";
import { formatTime, normalizeNumber } from "../../core/format.js";

let selectedShop = "";
let productIdQuery = "";
let statusFilter = "";
let products = [];
let fetchingProducts = false;
let fetchingSkus = false;
let relistingProducts = false;
let relistModalOpen = false;
let relistStock = 3;
let relistStockMode = "per_sku";
let relistEditPrice = true;
let relistUpdateInventory = true;
let relistUpshelf = true;
let relistDryRun = false;
let relistStopRequested = false;
let stopRequested = false;
let pageSize = 50;
let currentPage = 1;
let shopOptions = [];
let fetchRunId = 0;
let activeSyncId = "";
let previewImageUrl = "";
let sortKey = "";
let sortDirection = "desc";
let lastCheckedProductId = "";
const selectedProductIds = new Set();

export async function renderProductPage(container) {
  const shops = await api.get("/shops");
  shopOptions = shops;
  if (selectedShop) products = await loadProducts();
  else products = [];
  selectedProductIds.forEach((id) => {
    if (!products.some((product) => product.product_id === id && isSelectableProduct(product))) selectedProductIds.delete(id);
  });
  container.replaceChildren(renderProductPanel(shops));
}

function renderProductPanel(shops) {
  return el("section", { class: "panel" }, [
    el("div", { class: "panel-header" }, [
      el("div", { class: "panel-heading" }, [
        el("div", { class: "panel-title", text: "商品列表" }),
        el("div", { class: "actions" }, [
          shopSelect(shops),
          el("button", { class: "primary", disabled: fetchingProducts, onclick: fetchProductList }, [
            fetchingProducts ? "获取中..." : "获取商品ID",
          ]),
          el("button", { disabled: !fetchingProducts, onclick: stopFetchProducts }, ["停止获取"]),
          el("button", { disabled: fetchingSkus, onclick: syncSelectedSkus }, [
            fetchingSkus ? "同步SKU中..." : "同步SKU价/库存",
          ]),
          el("button", { id: "product-relist-button", disabled: relistingProducts || selectedProductIds.size === 0, onclick: openRelistModal }, [
            relistingProducts ? "执行中..." : "一键修改",
          ]),
          el("button", { disabled: !relistingProducts, onclick: stopRelistProducts }, ["终止修改"]),
        ]),
      ]),
      el("span", { class: "badge", text: `${products.length} 个商品` }),
    ]),
    el("div", { class: "panel-body" }, [
      el("div", { class: "product-toolbar" }, [
        el("input", {
          id: "product-id-query",
          class: "product-id-query",
          placeholder: "商品ID",
          value: productIdQuery,
          oninput: (event) => {
            productIdQuery = event.target.value.trim();
          },
        }),
        el("button", { class: "primary", onclick: queryProduct }, ["查询"]),
        statusSelect(),
      ]),
      renderProductTable(),
      renderPager(),
      renderRelistModal(),
      renderImagePreviewModal(),
    ]),
  ]);
}

function renderProductTable() {
  const pageRows = pagedProducts();
  return renderTable({
    rows: pageRows,
    emptyText: "暂无商品。选择店铺后点击“获取商品ID”。",
    className: "product-table",
    columns: [
      {
        title: "",
        className: "check-cell",
        width: "3%",
        renderHeader: () => renderPageCheck(),
        render: (product) =>
          el("input", {
            class: "row-check",
            type: "checkbox",
            disabled: !isSelectableProduct(product),
            checked: isSelectableProduct(product) && selectedProductIds.has(product.product_id),
            onchange: (event) => toggleProductFromRow(product, event),
          }),
      },
      { title: "ID", width: "4%", render: (_product, index) => String((currentPage - 1) * pageSize + index + 1) },
      {
        title: "主图",
        width: "8%",
        render: (product) => renderProductThumb(product.main_image_url),
      },
      { title: "PXI", width: "5%", render: (product) => formatPxiScore(product.pxi_score) },
      { title: "商品ID", key: "product_id", width: "11%" },
      { title: "标题", key: "title", width: "20%" },
      { title: "状态", width: "9%", render: (product) => formatStatus(product.status) },
      { title: "价格", width: "8%", render: (product) => formatPrice(product.price) },
      { title: "库存", key: "stock", width: "8%", renderHeader: () => sortHeader("库存", "stock") },
      { title: "累计销量", key: "total_sales", width: "9%", renderHeader: () => sortHeader("累计销量", "total_sales") },
      { title: "30日销量", key: "sales_30d", width: "9%", renderHeader: () => sortHeader("30日销量", "sales_30d") },
      {
        title: "最近更新时间",
        width: "11%",
        render: (product) => formatTime(product.last_platform_updated_at || product.updated_at),
        titleValue: (product) => formatTime(product.last_platform_updated_at || product.updated_at),
      },
    ],
  });
}

async function fetchProductList() {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  const runId = ++fetchRunId;
  activeSyncId = `product-sync-${Date.now()}-${runId}`;
  fetchingProducts = true;
  stopRequested = false;
  const taskId = startTask("正在获取商品ID", shopLabel(selectedShop));
  addLog("info", "开始获取商品ID", shopLabel(selectedShop));
  addLog("info", "并发抓取商品", "仓库中 / 出售中，固定 60 条/页");
  await window.renderActiveModule();
  try {
    const result = await api.post("/products/sync", { platform, shop_id, sync_id: activeSyncId });
    if (stopRequested || runId !== fetchRunId) {
      addLog("info", "停止获取商品ID", "已忽略停止后返回的数据");
      return;
    }
    Object.values(result.tabs || {}).forEach((tab) => {
      addLog("info", `完成${tab.label}`, `${tab.pages} 页，${tab.count} 条`);
    });
    products = await loadProducts();
    currentPage = 1;
    const statusText = result.cancelled ? "已停止" : "完成";
    addLog("success", "结束获取商品ID", `${statusText}，新增 ${result.inserted}，更新 ${result.updated}，标记删除 ${result.deleted}，共 ${result.count} 个商品`);
  } catch (error) {
    if (stopRequested || runId !== fetchRunId) return;
    addLog("error", "获取商品ID失败", error.message);
    alert(error.message);
  } finally {
    if (runId === fetchRunId) {
      fetchingProducts = false;
      stopRequested = false;
      endTask(taskId);
      await window.renderActiveModule();
    }
  }
}

async function syncSelectedSkus() {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  const selectableIds = new Set(products.filter(isSelectableProduct).map((product) => product.product_id));
  let productIds = [...selectedProductIds].filter((productId) => selectableIds.has(productId));
  let mode = "勾选更新";
  if (!productIds.length) {
    const existingSkus = await api.get(`/products/skus?${new URLSearchParams({ platform, shop_id }).toString()}`);
    const hasSkuIds = new Set(existingSkus.map((sku) => sku.product_id));
    productIds = products
      .filter((product) => product.status !== "deleted" && !hasSkuIds.has(product.product_id))
      .map((product) => product.product_id);
    mode = "自动补齐未获取";
  }
  if (!productIds.length) {
    addLog("success", "同步SKU价/库存", "当前商品都已有 SKU 数据");
    return;
  }
  fetchingSkus = true;
  const taskId = startTask("正在同步SKU价/库存", `${productIds.length} 个商品`);
  const batches = chunk(productIds, 5);
  const totals = { count: 0, inserted: 0, updated: 0, inactive: 0, failed: 0 };
  addLog("info", "开始同步SKU价/库存", `${mode}，${productIds.length} 个商品，${batches.length} 批，每批最多 5 个，随机等待 2-4 秒`);
  await window.renderActiveModule();
  try {
    for (let index = 0; index < batches.length; index += 1) {
      const batch = batches[index];
      addLog("info", "同步SKU价/库存进度", `提交第 ${index + 1}/${batches.length} 批，${batch.length} 个商品`);
      const result = await api.post("/products/skus/sync", {
        platform,
        shop_id,
        product_ids: batch,
        max_workers: 5,
        wait_min_seconds: 2,
        wait_max_seconds: 4,
      });
      totals.count += result.count;
      totals.inserted += result.inserted;
      totals.updated += result.updated;
      totals.inactive += result.inactive;
      totals.failed += result.failed.length;
      addLog(
        result.failed.length ? "error" : "info",
        "同步SKU价/库存进度",
        `完成第 ${index + 1}/${batches.length} 批，SKU ${result.count} 条，新增 ${result.inserted}，更新 ${result.updated}，失效 ${result.inactive}，失败 ${result.failed.length}`,
      );
    }
    addLog(
      totals.failed ? "error" : "success",
      "结束同步SKU价/库存",
      `SKU ${totals.count} 条，新增 ${totals.inserted}，更新 ${totals.updated}，失效 ${totals.inactive}，失败 ${totals.failed}`,
    );
  } catch (error) {
    addLog("error", "同步SKU价/库存失败", error.message);
    alert(error.message);
  } finally {
    fetchingSkus = false;
    endTask(taskId);
    await window.renderActiveModule();
  }
}

async function openRelistModal() {
  if (!selectedProductIds.size) {
    alert("请先勾选商品");
    return;
  }
  relistModalOpen = true;
  await window.renderActiveModule();
}

async function closeRelistModal() {
  relistModalOpen = false;
  await window.renderActiveModule();
}

async function relistSelectedProducts() {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  const productIds = [...selectedProductIds].filter((productId) => products.some((product) => product.product_id === productId && isSelectableProduct(product)));
  if (!productIds.length) {
    alert("没有可上架的勾选商品");
    return;
  }
  relistStock = Math.max(0, Math.floor(normalizeNumber(formValue("relist-stock"), relistStock)));
  relistStockMode = formValue("relist-stock-mode") || "per_sku";
  relistEditPrice = Boolean(document.getElementById("relist-edit-price")?.checked);
  relistUpdateInventory = Boolean(document.getElementById("relist-update-inventory")?.checked);
  relistUpshelf = Boolean(document.getElementById("relist-upshelf")?.checked);
  relistDryRun = Boolean(document.getElementById("relist-dry-run")?.checked);
  if (!relistEditPrice && !relistUpdateInventory && !relistUpshelf) {
    alert("请至少勾选一个修改动作");
    return;
  }
  relistModalOpen = false;
  relistingProducts = true;
  relistStopRequested = false;
  const taskId = startTask("正在一键修改", `${productIds.length} 个商品`);
  addLog("info", "一键修改前检测", `检测 ${productIds.length} 个商品的Cookie、SKU、正常价和计划库存`);
  await window.renderActiveModule();
  try {
    const checkResult = await api.post("/products/relist", {
      platform,
      shop_id,
      product_ids: productIds,
      unified_stock: relistStock,
      stock_mode: relistStockMode,
      edit_price: relistEditPrice,
      update_inventory: relistUpdateInventory,
      upshelf: relistUpshelf,
      dry_run: true,
      wait_min_seconds: 0,
      wait_max_seconds: 0,
    });
    logRelistPrecheckDetails(checkResult);
    if (checkResult.failed_count || checkResult.skipped_count) {
      alert(`一键修改前检测未通过：失败${checkResult.failed_count}，跳过${checkResult.skipped_count}。请先看日志处理。`);
      return;
    }
    addLog("success", "一键修改前检测通过", `商品${productIds.length}个，可以执行`);
  } catch (error) {
    addLog("error", "一键修改前检测失败", error.message);
    alert(error.message);
    return;
  } finally {
    if (!relistingProducts) await window.renderActiveModule();
  }
  if (relistDryRun) {
    addLog("success", "只模拟不提交完成", "检测通过，未向淘宝提交任何修改");
    relistingProducts = false;
    await window.renderActiveModule();
    return;
  }
  addLog("info", "开始一键修改", `商品${productIds.length}个，${modifyFlowText(relistEditPrice, relistUpdateInventory, relistUpshelf)}，库存${relistStock}，模式${relistStockMode}${relistDryRun ? "，只模拟不提交" : ""}`);
  await window.renderActiveModule();
  const totals = { success_count: 0, failed_count: 0, skipped_count: 0 };
  try {
    for (let index = 0; index < productIds.length; index += 1) {
      if (relistStopRequested) {
        addLog("info", "一键修改已终止", `已处理 ${index}/${productIds.length} 个商品`);
        break;
      }
      const productId = productIds[index];
      addLog("info", "一键修改进度", `${index + 1}/${productIds.length} 开始处理 ${productId}，流程：${modifyFlowText(relistEditPrice, relistUpdateInventory, relistUpshelf)}`);
      await window.renderActiveModule();
      const result = await api.post("/products/relist", {
        platform,
        shop_id,
        product_ids: [productId],
        unified_stock: relistStock,
        stock_mode: relistStockMode,
        edit_price: relistEditPrice,
        update_inventory: relistUpdateInventory,
        upshelf: relistUpshelf,
        dry_run: relistDryRun,
        wait_min_seconds: 1,
        wait_max_seconds: 2,
      });
      totals.success_count += result.success_count;
      totals.failed_count += result.failed_count;
      totals.skipped_count += result.skipped_count;
      logRelistDetails(result);
    }
    products = await loadProducts();
    selectedProductIds.clear();
    addLog("success", "结束一键修改", `成功${totals.success_count}，失败${totals.failed_count}，跳过${totals.skipped_count}`);
    if (relistUpshelf && totals.success_count > 0 && !relistDryRun) {
      await refreshShunshouItemsAfterUpshelf(platform, shop_id);
    }
  } catch (error) {
    addLog("error", "一键修改失败", error.message);
    alert(error.message);
  } finally {
    relistingProducts = false;
    relistStopRequested = false;
    endTask(taskId);
    await window.renderActiveModule();
  }
}

function stopRelistProducts() {
  relistStopRequested = true;
  addLog("info", "请求终止一键修改", "当前商品处理完成后停止后续商品");
  window.renderActiveModule();
}

async function refreshShunshouItemsAfterUpshelf(platform, shop_id) {
  const taskId = startTask("正在刷新顺手活动商品", "上架后重新请求活动状态");
  addLog("info", "刷新顺手活动商品", "上架成功后逐个活动请求淘宝活动商品状态，补齐后续报名候选");
  try {
    const activities = await api.get(`/shunshou/activities?${new URLSearchParams({ platform, shop_id, status: "active" }).toString()}`);
    if (!activities.length) {
      addLog("info", "刷新顺手活动商品", "当前没有有效活动ID，跳过");
      return;
    }
    const totals = { count: 0, inserted: 0, updated: 0, inactive: 0 };
    for (let index = 0; index < activities.length; index += 1) {
      const activity = activities[index];
      addLog("info", "刷新活动商品进度", `${index + 1}/${activities.length} 活动 ${activity.activity_id}`);
      const result = await api.post("/shunshou/activity-items/sync", {
        platform,
        shop_id,
        activity_id: activity.activity_id,
        cross_shop: false,
        auction_status: 0,
      });
      totals.count += result.count || 0;
      totals.inserted += result.inserted || 0;
      totals.updated += result.updated || 0;
      totals.inactive += result.inactive || 0;
    }
    addLog("success", "顺手活动商品已刷新", `活动${activities.length}个，商品${totals.count}条，新增${totals.inserted}，更新${totals.updated}，失效${totals.inactive}`);
  } catch (error) {
    addLog("error", "刷新顺手活动商品失败", error.message);
  } finally {
    endTask(taskId);
  }
}

function chunk(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

async function queryProduct() {
  productIdQuery = formValue("product-id-query").trim();
  statusFilter = formValue("product-status-filter");
  products = await loadProducts();
  currentPage = 1;
  addLog("info", "查询商品", [productIdQuery || "全部商品", statusLabel(statusFilter)].filter(Boolean).join(" / "));
  await window.renderActiveModule();
}

function stopFetchProducts() {
  stopRequested = true;
  fetchRunId += 1;
  fetchingProducts = false;
  if (activeSyncId) {
    api.post(`/products/sync/${encodeURIComponent(activeSyncId)}/cancel`).catch(() => {});
  }
  addLog("info", "请求停止获取商品ID", "当前请求完成后停止");
  window.renderActiveModule();
}

async function loadProducts() {
  if (!selectedShop) return [];
  const [platform, shop_id] = selectedShop.split("::");
  const params = new URLSearchParams({ platform, shop_id });
  if (productIdQuery) params.set("product_id", productIdQuery);
  if (statusFilter) params.set("status", statusFilter);
  return api.get(`/products?${params.toString()}`);
}

function shopSelect(shops) {
  return el(
    "select",
    {
      id: "product-shop",
      class: "ui-select product-shop-select",
      value: selectedShop,
      onchange: async (event) => {
        selectedShop = event.target.value;
        productIdQuery = "";
        products = await loadProducts();
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
      id: "product-status-filter",
      class: "ui-select product-status-filter",
      value: statusFilter,
      onchange: async (event) => {
        statusFilter = event.target.value;
        products = await loadProducts();
        currentPage = 1;
        await window.renderActiveModule();
      },
    },
    [
      el("option", { value: "", selected: statusFilter === "", text: "有效商品" }),
      el("option", { value: "onsale", selected: statusFilter === "onsale", text: "出售中" }),
      el("option", { value: "warehouse", selected: statusFilter === "warehouse", text: "仓库中" }),
      el("option", { value: "deleted", selected: statusFilter === "deleted", text: "已删除" }),
      el("option", { value: "all", selected: statusFilter === "all", text: "全部状态" }),
    ],
  );
}

function renderPageCheck() {
  const pageRows = pagedProducts();
  const selectableRows = pageRows.filter(isSelectableProduct);
  const checked = selectableRows.length > 0 && selectableRows.every((product) => selectedProductIds.has(product.product_id));
  return el("input", {
    class: "row-check",
    type: "checkbox",
    disabled: selectableRows.length === 0,
    checked,
    onchange: (event) => togglePageProducts(selectableRows, event.target.checked),
  });
}

function toggleProduct(product, checked) {
  if (!isSelectableProduct(product)) {
    selectedProductIds.delete(product.product_id);
    return;
  }
  if (checked) selectedProductIds.add(product.product_id);
  else selectedProductIds.delete(product.product_id);
}

function toggleProductFromRow(product, event) {
  const checked = Boolean(event.target.checked);
  if (event.shiftKey && lastCheckedProductId) {
    toggleProductRange(lastCheckedProductId, product.product_id, checked);
  } else {
    toggleProduct(product, checked);
  }
  lastCheckedProductId = product.product_id;
  updateRelistButtonState();
}

function toggleProductRange(fromProductId, toProductId, checked) {
  const pageRows = pagedProducts().filter(isSelectableProduct);
  const fromIndex = pageRows.findIndex((product) => product.product_id === fromProductId);
  const toIndex = pageRows.findIndex((product) => product.product_id === toProductId);
  if (fromIndex < 0 || toIndex < 0) {
    const product = pageRows.find((row) => row.product_id === toProductId);
    if (product) toggleProduct(product, checked);
    return;
  }
  const start = Math.min(fromIndex, toIndex);
  const end = Math.max(fromIndex, toIndex);
  pageRows.slice(start, end + 1).forEach((row) => toggleProduct(row, checked));
  document.querySelectorAll(".product-table tbody .row-check").forEach((checkbox, index) => {
    const row = pageRows[index];
    if (row && index >= start && index <= end) checkbox.checked = checked;
  });
}

function updateRelistButtonState() {
  const button = document.getElementById("product-relist-button");
  if (button) button.disabled = relistingProducts || selectedProductIds.size === 0;
}

async function togglePageProducts(rows, checked) {
  rows.forEach((product) => toggleProduct(product, checked));
  lastCheckedProductId = "";
  await window.renderActiveModule();
}

function isSelectableProduct(product) {
  return product?.status !== "deleted";
}

function renderPager() {
  const totalPages = Math.max(1, Math.ceil(products.length / pageSize));
  if (currentPage > totalPages) currentPage = totalPages;
  return el("div", { class: "pager" }, [
    el("span", { class: "muted", text: `共 ${products.length} 条` }),
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

function pagedProducts() {
  const sortedProducts = sortedRows();
  const start = (currentPage - 1) * pageSize;
  return sortedProducts.slice(start, start + pageSize);
}

function sortedRows() {
  if (!sortKey) return products;
  const direction = sortDirection === "asc" ? 1 : -1;
  return [...products].sort((a, b) => {
    const left = Number(a[sortKey] || 0);
    const right = Number(b[sortKey] || 0);
    return (left - right) * direction;
  });
}

function sortHeader(label, key) {
  const active = sortKey === key;
  const indicator = active ? (sortDirection === "asc" ? " ↑" : " ↓") : "";
  return el(
    "button",
    {
      class: active ? "sort-header active" : "sort-header",
      title: `按${label}排序`,
      onclick: () => toggleSort(key),
    },
    [`${label}${indicator}`],
  );
}

async function toggleSort(key) {
  if (sortKey === key) {
    sortDirection = sortDirection === "asc" ? "desc" : "asc";
  } else {
    sortKey = key;
    sortDirection = "desc";
  }
  currentPage = 1;
  await window.renderActiveModule();
}

function shopLabel(value) {
  const shop = shopOptions.find((item) => `${item.platform}::${item.shop_id}` === value);
  return shop?.shop_name || value || "";
}

function renderProductThumb(url) {
  return renderThumbButton(url, { onOpen: openImagePreview });
}

function renderImagePreviewModal() {
  return renderImagePreview({ url: previewImageUrl, onClose: closeImagePreview });
}

function renderRelistModal() {
  return el("div", { class: relistModalOpen ? "modal-mask open" : "modal-mask", onclick: closeRelistModal }, [
    el("div", { class: "modal relist-modal", onclick: (event) => event.stopPropagation() }, [
      el("div", { class: "modal-header" }, [
        el("strong", { text: "一键修改" }),
        el("button", { class: "ghost", onclick: closeRelistModal }, ["关闭"]),
      ]),
      el("div", { class: "modal-body" }, [
        el("div", { class: "relist-options" }, [
          el("label", { class: "relist-check" }, [
            el("input", { id: "relist-edit-price", type: "checkbox", checked: relistEditPrice }),
            el("span", { text: "改价格" }),
          ]),
          el("label", { class: "relist-check" }, [
            el("input", { id: "relist-update-inventory", type: "checkbox", checked: relistUpdateInventory }),
            el("span", { text: "改库存" }),
          ]),
          el("label", { class: "relist-check" }, [
            el("input", { id: "relist-upshelf", type: "checkbox", checked: relistUpshelf }),
            el("span", { text: "上架" }),
          ]),
          el("div", { class: "relist-field" }, [
            el("label", { for: "relist-stock", text: "库存" }),
            el("input", { id: "relist-stock", type: "number", min: "0", value: String(relistStock) }),
          ]),
          el("div", { class: "relist-field" }, [
            el("label", { for: "relist-stock-mode", text: "库存模式" }),
            el(
              "select",
              { id: "relist-stock-mode", class: "ui-select", value: relistStockMode },
              [
                el("option", { value: "per_sku", selected: relistStockMode === "per_sku", text: "每个SKU同库存" }),
                el("option", { value: "total_split", selected: relistStockMode === "total_split", text: "总库存拆分到SKU" }),
              ],
            ),
          ]),
          el("label", { class: "relist-check" }, [
            el("input", { id: "relist-dry-run", type: "checkbox", checked: relistDryRun }),
            el("span", { text: "只模拟不提交" }),
          ]),
        ]),
        el("div", { class: "modal-actions" }, [
          el("button", { onclick: closeRelistModal }, ["取消"]),
          el("button", { class: "primary", disabled: relistingProducts, onclick: relistSelectedProducts }, [
            relistingProducts ? "执行中..." : "执行",
          ]),
        ]),
      ]),
    ]),
  ]);
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
  if (status === "onsale" || status === "active") return "出售中";
  if (status === "instock" || status === "warehouse" || status === "draft") return "仓库中";
  return status || "";
}

function statusLabel(status) {
  if (status === "onsale") return "出售中";
  if (status === "warehouse") return "仓库中";
  if (status === "deleted") return "已删除";
  if (status === "all") return "全部状态";
  return "";
}

function formatPrice(value) {
  const price = Number(value || 0);
  return price ? price.toFixed(2) : "0.00";
}

function formatPxiScore(value) {
  const score = Number(value || 0);
  if (!Number.isFinite(score) || score <= 0) return "0";
  return String(Math.round(score * 10) / 10).replace(/\.0$/, "");
}

function logRelistDetails(result) {
  (result.success_items || []).slice(0, 20).forEach((row) => {
    addLog("info", "一键修改成功明细", `${row.product_id}：${relistStageSummary(row)}，${relistPricePlanSummary(row)}，SKU ${row.sku_count}，库存 ${row.total_stock}`);
  });
  (result.failed_items || []).slice(0, 20).forEach((row) => {
    addLog("error", "一键修改失败明细", `${row.product_id}：${row.failed_stage || ""} ${row.error_message || ""}，${relistPricePlanSummary(row)}`);
  });
  (result.skipped_items || []).slice(0, 20).forEach((row) => {
    addLog("info", "一键修改跳过明细", `${row.product_id}：${row.reason || ""}`);
  });
}

function logRelistPrecheckDetails(result) {
  (result.success_items || []).slice(0, 20).forEach((row) => {
    addLog("info", "修改前检测通过", `${row.product_id}：${relistPricePlanSummary(row)}，SKU ${row.sku_count}，计划库存 ${row.total_stock}`);
  });
  (result.failed_items || []).slice(0, 20).forEach((row) => {
    addLog("error", "修改前检测失败", `${row.product_id}：${row.failed_stage || ""} ${row.error_message || ""}`);
  });
  (result.skipped_items || []).slice(0, 20).forEach((row) => {
    addLog("error", "修改前检测跳过", `${row.product_id}：${row.reason || ""}`);
  });
}

function relistStageSummary(row) {
  const editAttempts = row.edit_price_result?.attempts || 0;
  const inventoryAttempts = row.inventory_result?.attempts || 0;
  const upshelfAttempts = row.upshelf_result?.attempts || 0;
  return `改价${editAttempts || "-"}次 / 库存${inventoryAttempts || "-"}次 / 上架${upshelfAttempts || "-"}次`;
}

function modifyFlowText(editPrice, updateInventory, upshelf) {
  return [
    editPrice ? "改价格" : "",
    updateInventory ? "改库存" : "",
    upshelf ? "上架" : "",
  ].filter(Boolean).join(" -> ") || "未选择动作";
}

function relistPricePlanSummary(row) {
  const itemPrice = row.planned_item_price ?? row.edit_price_result?.planned_item_price;
  const skuPrices = row.planned_sku_prices || row.edit_price_result?.planned_sku_prices || [];
  const skuText = skuPrices
    .slice(0, 4)
    .map((sku) => `${sku.sku_id || sku.skuId}:${formatPrice(sku.price ?? sku.skuPrice)}`)
    .join(" / ");
  const moreText = skuPrices.length > 4 ? ` 等${skuPrices.length}个SKU` : "";
  return `计划一口价${formatPrice(itemPrice)}${skuText ? `，SKU价 ${skuText}${moreText}` : ""}`;
}
