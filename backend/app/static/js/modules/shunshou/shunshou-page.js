import { api } from "../../api/client.js";
import { el, formValue } from "../../core/dom.js";
import { addLog, endTask, startTask } from "../../core/state.js";
import { renderTable } from "../../components/table.js";
import { renderImagePreview, renderThumbButton } from "../../components/media.js";
import { formatMoney, formatTime, normalizeNumber } from "../../core/format.js";

let selectedShop = "";
let activeTab = "signup";
let activityStatusFilter = "active";
let itemStatusFilter = "active";
let selectedActivityId = "";
let productIdQuery = "";
let activities = [];
let activityItems = [];
let shopsCache = [];
let readiness = null;
let syncingActivities = false;
let syncingItems = false;
let previewImageUrl = "";
let signupLimit = 160;
let pxiMin = 70;
let soldTotalMin = 3;
let signupProductId = "";
let joinedCountMin = "0";
let joinedCountMax = "0";
let signingUp = false;
let signupModalOpen = false;
let previewingSignup = false;
let relistingSignupProducts = false;
let signupModifyStopRequested = false;
let signupModifyModalOpen = false;
let signupModifyEditPrice = true;
let signupModifyUpdateInventory = true;
let signupRelistStock = 3;
let signupRelistStockMode = "per_sku";
let signupPreviewRows = [];
let signupActivityPickerProductId = "";
const selectedSignupKeys = new Set();
const selectedSignupProductIds = new Set();
let lastAutoPriceNoChangeLogAt = 0;

window.autoDetectShunshouSignupPriceChanges = autoDetectSignupPriceChanges;

export async function renderShunshouPage(container) {
  const shops = await api.get("/shops");
  shopsCache = shops;
  if (selectedShop) {
    readiness = await loadReadiness();
    activities = await loadActivities();
    if (!selectedActivityId && activities.length) selectedActivityId = activities[0].activity_id;
    activityItems = await loadActivityItems();
  } else {
    readiness = null;
    activities = [];
    activityItems = [];
    selectedActivityId = "";
  }
  container.replaceChildren(renderPanel(shops));
}

function renderPanel(shops) {
  const tabContent = activeTab === "activities" ? renderActivitiesTab() : activeTab === "items" ? renderItemsTab() : renderSignupTab();
  return el("section", { class: "panel" }, [
    el("div", { class: "panel-header" }, [
      el("div", { class: "panel-heading" }, [
        el("div", { class: "panel-title", text: "顺手报名工作台" }),
        el("div", { class: "actions" }, [
          shopSelect(shops),
          el("button", { class: "primary", disabled: previewingSignup || signingUp || relistingSignupProducts || syncingActivities || syncingItems, onclick: syncWorkbenchChain }, [
            previewingSignup || syncingActivities || syncingItems ? "更新中..." : "一键更新",
          ]),
        ]),
      ]),
      el("span", { class: "badge", text: badgeText() }),
    ]),
    el("div", { class: "panel-body" }, [...tabContent, renderSignupModal(), renderSignupModifyModal(), renderSignupActivityPickerModal(), renderImagePreviewModal()]),
  ]);
}

function renderActivitiesTab() {
  return [
    el("div", { class: "shunshou-toolbar" }, [
      activityStatusSelect(),
      el("button", { class: "primary", disabled: syncingActivities, onclick: syncActivities }, [syncingActivities ? "获取中..." : "获取活动ID"]),
    ]),
    renderActivitiesTable(),
  ];
}

function renderItemsTab() {
  return [
    el("div", { class: "shunshou-toolbar" }, [
      activitySelect(),
      el("input", {
        id: "shunshou-product-id-query",
        class: "shunshou-product-id-query",
        placeholder: "商品ID",
        value: productIdQuery,
        oninput: (event) => {
          productIdQuery = event.target.value.trim();
        },
      }),
      el("button", { class: "primary", onclick: queryItems }, ["查询"]),
      el("button", { disabled: syncingItems || !selectedActivityId, onclick: syncActivityItems }, [syncingItems ? "获取中..." : "获取活动商品"]),
      itemStatusSelect(),
    ]),
    renderItemsTable(),
  ];
}

function renderSignupTab() {
  const signupChanges = buildSignupChanges();
  return [
    renderReadinessPanel(),
    el("div", { class: "signup-summary-row", id: "signup-summary-row", text: signupSummaryText(signupChanges) }),
    el("div", { class: "shunshou-toolbar" }, [
      el("button", { class: "primary", disabled: previewingSignup, onclick: openSignupModal }, [previewingSignup ? "获取中..." : "获取符合条件商品"]),
      el("button", { class: "primary", disabled: signingUp || signupPreviewRows.length === 0, onclick: signupPreviewSelection }, [
        signingUp ? "提交中..." : "提交报名变更",
      ]),
      el("button", { disabled: relistingSignupProducts || signupPreviewRows.length === 0, onclick: openSignupModifyModal }, [
        relistingSignupProducts ? "执行中..." : "一键修改",
      ]),
      el("button", { disabled: !relistingSignupProducts, onclick: stopSignupModify }, ["终止修改"]),
      el("button", { disabled: previewingSignup || signingUp || relistingSignupProducts, onclick: detectSignupPriceChanges }, ["检测报名价变动"]),
      el("button", { disabled: previewingSignup || signingUp || relistingSignupProducts, onclick: updateJoinedSignupPrices }, ["更新已报名价格"]),
      el("button", { disabled: previewingSignup || signingUp || relistingSignupProducts || signupPreviewRows.length === 0, onclick: clearSignupPreviewRows }, ["清空列表"]),
    ]),
    renderSignupPreviewTable(),
  ];
}

function signupSummaryText(signupChanges = buildSignupChanges()) {
  return `预览 ${signupPreviewRows.length} 条，已选商品 ${selectedSignupProductIds.size} 条，活动变更 ${signupChanges.addedCount + signupChanges.removedCount} 项`;
}

function renderReadinessPanel() {
  const checks = readiness?.checks || [];
  if (!checks.length) {
    return el("div", { class: "readiness-panel" }, [
      el("div", { class: "readiness-summary", text: selectedShop ? "正在检测数据准备状态" : "请先选择店铺" }),
    ]);
  }
  const missing = checks.filter((item) => !item.ok);
  const visible = missing.slice(0, 3);
  return el("div", { class: "readiness-panel" }, [
    el("div", { class: "readiness-summary" }, [
      el("strong", { text: readiness.ready ? "数据已就绪" : `缺 ${missing.length} 项` }),
    ]),
    missing.length ? el("div", { class: "readiness-compact" }, visible.map(renderReadinessChip)) : "",
  ]);
}

function renderReadinessChip(item) {
  return el("button", { class: "readiness-chip", title: item.action, onclick: () => handleReadinessAction(item.name) }, [
    `${item.name} ${item.count} · ${readinessActionText(item.name)}`,
  ]);
}

function readinessActionText(name) {
  if (name === "商品列表") return "点1";
  if (name === "SKU") return "点2";
  if (name === "飞书价格") return "点3";
  if (name === "PXI分") return "点4";
  if (name === "活动ID") return "点5";
  if (name === "活动商品") return "点6";
  if (name === "价格状态") return "看候选";
  return "处理";
}

async function handleReadinessAction(name) {
  if (name === "商品列表") {
    await syncProductsFromWorkbench();
    return;
  }
  if (name === "SKU") {
    await syncSkusFromWorkbench();
    return;
  }
  if (name === "飞书价格") {
    await syncFeishuPricesFromWorkbench();
    return;
  }
  if (name === "PXI分") {
    await syncPxiFromWorkbench();
    return;
  }
  if (name === "活动ID") {
    await syncActivities();
    return;
  }
  if (name === "活动商品") {
    await syncAllActivityItems();
    return;
  }
  if (name === "价格状态") {
    await openSignupModal();
  }
}

async function syncWorkbenchChain() {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  addLog("info", "开始一键更新", "商品列表 -> 增量SKU -> PXI分 -> 活动ID -> 活动商品；飞书价格由后台轮询匹配");
  await syncProductsFromWorkbench(false);
  await syncSkusFromWorkbench(false);
  await syncPxiFromWorkbench(false);
  await syncActivities(false);
  await syncAllActivityItems(false);
  readiness = await loadReadiness();
  await window.renderActiveModule();
  addLog("success", "一键更新完成", "已跳过飞书匹配价格，后台轮询会自动全局匹配");
}

async function syncProductsFromWorkbench(render = true) {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  previewingSignup = true;
  const taskId = startTask("正在同步商品列表", shopLabel(selectedShop));
  addLog("info", "开始一键商品列表", "同步出售中/仓库中商品");
  if (render) await window.renderActiveModule();
  try {
    await api.post("/products/sync", { platform, shop_id, sync_id: `workbench-products-${Date.now()}` });
    readiness = await loadReadiness();
    addLog("success", "一键商品列表完成", "商品列表已同步；需要刷新SKU价/库存请点一键SKU价/库存");
  } catch (error) {
    addLog("error", "一键商品列表失败", error.message);
    alert(error.message);
  } finally {
    previewingSignup = false;
    endTask(taskId);
    if (render) await window.renderActiveModule();
  }
}

async function syncSkusFromWorkbench(render = true) {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  previewingSignup = true;
  const taskId = startTask("正在同步SKU价/库存", shopLabel(selectedShop));
  addLog("info", "开始一键SKU价/库存", "增量补齐缺失的SKU编码、当前价和库存");
  if (render) await window.renderActiveModule();
  try {
    const products = await api.get(`/products?${new URLSearchParams({ platform, shop_id }).toString()}`);
    const existingSkus = await api.get(`/products/skus?${new URLSearchParams({ platform, shop_id }).toString()}`);
    const hasSkuIds = new Set(existingSkus.map((sku) => String(sku.product_id)));
    const productIds = products
      .filter((product) => product.status !== "deleted" && !hasSkuIds.has(String(product.product_id)))
      .map((product) => product.product_id);
    if (!productIds.length) {
      addLog("success", "一键SKU价/库存", "当前商品都已有 SKU 数据");
      return;
    }
    const batches = chunk(productIds, 5);
    const totals = { count: 0, inserted: 0, updated: 0, inactive: 0, failed: 0 };
    for (let index = 0; index < batches.length; index += 1) {
      addLog("info", "一键SKU价/库存进度", `${index + 1}/${batches.length} 批，${batches[index].length} 个商品`);
      const result = await api.post("/products/skus/sync", {
        platform,
        shop_id,
        product_ids: batches[index],
        max_workers: 5,
        wait_min_seconds: 2,
        wait_max_seconds: 4,
      });
      totals.count += result.count || 0;
      totals.inserted += result.inserted || 0;
      totals.updated += result.updated || 0;
      totals.inactive += result.inactive || 0;
      totals.failed += result.failed?.length || 0;
    }
    readiness = await loadReadiness();
    addLog("success", "一键SKU价/库存完成", `SKU ${totals.count} 条，新增${totals.inserted}，更新${totals.updated}，失效${totals.inactive}，失败${totals.failed}`);
  } catch (error) {
    addLog("error", "一键SKU价/库存失败", error.message);
    alert(error.message);
  } finally {
    previewingSignup = false;
    endTask(taskId);
    if (render) await window.renderActiveModule();
  }
}

async function syncFeishuPricesFromWorkbench(render = true) {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  previewingSignup = true;
  const taskId = startTask("正在飞书匹配价格", shopLabel(selectedShop));
  addLog("info", "开始飞书匹配价格", "按 SKU 编码回填正常售价和顺手报名价；无顺手报名价的SKU报名时自动忽略");
  if (render) await window.renderActiveModule();
  try {
    const result = await api.post("/products/skus/prices/sync");
    readiness = await loadReadiness();
    addLog("success", "飞书匹配价格完成", `更新SKU ${result.updated_global_skus + result.updated_shop_skus} 条，警告 ${result.warnings.length}`);
  } catch (error) {
    addLog("error", "飞书匹配价格失败", error.message);
    alert(error.message);
  } finally {
    previewingSignup = false;
    endTask(taskId);
    if (render) await window.renderActiveModule();
  }
}

function renderActivitiesTable() {
  return renderTable({
    rows: activities,
    emptyText: "暂无活动。选择店铺后点击“获取活动ID”。",
    className: "product-table",
    columns: [
      { title: "ID", width: "4%", render: (_row, index) => String(index + 1) },
      { title: "活动ID", key: "activity_id", width: "15%" },
      { title: "活动名", key: "activity_name", width: "18%" },
      { title: "状态", key: "activity_status_text", width: "8%" },
      { title: "报名数", width: "8%", render: (row) => formatCapacity(row) },
      { title: "开始时间", key: "start_time", width: "12%" },
      { title: "结束时间", key: "end_time", width: "12%" },
      { title: "同步状态", width: "8%", render: (row) => formatSyncStatus(row.sync_status) },
      { title: "操作", className: "action-cell", width: "15%", render: (row) => renderActivityActions(row) },
    ],
  });
}

function renderItemsTable() {
  return renderTable({
    rows: activityItems,
    emptyText: "暂无活动商品。选择活动后点击“获取活动商品”。",
    className: "product-table",
    columns: [
      { title: "ID", width: "4%", render: (_row, index) => String(index + 1) },
      { title: "主图", width: "7%", render: (row) => renderProductThumb(row.product_image_url) },
      { title: "活动ID", key: "activity_id", width: "13%" },
      { title: "商品ID", key: "product_id", width: "13%" },
      { title: "商品标题", width: "24%", render: (row) => row.product_title || row.item_title || "" },
      { title: "报名状态", key: "activity_item_status", width: "10%" },
      { title: "提示", key: "warn_message", width: "17%" },
      { title: "同步状态", width: "7%", render: (row) => formatSyncStatus(row.sync_status) },
      {
        title: "最近更新时间",
        width: "5%",
        render: (row) => formatTime(row.last_platform_updated_at || row.updated_at),
        titleValue: (row) => formatTime(row.last_platform_updated_at || row.updated_at),
      },
    ],
  });
}

function renderSignupPreviewTable() {
  return renderTable({
    rows: signupPreviewRows,
    emptyText: "暂无待报名商品。点击获取符合条件商品后再勾选报名。",
    className: "product-table",
    columns: signupPreviewColumns(),
  });
}

function signupPreviewColumns() {
  return [
    {
      title: "",
      className: "check-cell",
      width: "4%",
      renderHeader: () => renderSignupPageCheck(),
      render: (row) =>
        el("input", {
          class: "row-check signup-row-check",
          type: "checkbox",
          checked: selectedSignupProductIds.has(String(row.product_id)),
          onchange: (event) => {
            toggleSignupProduct(row, event.target.checked);
            updateSignupSelectionUi();
          },
        }),
    },
    { title: "ID", width: "4%", render: (_row, index) => String(index + 1) },
    { title: "主图", width: "7%", render: (row) => renderProductThumb(row.image_url) },
    { title: "商品ID", key: "product_id", width: "14%" },
    { title: "标题", key: "title", width: "25%" },
    { title: "价格检查", width: "12%", render: (row) => renderSignupPriceStatus(row), titleValue: (row) => signupPriceStatusTitle(row) },
    { title: "报名价", width: "10%", render: (row) => formatSignupPrice(row) },
    { title: "活动", width: "10%", render: (row) => renderSignupActivityChoices(row) },
    { title: "PXI", key: "pxi_score", width: "5%" },
    { title: "已报", key: "joined_count", width: "5%" },
  ];
}

async function syncActivities(render = true) {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  syncingActivities = true;
  const taskId = startTask("正在获取顺手活动ID", shopLabel(selectedShop));
  addLog("info", "开始获取顺手活动ID", shopLabel(selectedShop));
  if (render) await window.renderActiveModule();
  try {
    const result = await api.post("/shunshou/activities/sync", { platform, shop_id, activity_status: "null" });
    activities = await loadActivities();
    readiness = await loadReadiness();
    if (!selectedActivityId && activities.length) selectedActivityId = activities[0].activity_id;
    addLog("success", "结束获取顺手活动ID", `新增 ${result.inserted}，更新 ${result.updated}，失效 ${result.inactive}，共 ${result.count} 个活动`);
  } catch (error) {
    addLog("error", "获取顺手活动ID失败", error.message);
    alert(error.message);
  } finally {
    syncingActivities = false;
    endTask(taskId);
    if (render) await window.renderActiveModule();
  }
}

async function deleteActivity(row) {
  if (!confirm(`确认删除活动 ${row.activity_id}？删除后后续同步不会恢复显示。`)) return;
  await api.delete(`/shunshou/activities/${row.id}`);
  activities = await loadActivities();
  if (selectedActivityId === row.activity_id) {
    selectedActivityId = activities[0]?.activity_id || "";
    activityItems = await loadActivityItems();
  }
  addLog("success", "删除顺手活动ID", row.activity_id);
  await window.renderActiveModule();
}

async function openSignupModal() {
  signupModalOpen = true;
  await window.renderActiveModule();
}

async function closeSignupModal() {
  signupModalOpen = false;
  await window.renderActiveModule();
}

async function previewSignupCandidates(render = true) {
  const config = readSignupConfig();
  if (!config) return;
  previewingSignup = true;
  signupModalOpen = false;
  const taskId = startTask("正在获取符合条件商品", shopLabel(selectedShop));
  addLog("info", "获取符合条件商品", `PXI>${pxiMin} / 销量>=${soldTotalMin} / 按商品手动选择活动`);
  if (render) await window.renderActiveModule();
  try {
    const result = await api.post("/shunshou/signup/preview", config);
    signupPreviewRows = result.rows || [];
    selectedSignupKeys.clear();
    selectedSignupProductIds.clear();
    signupPreviewRows.forEach((row) => {
      (row.activities || []).forEach((activity) => {
        if (activity.selected !== false) selectedSignupKeys.add(signupActivityKey(row, activity));
      });
    });
    readiness = await loadReadiness();
    addLog("success", "符合条件商品获取完成", `候选${result.candidate_count}，可选择活动${result.assignment_count}，跳过${(result.skipped_items || []).length}`);
  } catch (error) {
    addLog("error", "获取符合条件商品失败", error.message);
    alert(error.message);
  } finally {
    previewingSignup = false;
    endTask(taskId);
    if (render) await window.renderActiveModule();
  }
}

async function openSignupModifyModal() {
  signupModifyModalOpen = true;
  await window.renderActiveModule();
}

async function closeSignupModifyModal() {
  signupModifyModalOpen = false;
  await window.renderActiveModule();
}

async function relistSignupPreviewProducts() {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  signupModifyEditPrice = Boolean(document.getElementById("signup-modify-edit-price")?.checked);
  signupModifyUpdateInventory = Boolean(document.getElementById("signup-modify-update-inventory")?.checked);
  signupRelistStock = Math.max(0, Math.floor(normalizeNumber(formValue("signup-modify-stock"), signupRelistStock)));
  signupRelistStockMode = formValue("signup-modify-stock-mode") || "per_sku";
  if (!signupModifyEditPrice && !signupModifyUpdateInventory) {
    alert("请至少勾选一个修改动作");
    return;
  }
  const sourceRows = selectedSignupProductIds.size
    ? signupPreviewRows.filter((row) => selectedSignupProductIds.has(String(row.product_id)))
    : signupModifyEditPrice
      ? signupPreviewRows.filter((row) => Number(row.price_mismatch_count || 0) > 0)
      : signupPreviewRows;
  const missingRows = sourceRows.filter((row) => Number(row.missing_normal_price_count || 0) > 0);
  if (signupModifyEditPrice && missingRows.length) {
    alert(`有 ${missingRows.length} 条商品缺正常售价，不能自动改价。请先同步飞书价格。`);
    return;
  }
  const productContextMap = buildProductContextMap(sourceRows);
  const productIds = [...productContextMap.keys()];
  if (!productIds.length) {
    alert("当前没有可执行的商品");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  signupModifyModalOpen = false;
  relistingSignupProducts = true;
  signupModifyStopRequested = false;
  const taskId = startTask("正在一键修改候选商品", `${productIds.length} 个商品`);
  addLog("info", "开始一键修改", `候选${sourceRows.length}条，去重商品${productIds.length}个，${modifyFlowText(signupModifyEditPrice, signupModifyUpdateInventory, false)}，库存${signupRelistStock}，模式${signupRelistStockMode}`);
  await window.renderActiveModule();
  const totals = { success_count: 0, failed_count: 0, skipped_count: 0 };
  try {
    for (let index = 0; index < productIds.length; index += 1) {
      if (signupModifyStopRequested) {
        addLog("info", "一键修改已终止", `已处理 ${index}/${productIds.length} 个商品`);
        break;
      }
      const productId = productIds[index];
      const contextText = productContextText(productContextMap.get(String(productId)));
      const planText = productPlanText(productId, signupRelistStock, signupRelistStockMode);
      addLog("info", "一键修改进度", `${index + 1}/${productIds.length} 开始处理 ${productId}${contextText}，流程：${modifyFlowText(signupModifyEditPrice, signupModifyUpdateInventory, false)}${planText}`);
      await window.renderActiveModule();
      const result = await api.post("/products/relist", {
        platform,
        shop_id,
        product_ids: [productId],
        unified_stock: signupRelistStock,
        stock_mode: signupRelistStockMode,
        edit_price: signupModifyEditPrice,
        update_inventory: signupModifyUpdateInventory,
        upshelf: false,
        dry_run: false,
        wait_min_seconds: 1,
        wait_max_seconds: 2,
      });
      totals.success_count += result.success_count;
      totals.failed_count += result.failed_count;
      totals.skipped_count += result.skipped_count;
      logRelistDetails(result, productContextMap);
    }
    addLog("success", "结束一键修改", `成功${totals.success_count}，失败${totals.failed_count}，跳过${totals.skipped_count}`);
    readiness = await loadReadiness();
    if (signupModifyEditPrice && totals.failed_count === 0) addLog("info", "下一步", "请重新点击“获取符合条件商品”，刷新当前价后再报名");
  } catch (error) {
    addLog("error", "一键修改失败", error.message);
    alert(error.message);
  } finally {
    relistingSignupProducts = false;
    signupModifyStopRequested = false;
    endTask(taskId);
    await window.renderActiveModule();
  }
}

function stopSignupModify() {
  signupModifyStopRequested = true;
  addLog("info", "请求终止一键修改", "当前商品处理完成后停止后续商品");
  window.renderActiveModule();
}

async function clearSignupPreviewRows() {
  signupPreviewRows = [];
  selectedSignupProductIds.clear();
  selectedSignupKeys.clear();
  signupActivityPickerProductId = "";
  addLog("info", "清空报名商品列表", "下次检测报名价变动将按全部已报名商品扫描");
  await window.renderActiveModule();
}

async function detectSignupPriceChanges() {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const productIds = selectedSignupProductIds.size
    ? [...selectedSignupProductIds]
    : signupPreviewRows.map((row) => String(row.product_id || "")).filter(Boolean);
  const [platform, shop_id] = selectedShop.split("::");
  const scopeText = selectedSignupProductIds.size
    ? `${productIds.length} 个已勾选商品`
    : productIds.length
      ? `${productIds.length} 个列表商品`
      : "全部已报名商品";
  const taskId = startTask("正在检测报名价变动", scopeText);
  addLog("info", "开始检测报名价变动", `范围：${scopeText}；对比活动当前报名价和飞书顺手报名价`);
  await window.renderActiveModule();
  try {
    const result = await api.post("/shunshou/signup/price-changes/detect", {
      platform,
      shop_id,
      product_ids: productIds,
      cross_shop: false,
      batch_size: 25,
      min_wait_seconds: 0.4,
      max_wait_seconds: 0.8,
    });
    const changedProductIds = applySignupPriceChangeResult(result);
    addLog("success", "检测报名价变动完成", `已报名商品${result.joined_product_count || 0}个，活动${result.activity_count}个，SKU ${result.sku_count}个，变动${result.changed_count}个，可更新${result.can_update_count}个，已自动勾选${changedProductIds.size}个商品`);
    logSignupPriceChangeRows(result.rows || []);
  } catch (error) {
    addLog("error", "检测报名价变动失败", error.message);
    alert(error.message);
  } finally {
    endTask(taskId);
    await window.renderActiveModule();
  }
}

async function autoDetectSignupPriceChanges({ updatedCount = 0 } = {}) {
  if (!selectedShop) return;
  if (previewingSignup || signingUp || relistingSignupProducts || syncingActivities || syncingItems) return;
  if (signupPreviewRows.length && !hasPriceChangePreviewRows()) {
    if (updatedCount > 0) addLog("info", "自动报名价检测跳过", "当前表格是报名候选列表，为避免覆盖选择，请手动清空列表或手动检测");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  try {
    const result = await api.post("/shunshou/signup/price-changes/detect", {
      platform,
      shop_id,
      product_ids: [],
      cross_shop: false,
      batch_size: 25,
      min_wait_seconds: 0.3,
      max_wait_seconds: 0.6,
    });
    if (Number(result.can_update_count || 0) <= 0) {
      if (hasPriceChangePreviewRows()) {
        signupPreviewRows = [];
        selectedSignupProductIds.clear();
        selectedSignupKeys.clear();
        await window.renderActiveModule();
      }
      const now = Date.now();
      if (now - lastAutoPriceNoChangeLogAt > 5 * 60 * 1000) {
        addLog("info", "自动报名价检测完成", `全部已报名商品暂无待更新价格，已报名商品${result.joined_product_count || 0}个`);
        lastAutoPriceNoChangeLogAt = now;
      }
      return;
    }
    const changedProductIds = applySignupPriceChangeResult(result);
    addLog("success", "自动发现报名价变动", `已报名商品${result.joined_product_count || 0}个，活动${result.activity_count}个，可更新SKU ${result.can_update_count}个，已自动勾选${changedProductIds.size}个商品`);
    await window.renderActiveModule();
  } catch (error) {
    addLog("error", "自动报名价检测失败", error.message);
  }
}

function applySignupPriceChangeResult(result) {
  const changedProductIds = new Set((result.rows || []).filter((row) => row.changed && row.can_update).map((row) => String(row.product_id)));
  signupPreviewRows = buildSignupPriceChangePreviewRows(result.rows || []);
  selectedSignupKeys.clear();
  selectedSignupProductIds.clear();
  changedProductIds.forEach((productId) => selectedSignupProductIds.add(productId));
  signupPreviewRows.forEach((row) => {
    if (row.preview_mode !== "price_change") return;
    (row.activities || []).forEach((activity) => {
      if (activity.selected !== false) selectedSignupKeys.add(signupActivityKey(row, activity));
    });
  });
  return changedProductIds;
}

async function updateJoinedSignupPrices() {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const assignmentsByActivity = buildPriceChangeUpdateAssignments();
  const productIds = [...selectedSignupProductIds];
  if (!productIds.length) {
    addLog("error", "更新已报名价格失败", "请先勾选商品，或先点击“检测报名价变动”自动勾选变动商品");
    alert("请先勾选要更新已报名价格的商品，或先点击“检测报名价变动”自动勾选。");
    return;
  }
  if (hasPriceChangePreviewRows() && !Object.keys(assignmentsByActivity).length) {
    addLog("error", "更新已报名价格失败", "请在活动列选择至少一个要更新的活动");
    alert("请在活动列选择至少一个要更新价格的活动。");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  const activityCount = Object.keys(assignmentsByActivity).length;
  const taskId = startTask("正在更新已报名价格", `${productIds.length} 个商品${activityCount ? ` / ${activityCount} 个活动` : ""}`);
  addLog("info", "开始更新已报名价格", `商品${productIds.length}个${activityCount ? `，活动${activityCount}个` : ""}；只更新报名价，不改变活动关系`);
  await window.renderActiveModule();
  try {
    const result = await api.post("/shunshou/signup/price-changes/update", {
      platform,
      shop_id,
      product_ids: productIds,
      assignments_by_activity: Object.keys(assignmentsByActivity).length ? assignmentsByActivity : null,
      cross_shop: false,
      batch_size: 25,
      min_wait_seconds: 0.6,
      max_wait_seconds: 1.2,
      dry_run: false,
    });
    addLog("success", "更新已报名价格完成", `提交活动${result.submitted_activity_count}个，更新SKU ${result.updated_sku_count}个，跳过${result.skipped_count}个`);
    logSignupPriceUpdateRows(result);
    await verifySignupPriceUpdateResult({ platform, shop_id, productIds, assignmentsByActivity });
  } catch (error) {
    addLog("error", "更新已报名价格失败", error.message);
    alert(error.message);
  } finally {
    endTask(taskId);
    await window.renderActiveModule();
  }
}

async function signupPreviewSelection() {
  const config = readSignupConfig();
  if (!config) return;
  const changes = buildSignupChanges();
  if (!changes.changedRows.length) {
    alert("没有报名变更。请先在活动弹窗里勾选要报名的活动，或取消已报名活动。");
    return;
  }
  const blockedRows = changes.addedRows.filter(needsPriceFix);
  if (blockedRows.length) {
    alert(`有 ${blockedRows.length} 条商品需要先恢复正常价。请点击“恢复正常价”后重新获取符合条件商品，再报名。`);
    addLog("error", "报名前价格检查", `拦截 ${blockedRows.length} 条需改价/缺正常价商品`);
    return;
  }
  signingUp = true;
  const taskId = startTask("正在报名检测/提交", `${changes.changedRows.length} 条变更`);
  addLog("info", "报名前检测", `新增${changes.addedCount}，取消${changes.removedCount}，确认PXI、活动状态和价格`);
  await window.renderActiveModule();
  try {
    const check = await api.post("/shunshou/signup/check", {
      ...config,
      assignments_by_activity: changes.assignments,
      remove_assignments_by_activity: changes.removals,
    });
    const failedRows = check.failed_rows || [];
    if (failedRows.length) {
      const detailText = failedRows.slice(0, 20).map((row) => `${row.product_id}/${row.activity_id}:${row.reason || "no reason"}`).join("; ");
      addLog("error", "报名前检测失败", `${failedRows.length} 条：${detailText}`);
      alert(`报名前检测失败：${failedRows.length} 条\n${detailText}`);
      return;
    }
    const missingRows = [];
    if (missingRows.length) {
      const detailText = missingRows.slice(0, 20).map((row) => `${row.product_id}/${row.activity_id}:${row.reason || "no reason"}`).join("; ");
      addLog("error", "报名检测明细", detailText);
      addLog("error", "报名前检测未通过", `${missingRows.length} 条不再是可报名候选：${missingRows.slice(0, 20).map((row) => `${row.product_id}/${row.activity_id}`).join("，")}`);
      alert(`报名前检测未通过：${missingRows.length} 条商品当前不再可报名。请重新点击“获取符合条件商品”。`);
      return;
    }
    addLog("success", "报名前检测通过", `新增${changes.addedCount}，取消${changes.removedCount}，涉及活动 ${changes.activityCount} 个`);
    addLog("info", "开始提交报名变更", `新增${changes.addedCount}，取消${changes.removedCount}，涉及活动 ${changes.activityCount} 个`);
    const result = await api.post("/shunshou/signup", {
      ...config,
      assignments_by_activity: changes.assignments,
      remove_assignments_by_activity: changes.removals,
    });
    activityItems = await loadActivityItems();
    activities = await loadActivities();
    readiness = await loadReadiness();
    addLog(
      "success",
      "结束报名变更",
      `提交活动${result.submitted_activity_count}，新增SKU ${result.submitted_sku_count}，跳过${result.skipped_count}`,
    );
    logSignupResultDetails(result);
    await verifySignupSubmitResult(config, changes, result);
    await previewSignupCandidates(false);
  } catch (error) {
    addLog("error", "报名变更失败", error.message);
    alert(error.message);
  } finally {
    signingUp = false;
    endTask(taskId);
    await window.renderActiveModule();
  }
}

function readSignupConfig() {
  const limit = normalizeSignupLimit(formValue("shunshou-signup-limit") || signupLimit);
  signupLimit = limit;
  pxiMin = normalizeNumber(formValue("shunshou-pxi-min"), 70);
  soldTotalMin = Math.floor(normalizeNumber(formValue("shunshou-sold-min"), 3));
  signupProductId = formValue("shunshou-signup-product-id").trim();
  joinedCountMin = formValue("shunshou-joined-min").trim();
  joinedCountMax = formValue("shunshou-joined-max").trim();
  if (!selectedShop) {
    alert("请先选择店铺");
    return null;
  }
  const [platform, shop_id] = selectedShop.split("::");
  return {
    platform,
    shop_id,
    pxi_min: pxiMin,
    sold_total_min: soldTotalMin,
    product_id: signupProductId || null,
    joined_count_min: joinedCountMin === "" ? 0 : Math.max(0, Math.floor(normalizeNumber(joinedCountMin, 0))),
    joined_count_max: joinedCountMax === "" ? 0 : Math.max(0, Math.floor(normalizeNumber(joinedCountMax, 0))),
    target_activity_count: 1,
    custom_capacity_limit: signupLimit,
    reserve_item_count: 3,
    real_capacity_fallback: 171,
    cross_shop: false,
    batch_size: 25,
    min_wait_seconds: 0.6,
    max_wait_seconds: 1.8,
    dry_run: false,
  };
}

async function syncActivityItems() {
  if (!selectedShop || !selectedActivityId) {
    alert("请先选择店铺和活动");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  syncingItems = true;
  const taskId = startTask("正在获取活动商品", selectedActivityId);
  addLog("info", "开始获取活动商品", `${selectedActivityId} / 固定20条每页`);
  await window.renderActiveModule();
  try {
    const result = await api.post("/shunshou/activity-items/sync", {
      platform,
      shop_id,
      activity_id: selectedActivityId,
      cross_shop: false,
      auction_status: 0,
    });
    activityItems = await loadActivityItems();
    readiness = await loadReadiness();
    addLog("success", "结束获取活动商品", `新增 ${result.inserted}，更新 ${result.updated}，失效 ${result.inactive}，共 ${result.count} 个商品`);
  } catch (error) {
    addLog("error", "获取活动商品失败", error.message);
    alert(error.message);
  } finally {
    syncingItems = false;
    endTask(taskId);
    await window.renderActiveModule();
  }
}

async function syncAllActivityItems(render = true) {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  if (!activities.length) activities = await loadActivities();
  if (!activities.length) {
    alert("请先获取活动ID");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  syncingItems = true;
  const taskId = startTask("正在获取全部活动商品", `${activities.length} 个活动`);
  addLog("info", "开始获取全部活动商品", `${activities.length} 个活动`);
  if (render) await window.renderActiveModule();
  try {
    const totals = { inserted: 0, updated: 0, inactive: 0, count: 0 };
    for (let index = 0; index < activities.length; index += 1) {
      const activity = activities[index];
      addLog("info", "获取活动商品进度", `${index + 1}/${activities.length}，活动 ${activity.activity_id}`);
      const result = await api.post("/shunshou/activity-items/sync", {
        platform,
        shop_id,
        activity_id: activity.activity_id,
        cross_shop: false,
        auction_status: 0,
      });
      totals.inserted += result.inserted;
      totals.updated += result.updated;
      totals.inactive += result.inactive;
      totals.count += result.count;
    }
    activityItems = await loadActivityItems();
    readiness = await loadReadiness();
    addLog("success", "结束获取全部活动商品", `新增 ${totals.inserted}，更新 ${totals.updated}，失效 ${totals.inactive}，共 ${totals.count}`);
  } catch (error) {
    addLog("error", "获取全部活动商品失败", error.message);
    alert(error.message);
  } finally {
    syncingItems = false;
    endTask(taskId);
    if (render) await window.renderActiveModule();
  }
}

async function syncPxiFromWorkbench(render = true) {
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  const [platform, shop_id] = selectedShop.split("::");
  const taskId = startTask("正在获取PXI", shopLabel(selectedShop));
  addLog("info", "开始获取PXI", "工作台自动补齐，固定60条每页");
  if (render) await window.renderActiveModule();
  try {
    const result = await api.post("/pxi/sync", {
      platform,
      shop_id,
      update_date: "",
      range_day: "30d",
      filter_type: "all",
      category: "",
      item_title: "",
      item_id: "",
    });
    readiness = await loadReadiness();
    addLog("success", "结束获取PXI", `新增 ${result.inserted}，更新 ${result.updated}，失效 ${result.inactive}，共 ${result.count}`);
  } catch (error) {
    addLog("error", "获取PXI失败", error.message);
    alert(error.message);
  } finally {
    endTask(taskId);
    if (render) await window.renderActiveModule();
  }
}

async function queryItems() {
  productIdQuery = formValue("shunshou-product-id-query");
  itemStatusFilter = formValue("shunshou-item-status-filter") || "active";
  activityItems = await loadActivityItems();
  addLog("info", "查询活动商品", [selectedActivityId || "全部活动", productIdQuery || "全部商品", statusLabel(itemStatusFilter)].join(" / "));
  await window.renderActiveModule();
}

async function loadActivities() {
  if (!selectedShop) return [];
  const [platform, shop_id] = selectedShop.split("::");
  const params = new URLSearchParams({ platform, shop_id });
  if (activityStatusFilter) params.set("status", activityStatusFilter);
  return api.get(`/shunshou/activities?${params.toString()}`);
}

async function loadActivityItems() {
  if (!selectedShop) return [];
  const [platform, shop_id] = selectedShop.split("::");
  const params = new URLSearchParams({ platform, shop_id });
  if (selectedActivityId) params.set("activity_id", selectedActivityId);
  if (productIdQuery) params.set("product_id", productIdQuery);
  if (itemStatusFilter) params.set("status", itemStatusFilter);
  return api.get(`/shunshou/activity-items?${params.toString()}`);
}

async function loadReadiness() {
  if (!selectedShop) return null;
  const [platform, shop_id] = selectedShop.split("::");
  return api.get(`/shunshou/readiness?${new URLSearchParams({ platform, shop_id }).toString()}`);
}

function chunk(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function shopSelect(shops) {
  return el(
    "select",
    {
      class: "ui-select product-shop-select",
      value: selectedShop,
      onchange: async (event) => {
        selectedShop = event.target.value;
        selectedActivityId = "";
        readiness = await loadReadiness();
        activities = await loadActivities();
        if (activities.length) selectedActivityId = activities[0].activity_id;
        activityItems = await loadActivityItems();
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

function tabButton(id, text) {
  return el("button", {
    class: activeTab === id ? "tab-button active" : "tab-button",
    onclick: async () => {
      activeTab = id;
      if (id === "activities") activities = await loadActivities();
      else if (id === "items") activityItems = await loadActivityItems();
      await window.renderActiveModule();
    },
    text,
  });
}

function activityStatusSelect() {
  return statusSelect("shunshou-activity-status-filter", activityStatusFilter, async (value) => {
    activityStatusFilter = value;
    activities = await loadActivities();
  });
}

function itemStatusSelect() {
  return statusSelect("shunshou-item-status-filter", itemStatusFilter, async (value) => {
    itemStatusFilter = value;
    activityItems = await loadActivityItems();
  });
}

function statusSelect(id, value, onChange) {
  return el(
    "select",
    {
      id,
      class: "ui-select shunshou-status-filter",
      value,
      onchange: async (event) => {
        await onChange(event.target.value);
        await window.renderActiveModule();
      },
    },
    [
      el("option", { value: "active", selected: value === "active", text: "有效数据" }),
      el("option", { value: "inactive", selected: value === "inactive", text: "失效" }),
      el("option", { value: "all", selected: value === "all", text: "全部状态" }),
    ],
  );
}

function activitySelect() {
  return el(
    "select",
    {
      class: "ui-select shunshou-activity-select",
      value: selectedActivityId,
      onchange: async (event) => {
        selectedActivityId = event.target.value;
        activityItems = await loadActivityItems();
        await window.renderActiveModule();
      },
    },
    [
      el("option", { value: "", text: activities.length ? "选择活动" : "请先获取活动ID" }),
      ...activities.map((activity) =>
        el("option", {
          value: activity.activity_id,
          selected: selectedActivityId === activity.activity_id,
          text: `${activity.activity_name || "未命名"} / ${activity.activity_id}`,
        }),
      ),
    ],
  );
}

function renderActivityActions(row) {
  return el("div", { class: "actions" }, [
    el("button", {
      class: "shunshou-row-action",
      disabled: row.sync_status !== "active",
      onclick: async () => {
        selectedActivityId = row.activity_id;
        activeTab = "items";
        activityItems = await loadActivityItems();
        await window.renderActiveModule();
      },
      text: "商品",
    }),
    el("button", {
      class: "danger shunshou-row-action",
      onclick: () => deleteActivity(row),
      text: "删除",
    }),
  ]);
}

function renderSignupPageCheck() {
  const checked = signupPreviewRows.length > 0 && signupPreviewRows.every((row) => selectedSignupProductIds.has(String(row.product_id)));
  return el("input", {
    class: "row-check",
    id: "signup-page-check",
    type: "checkbox",
    checked,
    disabled: signupPreviewRows.length === 0,
    onchange: (event) => {
      signupPreviewRows.forEach((row) => toggleSignupProduct(row, event.target.checked));
      document.querySelectorAll(".signup-row-check").forEach((input) => {
        input.checked = event.target.checked;
      });
      updateSignupSelectionUi();
    },
  });
}

function toggleSignupProduct(row, checked) {
  const productId = String(row.product_id || "");
  if (!productId) return;
  if (checked) selectedSignupProductIds.add(productId);
  else selectedSignupProductIds.delete(productId);
}

function updateSignupSelectionUi() {
  const summary = document.getElementById("signup-summary-row");
  if (summary) summary.textContent = signupSummaryText();
  const headerCheck = document.getElementById("signup-page-check");
  if (headerCheck) {
    headerCheck.checked = signupPreviewRows.length > 0 && signupPreviewRows.every((row) => selectedSignupProductIds.has(String(row.product_id)));
  }
}

function toggleSignupRowActivities(row, checked) {
  (row.activities || []).forEach((activity) => toggleSignupActivity(row, activity, checked));
}

function toggleSignupActivity(row, activity, checked) {
  const key = signupActivityKey(row, activity);
  if (checked) selectedSignupKeys.add(key);
  else selectedSignupKeys.delete(key);
}

function selectedSignupActivities(row) {
  return (row.activities || []).filter((activity) => selectedSignupKeys.has(signupActivityKey(row, activity)));
}

function buildSignupChanges() {
  const assignments = {};
  const removals = {};
  const changedRowsByProduct = new Map();
  const addedRowsByProduct = new Map();
  let addedCount = 0;
  let removedCount = 0;
  signupPreviewRows.forEach((row) => {
    (row.activities || []).forEach((activity) => {
      const selected = selectedSignupKeys.has(signupActivityKey(row, activity));
      const joined = Number(activity.is_joined || 0) === 1;
      if (selected && !joined) {
        assignments[activity.activity_id] ||= [];
        if (!assignments[activity.activity_id].includes(row.product_id)) assignments[activity.activity_id].push(row.product_id);
        changedRowsByProduct.set(String(row.product_id), row);
        addedRowsByProduct.set(String(row.product_id), row);
        addedCount += 1;
      } else if (!selected && joined) {
        removals[activity.activity_id] ||= [];
        if (!removals[activity.activity_id].includes(row.product_id)) removals[activity.activity_id].push(row.product_id);
        changedRowsByProduct.set(String(row.product_id), row);
        removedCount += 1;
      }
    });
  });
  return {
    assignments,
    removals,
    changedRows: [...changedRowsByProduct.values()],
    addedRows: [...addedRowsByProduct.values()],
    addedCount,
    removedCount,
    activityCount: new Set([...Object.keys(assignments), ...Object.keys(removals)]).size,
  };
}

function hasPriceChangePreviewRows() {
  return signupPreviewRows.some((row) => row.preview_mode === "price_change");
}

function buildPriceChangeUpdateAssignments() {
  const assignments = {};
  signupPreviewRows
    .filter((row) => row.preview_mode === "price_change" && selectedSignupProductIds.has(String(row.product_id)))
    .forEach((row) => {
      (row.activities || []).forEach((activity) => {
        if (!selectedSignupKeys.has(signupActivityKey(row, activity))) return;
        const activityId = String(activity.activity_id || "");
        const productId = String(row.product_id || "");
        if (!activityId || !productId) return;
        if (!assignments[activityId]) assignments[activityId] = [];
        if (!assignments[activityId].includes(productId)) assignments[activityId].push(productId);
      });
    });
  return assignments;
}

function renderSignupActivityChoices(row) {
  if (row.preview_mode === "price_change") {
    const selectedCount = selectedSignupActivities(row).length;
    const activityCount = (row.activities || []).length;
    return el("button", {
      class: selectedCount ? "signup-activity-button active" : "signup-activity-button",
      title: (row.price_change_rows || []).map((item) => `${item.activity_id} ${item.activity_name || ""}`).join("\n"),
      onclick: () => openSignupActivityPicker(row.product_id),
    }, [`${selectedCount}/${activityCount} 更新`]);
  }
  const activities = row.activities || [];
  if (!activities.length) return "";
  const selectedCount = selectedSignupActivities(row).length;
  return el("button", {
    class: selectedCount ? "signup-activity-button active" : "signup-activity-button",
    title: activities.map((activity) => `${activity.activity_id} ${activity.activity_name || ""}`).join("\n"),
    onclick: () => openSignupActivityPicker(row.product_id),
  }, [`${selectedCount}/${activities.length} 选择`]);
}

async function openSignupActivityPicker(productId) {
  signupActivityPickerProductId = String(productId || "");
  await window.renderActiveModule();
}

async function closeSignupActivityPicker() {
  signupActivityPickerProductId = "";
  await window.renderActiveModule();
}

function currentSignupActivityPickerRow() {
  if (!signupActivityPickerProductId) return null;
  return signupPreviewRows.find((row) => String(row.product_id) === String(signupActivityPickerProductId)) || null;
}

function signupActivityKey(row, activity) {
  return `${activity.activity_id}::${row.product_id}`;
}

function needsPriceFix(row) {
  return Number(row.price_mismatch_count || 0) > 0 || Number(row.missing_normal_price_count || 0) > 0;
}

function logSignupResultDetails(result) {
  const executionRows = result?.execution_results || [];
  executionRows.forEach((row) => {
    const status = row.error ? `失败：${row.error}` : row.submit_success ? "平台确认成功" : row.submitted ? "请求已发送" : row.dry_run ? "预演" : "未提交";
    addLog(
      row.error ? "error" : row.submit_success ? "info" : "error",
      `报名活动 ${row.activity_id}`,
      `请求新增${row.new_item_count ?? row.item_count}，平台确认新增${(row.submitted_product_ids || []).length}，进入参数商品${(row.param_product_ids || []).length}，取消${row.removed_item_count || 0}，保留已报名${row.preserved_item_count || 0}，提交商品${row.submit_item_count ?? row.item_count}，淘宝SKU明细${row.detail_count}，新增SKU${row.new_params_count ?? row.params_count}，保留SKU${row.preserved_params_count || 0}，忽略无报名价SKU${row.ignored_sku_count || 0}，总SKU${row.params_count}，${status}`,
    );
    if ((row.ignored_product_ids || []).length) {
      addLog("info", "报名忽略商品", `${row.ignored_product_ids.slice(0, 20).join("、")}：全部SKU无顺手报名价`);
    }
    if ((row.failed_product_ids || []).length) {
      addLog("error", "报名失败商品", `${row.failed_product_ids.slice(0, 20).join("、")}：${row.error ? "平台拒绝或本地参数校验失败" : "没有可提交SKU"}，未回写为已报名`);
    }
    if ((row.invalid_params || []).length) {
      addLog("error", "报名参数异常", row.invalid_params.slice(0, 10).map((item) => `${item.product_id}/${item.sku_id}:${item.reason}`).join("；"));
    }
  });

  const skipped = result?.skipped_items || [];
  skipped.slice(0, 20).forEach((row) => {
    const productId = row.product_id || "";
    const skuId = row.sku_id ? ` / SKU ${row.sku_id}` : "";
    const skuCode = row.sku_code ? ` / 编码 ${row.sku_code}` : "";
    const skuName = row.sku_name ? ` / ${row.sku_name}` : "";
    const signupPrice = row.signup_price !== undefined && row.signup_price !== null ? ` / 飞书报名价 ${formatMoney(row.signup_price)}` : "";
    const level = String(row.reason || "").includes("平台置灰") ? "info" : "error";
    addLog(level, "报名跳过明细", `${productId}${skuId}${skuCode}${skuName}${signupPrice}：${row.reason || "未返回原因"}`);
  });
  if (skipped.length > 20) {
    addLog("info", "报名跳过明细", `还有 ${skipped.length - 20} 条未展开，请缩小勾选范围后重试或查看接口返回`);
  }
}

function logSignupPriceChangeRows(rows) {
  rows.filter((row) => row.changed).slice(0, 20).forEach((row) => {
    addLog(
      row.can_update ? "info" : "error",
      "报名价变动明细",
      `${row.product_id}，活动${row.activity_id}，SKU ${row.sku_id}：${formatMoney(row.current_signup_price)} -> ${formatMoney(row.feishu_signup_price)}${row.reason ? `，${row.reason}` : ""}`,
    );
  });
  const changedCount = rows.filter((row) => row.changed).length;
  if (changedCount > 20) addLog("info", "报名价变动明细", `还有 ${changedCount - 20} 条未展开`);
}

function buildSignupPriceChangePreviewRows(rows) {
  const grouped = new Map();
  rows.filter((row) => row.changed).forEach((row) => {
    const productId = String(row.product_id || "");
    if (!productId) return;
    if (!grouped.has(productId)) {
      grouped.set(productId, {
        preview_mode: "price_change",
        product_id: productId,
        title: row.title || "",
        image_url: row.image_url || "",
        pxi_score: "",
        joined_count: 0,
        activities: [],
        price_change_rows: [],
        price_change_activity_ids: new Set(),
        price_change_sku_ids: new Set(),
        signup_price_min: null,
        signup_price_max: null,
        current_price_min: null,
        current_price_max: null,
        activities_by_id: new Map(),
      });
    }
    const item = grouped.get(productId);
    if (!item.title && row.title) item.title = row.title;
    if (!item.image_url && row.image_url) item.image_url = row.image_url;
    item.price_change_rows.push(row);
    if (row.activity_id) {
      const activityId = String(row.activity_id);
      item.price_change_activity_ids.add(activityId);
      if (!item.activities_by_id.has(activityId)) {
        item.activities_by_id.set(activityId, {
          activity_id: activityId,
          activity_name: row.activity_name || "",
          is_joined: 1,
          selected: true,
        });
      }
    }
    if (row.sku_id) item.price_change_sku_ids.add(String(row.sku_id));
  });
  return [...grouped.values()].map((row) => {
    const targetPrices = row.price_change_rows.map((item) => normalizeNumber(item.feishu_signup_price)).filter((value) => Number.isFinite(value));
    const currentPrices = row.price_change_rows.map((item) => normalizeNumber(item.current_signup_price)).filter((value) => Number.isFinite(value));
    row.joined_count = row.price_change_activity_ids.size;
    row.price_change_count = row.price_change_rows.length;
    row.price_change_activity_count = row.price_change_activity_ids.size;
    row.price_change_sku_count = row.price_change_sku_ids.size;
    row.activities = [...row.activities_by_id.values()];
    row.signup_price_min = targetPrices.length ? Math.min(...targetPrices) : null;
    row.signup_price_max = targetPrices.length ? Math.max(...targetPrices) : null;
    row.current_price_min = currentPrices.length ? Math.min(...currentPrices) : null;
    row.current_price_max = currentPrices.length ? Math.max(...currentPrices) : null;
    delete row.price_change_activity_ids;
    delete row.price_change_sku_ids;
    delete row.activities_by_id;
    return row;
  });
}

function logSignupPriceUpdateRows(result) {
  (result.execution_results || []).forEach((row) => {
    const status = row.error ? `失败：${row.error}` : row.dry_run ? "预演" : row.submitted ? "已提交" : "未提交";
    addLog(
      row.error ? "error" : "info",
      `更新报名价活动 ${row.activity_id}`,
      `目标商品${row.target_item_count}，保留商品${row.preserved_item_count}，提交商品${row.submit_item_count}，更新SKU ${row.updated_params_count}，未变${row.unchanged_params_count}，保留SKU ${row.preserved_params_count}，${status}`,
    );
  });
  (result.skipped_items || []).slice(0, 20).forEach((row) => {
    addLog("error", "更新报名价跳过", `${row.product_id} / SKU ${row.sku_id}：${row.reason || ""}`);
  });
}

async function verifySignupPriceUpdateResult({ platform, shop_id, productIds, assignmentsByActivity }) {
  const watchedActivityIds = new Set(Object.keys(assignmentsByActivity || {}));
  if (!watchedActivityIds.size) return;
  addLog("info", "更新报名价后检测", `复查 ${productIds.length} 个商品 / ${watchedActivityIds.size} 个活动`);
  const check = await api.post("/shunshou/signup/price-changes/detect", {
    platform,
    shop_id,
    product_ids: productIds,
    cross_shop: false,
    batch_size: 25,
    min_wait_seconds: 0.3,
    max_wait_seconds: 0.6,
  });
  const remainRows = (check.rows || []).filter((row) => row.changed && watchedActivityIds.has(String(row.activity_id)));
  if (remainRows.length) {
    addLog("error", "更新报名价复查未通过", `仍有 ${remainRows.length} 条SKU价格未更新：${remainRows.slice(0, 10).map((row) => `${row.product_id}/${row.activity_id}/${row.sku_id}`).join("，")}`);
  } else {
    addLog("success", "更新报名价复查通过", "所选活动报名价已与飞书报名价一致");
  }
}

async function verifySignupSubmitResult(config, changes, submitResult) {
  const activityIds = [...new Set([...Object.keys(changes.assignments || {}), ...Object.keys(changes.removals || {})])];
  if (!activityIds.length) return;
  addLog("info", "报名后检测", `用SKU明细接口复查 ${activityIds.length} 个活动的实际状态`);
  const failed = [];
  const passed = [];
  const skippedBeforeVerify = [];
  const submittedByActivity = buildSubmittedSignupProductMap(submitResult);
  const failedBeforeVerify = buildFailedSignupProductMap(submitResult);
  const verifyAssignments = {};
  const verifyRemovals = {};
  activityIds.forEach((activityId) => {
    (changes.assignments[activityId] || []).forEach((productId) => {
      if ((failedBeforeVerify[activityId] || new Set()).has(String(productId))) {
        skippedBeforeVerify.push(`${productId}/${activityId}:无可提交SKU`);
        return;
      }
      if (!(submittedByActivity[activityId] || new Set()).has(String(productId))) {
        skippedBeforeVerify.push(`${productId}/${activityId}:未进入提交参数`);
        return;
      }
      if (!verifyAssignments[activityId]) verifyAssignments[activityId] = [];
      verifyAssignments[activityId].push(String(productId));
    });
    if ((changes.removals[activityId] || []).length) {
      verifyRemovals[activityId] = (changes.removals[activityId] || []).map((productId) => String(productId));
    }
  });
  const verifyResult = await api.post("/shunshou/signup/verify", {
    platform: config.platform,
    shop_id: config.shop_id,
    assignments_by_activity: verifyAssignments,
    remove_assignments_by_activity: verifyRemovals,
    cross_shop: config.cross_shop,
    batch_size: 25,
    min_wait_seconds: 0.3,
    max_wait_seconds: 0.6,
  });
  (verifyResult.rows || []).forEach((row) => {
    const text = `${row.product_id}/${row.activity_id}:${row.reason || ""}`;
    if (row.ok) passed.push(text);
    else failed.push(text);
  });
  if (skippedBeforeVerify.length) {
    addLog("error", "报名提交前失败", `${skippedBeforeVerify.length} 条：${skippedBeforeVerify.slice(0, 12).join("；")}`);
  }
  if (failed.length) {
    addLog("error", "报名后检测未通过", `${failed.length} 条：${failed.slice(0, 12).join("；")}`);
  }
  const message = [
    `报名后检测完成`,
    `成功：${passed.length} 条`,
    `提交前失败：${skippedBeforeVerify.length} 条`,
    `复查失败：${failed.length} 条`,
    "",
    ...passed.slice(0, 8),
    ...skippedBeforeVerify.slice(0, 8),
    ...failed.slice(0, 8),
  ].join("\n");
  alert(message);
  if (failed.length || skippedBeforeVerify.length) {
    addLog("error", "报名后检测完成", `成功${passed.length}，提交前失败${skippedBeforeVerify.length}，复查失败${failed.length}`);
  } else {
    addLog("success", "报名后检测通过", `所选活动商品状态已确认，成功${passed.length}条`);
  }
}

function buildSubmittedSignupProductMap(result) {
  const grouped = {};
  (result?.execution_results || []).forEach((row) => {
    const activityId = String(row.activity_id || "");
    if (!activityId) return;
    grouped[activityId] = new Set((row.submit_success ? row.submitted_product_ids || [] : []).map((productId) => String(productId)));
  });
  return grouped;
}

function buildFailedSignupProductMap(result) {
  const grouped = {};
  (result?.execution_results || []).forEach((row) => {
    const activityId = String(row.activity_id || "");
    if (!activityId) return;
    const failedIds = new Set((row.failed_product_ids || row.ignored_product_ids || []).map((productId) => String(productId)));
    if (!row.submit_success) {
      (row.param_product_ids || []).forEach((productId) => failedIds.add(String(productId)));
    }
    grouped[activityId] = failedIds;
  });
  return grouped;
}

function logRelistDetails(result, productContextMap = new Map()) {
  (result?.success_items || []).slice(0, 20).forEach((row) => {
    addLog("info", "一键修改成功", `${row.product_id}${productContextText(productContextMap.get(String(row.product_id)))}：${relistStageSummary(row)}，${relistPricePlanSummary(row)}，SKU ${row.sku_count}，库存 ${row.total_stock}`);
  });
  (result?.failed_items || []).slice(0, 20).forEach((row) => {
    addLog("error", "一键修改失败明细", `${row.product_id}${productContextText(productContextMap.get(String(row.product_id)))}：${row.failed_stage || ""} ${row.error_message || ""}，${relistPricePlanSummary(row)}`);
  });
  (result?.skipped_items || []).slice(0, 20).forEach((row) => {
    addLog("info", "一键修改跳过", `${row.product_id}${productContextText(productContextMap.get(String(row.product_id)))}：${row.reason || ""}`);
  });
}

function buildProductContextMap(rows) {
  const result = new Map();
  rows.forEach((row) => {
    const productId = String(row.product_id || "");
    if (!productId) return;
    if (!result.has(productId)) result.set(productId, { activityIds: new Set(), rowCount: 0 });
    const context = result.get(productId);
    context.rowCount += 1;
    if (row.activity_id) context.activityIds.add(String(row.activity_id));
  });
  return result;
}

function productContextText(context) {
  if (!context) return "";
  const activityIds = [...context.activityIds];
  const activityText = activityIds.length ? `，活动ID ${activityIds.join("、")}` : "";
  const countText = context.rowCount > 1 ? `，候选${context.rowCount}条` : "";
  return `${activityText}${countText}`;
}

function productPlanText(productId, stock, stockMode) {
  const rows = signupPreviewRows.filter((row) => String(row.product_id) === String(productId));
  if (!rows.length) return "";
  const first = rows[0];
  const normalRange = formatPriceRange(first.normal_price_min, first.normal_price_max);
  return `，正常价${normalRange || "-"}，库存${stock}(${stockMode})`;
}

function relistPricePlanSummary(row) {
  const itemPrice = row.planned_item_price ?? row.edit_price_result?.planned_item_price;
  const skuPrices = row.planned_sku_prices || row.edit_price_result?.planned_sku_prices || [];
  const skuText = skuPrices
    .slice(0, 4)
    .map((sku) => `${sku.sku_id || sku.skuId}:${formatMoney(sku.price ?? sku.skuPrice)}`)
    .join(" / ");
  const moreText = skuPrices.length > 4 ? ` 等${skuPrices.length}个SKU` : "";
  return `计划一口价${formatMoney(itemPrice)}${skuText ? `，SKU价 ${skuText}${moreText}` : ""}`;
}

function relistStageSummary(row) {
  const editAttempts = row.edit_price_result?.attempts || 0;
  const inventoryAttempts = row.inventory_result?.attempts || 0;
  const upshelfAttempts = row.upshelf_result?.attempts || 0;
  const parts = [`改价${editAttempts || "-"}次`];
  if (inventoryAttempts) parts.push(`库存${inventoryAttempts}次`);
  if (upshelfAttempts) parts.push(`上架${upshelfAttempts}次`);
  return parts.join(" / ");
}

function modifyFlowText(editPrice, updateInventory, upshelf) {
  return [
    editPrice ? "改价格" : "",
    updateInventory ? "改库存" : "",
    upshelf ? "上架" : "",
  ].filter(Boolean).join(" -> ") || "未选择动作";
}

function renderProductThumb(url) {
  return renderThumbButton(url, { onOpen: openImagePreview });
}

function renderImagePreviewModal() {
  return renderImagePreview({ url: previewImageUrl, onClose: closeImagePreview });
}

function renderSignupModal() {
  return el("div", { class: signupModalOpen ? "modal-mask open" : "modal-mask", onclick: closeSignupModal }, [
    el("div", { class: "modal shunshou-signup-modal", onclick: (event) => event.stopPropagation() }, [
      el("div", { class: "modal-header" }, [
        el("strong", { text: "一键报名设置" }),
        el("button", { class: "ghost", onclick: closeSignupModal }, ["关闭"]),
      ]),
      el("div", { class: "modal-body" }, [
        el("div", { class: "form-grid" }, [
          formField("PXI分大于", "shunshou-pxi-min", pxiMin, "0"),
          formField("累计销量大于等于", "shunshou-sold-min", soldTotalMin, "0"),
          formField("商品ID", "shunshou-signup-product-id", signupProductId, "", "", "text"),
          formField("已报活动数最小", "shunshou-joined-min", joinedCountMin, "0"),
          formField("已报活动数最大", "shunshou-joined-max", joinedCountMax, "0"),
          formField("单活动报名上限", "shunshou-signup-limit", signupLimit, "1", "171"),
        ]),
        el("div", { class: "modal-actions" }, [
          el("button", { onclick: closeSignupModal }, ["取消"]),
          el("button", { class: "primary", disabled: previewingSignup, onclick: previewSignupCandidates }, [
            previewingSignup ? "获取中..." : "获取符合条件商品",
          ]),
        ]),
      ]),
    ]),
  ]);
}

function renderSignupModifyModal() {
  return el("div", { class: signupModifyModalOpen ? "modal-mask open" : "modal-mask", onclick: closeSignupModifyModal }, [
    el("div", { class: "modal relist-modal", onclick: (event) => event.stopPropagation() }, [
      el("div", { class: "modal-header" }, [
        el("strong", { text: "一键修改" }),
        el("button", { class: "ghost", onclick: closeSignupModifyModal }, ["关闭"]),
      ]),
      el("div", { class: "modal-body" }, [
        el("div", { class: "relist-options" }, [
          el("label", { class: "relist-check" }, [
            el("input", { id: "signup-modify-edit-price", type: "checkbox", checked: signupModifyEditPrice }),
            el("span", { text: "改价格" }),
          ]),
          el("label", { class: "relist-check" }, [
            el("input", { id: "signup-modify-update-inventory", type: "checkbox", checked: signupModifyUpdateInventory }),
            el("span", { text: "改库存" }),
          ]),
          el("div", { class: "relist-field" }, [
            el("label", { for: "signup-modify-stock", text: "库存" }),
            el("input", { id: "signup-modify-stock", type: "number", min: "0", value: String(signupRelistStock) }),
          ]),
          el("div", { class: "relist-field" }, [
            el("label", { for: "signup-modify-stock-mode", text: "库存模式" }),
            el(
              "select",
              { id: "signup-modify-stock-mode", class: "ui-select", value: signupRelistStockMode },
              [
                el("option", { value: "per_sku", selected: signupRelistStockMode === "per_sku", text: "每个SKU同库存" }),
                el("option", { value: "total_split", selected: signupRelistStockMode === "total_split", text: "总库存拆分到SKU" }),
              ],
            ),
          ]),
        ]),
        el("div", { class: "modal-actions" }, [
          el("button", { onclick: closeSignupModifyModal }, ["取消"]),
          el("button", { class: "primary", disabled: relistingSignupProducts, onclick: relistSignupPreviewProducts }, [
            relistingSignupProducts ? "执行中..." : "执行",
          ]),
        ]),
      ]),
    ]),
  ]);
}

function renderSignupActivityPickerModal() {
  const row = currentSignupActivityPickerRow();
  return el("div", { class: row ? "modal-mask open" : "modal-mask", onclick: closeSignupActivityPicker }, [
    row ? el("div", { class: "modal signup-activity-modal", onclick: (event) => event.stopPropagation() }, [
      el("div", { class: "modal-header" }, [
        el("strong", { text: row.preview_mode === "price_change" ? "选择更新价格的活动" : "选择报名活动" }),
        el("button", { class: "ghost", onclick: closeSignupActivityPicker }, ["关闭"]),
      ]),
      el("div", { class: "modal-body" }, [
        el("div", { class: "signup-activity-product" }, [
          el("div", { class: "signup-activity-product-id", text: row.product_id }),
          el("div", { class: "muted", text: row.title || "" }),
        ]), 
        el("div", { class: "signup-activity-picker-actions" }, [
          el("button", { onclick: async () => { toggleSignupRowActivities(row, true); await window.renderActiveModule(); } }, [row.preview_mode === "price_change" ? "全选更新" : "全选活动"]),
          el("button", { onclick: async () => { toggleSignupRowActivities(row, false); await window.renderActiveModule(); } }, [row.preview_mode === "price_change" ? "全不更新" : "全不选活动"]),
        ]),
        el("div", { class: "signup-activity-picker-list" }, (row.activities || []).map((activity) =>
          el("label", { class: "signup-activity-picker-row" }, [
            el("input", {
              type: "checkbox",
              checked: selectedSignupKeys.has(signupActivityKey(row, activity)),
              onchange: async (event) => {
                toggleSignupActivity(row, activity, event.target.checked);
                await window.renderActiveModule();
              },
            }),
            el("span", { class: "signup-activity-picker-id", text: activity.activity_id }),
            el("span", { class: "signup-activity-picker-name", text: activity.activity_name || "" }),
            Number(activity.is_joined || 0) === 1 ? el("span", { class: "signup-activity-joined", text: row.preview_mode === "price_change" ? "待更新" : "已报名" }) : "",
          ]),
        )),
      ]),
      el("div", { class: "modal-actions" }, [
        el("button", { class: "primary", onclick: closeSignupActivityPicker }, ["确定"]),
      ]),
    ]) : "",
  ]);
}

function formField(labelText, id, value, min, max = "", type = "number") {
  const attrs = {
    id,
    type,
    value: String(value),
  };
  if (min !== "") attrs.min = min;
  if (max) attrs.max = max;
  return el("div", { class: "form-row" }, [
    el("label", { for: id, text: labelText }),
    el("input", attrs),
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

function formatCapacity(row) {
  if (row.signed_item_count === null || row.signed_item_count === undefined) return "";
  if (row.max_item_limit === null || row.max_item_limit === undefined) return String(row.signed_item_count);
  return `${row.signed_item_count}/${row.max_item_limit}`;
}

function formatSignupPrice(row) {
  if (row.preview_mode === "price_change") {
    return `${formatPriceRange(row.current_price_min, row.current_price_max) || "-"} -> ${formatPriceRange(row.signup_price_min, row.signup_price_max) || "-"}`;
  }
  return formatPriceRange(row.signup_price_min, row.signup_price_max);
}

function formatSignupPriceStatus(row) {
  if (row.preview_mode === "price_change") return `变动${row.price_change_count || 0}`;
  const mismatch = Number(row.price_mismatch_count || 0);
  const missing = Number(row.missing_normal_price_count || 0);
  if (missing > 0) return `缺正常价${missing}`;
  if (mismatch > 0) return `需改价${mismatch}`;
  return "正常";
}

function renderSignupPriceStatus(row) {
  const text = formatSignupPriceStatus(row);
  if (row.preview_mode === "price_change") return el("span", { class: "price-status-danger", text });
  return el("span", { class: needsPriceFix(row) ? "price-status-danger" : "price-status-ok", text });
}

function signupPriceStatusTitle(row) {
  if (row.preview_mode === "price_change") {
    return [
      `报名价变动：${row.price_change_count || 0} 条SKU记录`,
      `当前报名价：${formatPriceRange(row.current_price_min, row.current_price_max) || "-"}`,
      `飞书报名价：${formatPriceRange(row.signup_price_min, row.signup_price_max) || "-"}`,
      `涉及活动：${(row.price_change_rows || []).map((item) => `${item.activity_id} ${item.activity_name || ""}`).join(" / ")}`,
    ].join("\n");
  }
  return [
    `价格检查：${formatSignupPriceStatus(row)}`,
    `正常售价：${formatPriceRange(row.normal_price_min, row.normal_price_max) || "-"}`,
    `一口价：${formatMoney(row.current_item_price)} / 应为 ${formatMoney(row.expected_item_price)}`,
    `当前价：${formatPriceRange(row.current_price_min, row.current_price_max) || "-"}`,
    `顺手报名价：${formatSignupPrice(row) || "-"}`,
    `已定价SKU：${row.priced_sku_count || 0}`,
  ].join("\n");
}

function formatPriceRange(minValue, maxValue) {
  const min = Number(minValue);
  const max = Number(maxValue);
  if (!Number.isFinite(min) && !Number.isFinite(max)) return "";
  if (!Number.isFinite(max) || min === max) return formatMoney(min);
  return `${formatMoney(min)}-${formatMoney(max)}`;
}

function formatSyncStatus(status) {
  if (status === "active") return "有效";
  if (status === "inactive") return "失效";
  return status || "";
}

function statusLabel(status) {
  if (status === "active") return "有效数据";
  if (status === "inactive") return "失效";
  if (status === "all") return "全部状态";
  return "";
}

function badgeText() {
  if (activeTab === "activities") return `${activities.length} 个活动`;
  if (activeTab === "items") return `${activityItems.length} 个商品`;
  return `${signupPreviewRows.length} 条预览`;
}

function shopLabel(value) {
  const shop = shopsCache.find((item) => `${item.platform}::${item.shop_id}` === value);
  return shop?.shop_name || value || "";
}

function normalizeSignupLimit(value) {
  const number = Number(value || 160);
  if (!Number.isFinite(number)) return 160;
  return Math.max(1, Math.min(171, Math.floor(number)));
}
