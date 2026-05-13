import { api } from "../../api/client.js";
import { el, formValue } from "../../core/dom.js";
import { addLog, endTask, startTask } from "../../core/state.js";
import { renderTable } from "../../components/table.js";

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
let targetActivityCount = 2;
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
          el("button", { disabled: previewingSignup || signingUp || relistingSignupProducts, onclick: syncProductsFromWorkbench }, ["1 商品列表"]),
          el("button", { disabled: previewingSignup || signingUp || relistingSignupProducts, onclick: syncSkusFromWorkbench }, ["2 SKU价/库存"]),
          el("button", { disabled: previewingSignup || signingUp || relistingSignupProducts, onclick: syncFeishuPricesFromWorkbench }, ["3 飞书匹配价格"]),
          el("button", { disabled: previewingSignup || signingUp || relistingSignupProducts, onclick: syncPxiFromWorkbench }, ["4 PXI分"]),
          el("button", { disabled: syncingActivities || signingUp || relistingSignupProducts, onclick: syncActivities }, [syncingActivities ? "获取中..." : "5 活动ID"]),
          el("button", { disabled: syncingItems || signingUp || relistingSignupProducts, onclick: syncAllActivityItems }, [syncingItems ? "获取中..." : "6 活动商品"]),
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
  return [
    renderReadinessPanel(),
    el("div", { class: "shunshou-toolbar" }, [
      el("button", { class: "primary", disabled: previewingSignup, onclick: openSignupModal }, [previewingSignup ? "获取中..." : "获取符合条件商品"]),
      el("button", { class: "primary", disabled: signingUp || signupPreviewRows.length === 0, onclick: signupPreviewSelection }, [
        signingUp ? "报名中..." : "报名勾选/全部",
      ]),
      el("button", { disabled: relistingSignupProducts || signupPreviewRows.length === 0, onclick: openSignupModifyModal }, [
        relistingSignupProducts ? "执行中..." : "一键修改",
      ]),
      el("button", { disabled: !relistingSignupProducts, onclick: stopSignupModify }, ["终止修改"]),
      el("span", { class: "muted", text: `预览 ${signupPreviewRows.length} 条，已勾选 ${selectedSignupKeys.size} 条` }),
    ]),
    renderSignupPreviewTable(),
  ];
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
  addLog("info", "开始一键SKU价/库存", "同步当前有效商品的SKU编码、当前价和库存");
  if (render) await window.renderActiveModule();
  try {
    const products = await api.get(`/products?${new URLSearchParams({ platform, shop_id }).toString()}`);
    const productIds = products.filter((product) => product.status !== "deleted").map((product) => product.product_id);
    if (!productIds.length) {
      addLog("info", "一键SKU价/库存", "当前没有有效商品");
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
          class: "row-check",
          type: "checkbox",
          checked: selectedSignupActivities(row).length > 0,
          onchange: (event) => toggleSignupRow(row, event.target.checked),
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

function renderSignupPreviewTableOld() {
  return renderTable({
    rows: signupPreviewRows,
    emptyText: "暂无待报名商品。点击“获取符合条件商品”后再勾选报名。",
    className: "product-table",
    columns: [
      {
        title: "",
        className: "check-cell",
        width: "4%",
        renderHeader: () => renderSignupPageCheck(),
        render: (row) =>
          el("input", {
            class: "row-check",
            type: "checkbox",
            checked: selectedSignupKeys.has(signupKey(row)),
            onchange: (event) => toggleSignupRow(row, event.target.checked),
          }),
      },
      { title: "ID", width: "4%", render: (_row, index) => String(index + 1) },
      { title: "主图", width: "7%", render: (row) => renderProductThumb(row.image_url) },
      { title: "活动ID", key: "activity_id", width: "15%" },
      { title: "商品ID", key: "product_id", width: "15%" },
      { title: "标题", key: "title", width: "27%" },
      {
        title: "价格检查",
        width: "12%",
        render: (row) => renderSignupPriceStatus(row),
        titleValue: (row) => signupPriceStatusTitle(row),
      },
      { title: "顺手报名价", width: "10%", render: (row) => formatSignupPrice(row) },
      { title: "活动", width: "18%", render: (row) => renderSignupActivityChoices(row) },
      { title: "PXI", key: "pxi_score", width: "5%" },
      { title: "已报", key: "joined_count", width: "5%" },
    ],
  });
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

async function signupSelectedActivity() {
  const limit = normalizeSignupLimit(formValue("shunshou-signup-limit") || signupLimit);
  signupLimit = limit;
  pxiMin = normalizeNumber(formValue("shunshou-pxi-min"), 70);
  soldTotalMin = Math.floor(normalizeNumber(formValue("shunshou-sold-min"), 3));
  targetActivityCount = Math.max(1, Math.floor(normalizeNumber(formValue("shunshou-target-count"), 2)));
  if (!selectedShop) {
    alert("请先选择店铺");
    return;
  }
  signupModalOpen = false;
  const [platform, shop_id] = selectedShop.split("::");
  signingUp = true;
  const taskId = startTask("正在一键报名", shopLabel(selectedShop));
  addLog("info", "开始一键报名", `PXI>${pxiMin} / 销量>=${soldTotalMin} / 每商品${targetActivityCount}个活动 / 单活动容量${signupLimit}`);
  await window.renderActiveModule();
  try {
    const result = await api.post("/shunshou/signup", {
      platform,
      shop_id,
      pxi_min: pxiMin,
      sold_total_min: soldTotalMin,
      target_activity_count: targetActivityCount,
      custom_capacity_limit: signupLimit,
      reserve_item_count: 3,
      real_capacity_fallback: 171,
      cross_shop: false,
      batch_size: 25,
      min_wait_seconds: 0.6,
      max_wait_seconds: 1.8,
      dry_run: false,
    });
    activityItems = await loadActivityItems();
    activities = await loadActivities();
    addLog(
      "success",
      "结束一键报名",
      `候选${result.candidate_count}，分配${result.assignment_count}，提交活动${result.submitted_activity_count}，SKU ${result.submitted_sku_count}，跳过${result.skipped_count}`,
    );
    logSignupResultDetails(result);
  } catch (error) {
    addLog("error", "一键报名失败", error.message);
    alert(error.message);
  } finally {
    signingUp = false;
    endTask(taskId);
    await window.renderActiveModule();
  }
}

async function previewSignupCandidates() {
  const config = readSignupConfig();
  if (!config) return;
  previewingSignup = true;
  signupModalOpen = false;
  const taskId = startTask("正在获取符合条件商品", shopLabel(selectedShop));
  addLog("info", "获取符合条件商品", `PXI>${pxiMin} / 销量>=${soldTotalMin} / 每商品${targetActivityCount}个活动 / 单活动容量${signupLimit}`);
  await window.renderActiveModule();
  try {
    const result = await api.post("/shunshou/signup/preview", config);
    signupPreviewRows = result.rows || [];
    selectedSignupKeys.clear();
    signupPreviewRows.forEach((row) => {
      (row.activities || []).forEach((activity) => {
        if (activity.selected !== false) selectedSignupKeys.add(signupActivityKey(row, activity));
      });
    });
    readiness = await loadReadiness();
    addLog("success", "符合条件商品获取完成", `候选${result.candidate_count}，可分配${result.assignment_count}，跳过${(result.skipped_items || []).length}`);
  } catch (error) {
    addLog("error", "获取符合条件商品失败", error.message);
    alert(error.message);
  } finally {
    previewingSignup = false;
    endTask(taskId);
    await window.renderActiveModule();
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
  const sourceRows = selectedSignupKeys.size
    ? signupPreviewRows.filter((row) => selectedSignupKeys.has(signupKey(row)))
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

async function signupPreviewSelection() {
  const config = readSignupConfig();
  if (!config) return;
  const selectedRows = signupPreviewRows.filter((row) => selectedSignupActivities(row).length > 0);
  if (!selectedRows.length) {
    alert("没有可报名的预览商品");
    return;
  }
  const blockedRows = selectedRows.filter(needsPriceFix);
  if (blockedRows.length) {
    alert(`有 ${blockedRows.length} 条商品需要先恢复正常价。请点击“恢复正常价”后重新获取符合条件商品，再报名。`);
    addLog("error", "报名前价格检查", `拦截 ${blockedRows.length} 条需改价/缺正常价商品`);
    return;
  }
  const assignments = {};
  selectedRows.forEach((row) => {
    selectedSignupActivities(row).forEach((activity) => {
      assignments[activity.activity_id] ||= [];
      if (!assignments[activity.activity_id].includes(row.product_id)) assignments[activity.activity_id].push(row.product_id);
    });
  });
  signingUp = true;
  const taskId = startTask("正在报名检测/提交", `${selectedRows.length} 条候选`);
  addLog("info", "报名前检测", `重新检测 ${selectedRows.length} 条候选，确认PXI、活动状态和价格`);
  await window.renderActiveModule();
  try {
    const check = await api.post("/shunshou/signup/check", { ...config, assignments_by_activity: assignments });
    const failedRows = check.failed_rows || [];
    if (failedRows.length) {
      const detailText = failedRows.slice(0, 20).map((row) => `${row.product_id}/${row.activity_id}:${row.reason || "no reason"}`).join("; ");
      addLog("error", "signup check failed", `${failedRows.length} rows: ${detailText}`);
      alert(`signup check failed: ${failedRows.length} rows\n${detailText}`);
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
    addLog("success", "报名前检测通过", `提交 ${selectedRows.length} 条，活动 ${Object.keys(assignments).length} 个`);
    addLog("info", "开始报名预览商品", `提交 ${selectedRows.length} 条，活动 ${Object.keys(assignments).length} 个`);
    const result = await api.post("/shunshou/signup", { ...config, assignments_by_activity: assignments });
    activityItems = await loadActivityItems();
    activities = await loadActivities();
    readiness = await loadReadiness();
    const successKeys = successfulSignupKeys(result, selectedRows);
    if (successKeys.size) {
      signupPreviewRows = signupPreviewRows.filter((row) => !successKeys.has(signupKey(row)));
      successKeys.forEach((key) => selectedSignupKeys.delete(key));
    }
    addLog(
      "success",
      "结束报名预览商品",
      `提交活动${result.submitted_activity_count}，SKU ${result.submitted_sku_count}，跳过${result.skipped_count}`,
    );
    logSignupResultDetails(result);
    if (!successKeys.size) {
      addLog("error", "报名未完成", "没有任何 SKU 提交成功，预览商品已保留，请先处理日志中的跳过原因");
    }
  } catch (error) {
    addLog("error", "报名预览商品失败", error.message);
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
  targetActivityCount = Math.max(1, Math.floor(normalizeNumber(formValue("shunshou-target-count"), 2)));
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
    target_activity_count: targetActivityCount,
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
  const checked = signupPreviewRows.length > 0 && signupPreviewRows.every((row) => selectedSignupActivities(row).length > 0);
  return el("input", {
    class: "row-check",
    type: "checkbox",
    checked,
    disabled: signupPreviewRows.length === 0,
    onchange: async (event) => {
      signupPreviewRows.forEach((row) => toggleSignupRow(row, event.target.checked));
      await window.renderActiveModule();
    },
  });
}

function toggleSignupRow(row, checked) {
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

function renderSignupActivityChoices(row) {
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

function signupKey(row) {
  return `${row.product_id}`;
}

function needsPriceFix(row) {
  return Number(row.price_mismatch_count || 0) > 0 || Number(row.missing_normal_price_count || 0) > 0;
}

function successfulSignupKeys(result, selectedRows) {
  const keys = new Set();
  const successfulActivityIds = new Set(
    (result?.execution_results || [])
      .filter((row) => row.submitted && !row.error && Number(row.params_count || 0) > 0)
      .map((row) => String(row.activity_id)),
  );
  if (!successfulActivityIds.size) return keys;
  selectedRows.forEach((row) => {
    const allSucceeded = selectedSignupActivities(row).every((activity) => successfulActivityIds.has(String(activity.activity_id)));
    if (allSucceeded) keys.add(signupKey(row));
  });
  return keys;
}

function logSignupResultDetails(result) {
  const executionRows = result?.execution_results || [];
  executionRows.forEach((row) => {
    const status = row.error ? `失败：${row.error}` : row.submitted ? "已提交" : row.dry_run ? "预演" : "未提交";
    addLog(
      row.error ? "error" : "info",
      `报名活动 ${row.activity_id}`,
      `新增商品${row.new_item_count ?? row.item_count}，保留已报名${row.preserved_item_count || 0}，提交商品${row.submit_item_count ?? row.item_count}，淘宝SKU明细${row.detail_count}，新增SKU${row.new_params_count ?? row.params_count}，保留SKU${row.preserved_params_count || 0}，忽略无报名价SKU${row.ignored_sku_count || 0}，总SKU${row.params_count}，${status}`,
    );
    if ((row.ignored_product_ids || []).length) {
      addLog("info", "报名忽略商品", `${row.ignored_product_ids.slice(0, 20).join("、")}：全部SKU无顺手报名价`);
    }
  });

  const skipped = result?.skipped_items || [];
  skipped.slice(0, 20).forEach((row) => {
    const productId = row.product_id || "";
    const skuId = row.sku_id ? ` / SKU ${row.sku_id}` : "";
    addLog("info", "报名跳过明细", `${productId}${skuId}：${row.reason || "未返回原因"}`);
  });
  if (skipped.length > 20) {
    addLog("info", "报名跳过明细", `还有 ${skipped.length - 20} 条未展开，请缩小勾选范围后重试或查看接口返回`);
  }
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
  if (!url) return "";
  return el("button", { class: "product-thumb-button", title: "查看主图", onclick: () => openImagePreview(url) }, [
    el("img", { class: "product-thumb", src: url, alt: "主图", loading: "lazy" }),
    el("span", { class: "product-thumb-eye" }),
  ]);
}

function renderImagePreviewModal() {
  return el("div", { class: previewImageUrl ? "modal-mask open" : "modal-mask", onclick: closeImagePreview }, [
    el("div", { class: "image-preview-modal", onclick: (event) => event.stopPropagation() }, [
      el("div", { class: "modal-header" }, [
        el("strong", { text: "主图预览" }),
        el("button", { class: "ghost", onclick: closeImagePreview }, ["关闭"]),
      ]),
      el("div", { class: "image-preview-body" }, [
        previewImageUrl ? el("img", { class: "image-preview", src: previewImageUrl, alt: "主图预览" }) : "",
      ]),
    ]),
  ]);
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
          formField("每商品目标活动数", "shunshou-target-count", targetActivityCount, "1"),
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
        el("strong", { text: "选择报名活动" }),
        el("button", { class: "ghost", onclick: closeSignupActivityPicker }, ["关闭"]),
      ]),
      el("div", { class: "modal-body" }, [
        el("div", { class: "signup-activity-product" }, [
          el("div", { class: "signup-activity-product-id", text: row.product_id }),
          el("div", { class: "muted", text: row.title || "" }),
        ]),
        el("div", { class: "signup-activity-picker-actions" }, [
          el("button", { onclick: async () => { toggleSignupRow(row, true); await window.renderActiveModule(); } }, ["全选"]),
          el("button", { onclick: async () => { toggleSignupRow(row, false); await window.renderActiveModule(); } }, ["全不选"]),
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
          ]),
        )),
      ]),
      el("div", { class: "modal-actions" }, [
        el("button", { class: "primary", onclick: closeSignupActivityPicker }, ["确定"]),
      ]),
    ]) : "",
  ]);
}

function formField(labelText, id, value, min, max = "") {
  const attrs = {
    id,
    type: "number",
    min,
    value: String(value),
  };
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
  return formatPriceRange(row.signup_price_min, row.signup_price_max);
}

function formatSignupPriceStatus(row) {
  const mismatch = Number(row.price_mismatch_count || 0);
  const missing = Number(row.missing_normal_price_count || 0);
  if (missing > 0) return `缺正常价${missing}`;
  if (mismatch > 0) return `需改价${mismatch}`;
  return "正常";
}

function renderSignupPriceStatus(row) {
  const text = formatSignupPriceStatus(row);
  return el("span", { class: needsPriceFix(row) ? "price-status-danger" : "price-status-ok", text });
}

function signupPriceStatusTitle(row) {
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

function formatMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return number.toFixed(2).replace(/\.?0+$/, "");
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

function formatTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function normalizeSignupLimit(value) {
  const number = Number(value || 160);
  if (!Number.isFinite(number)) return 160;
  return Math.max(1, Math.min(171, Math.floor(number)));
}

function normalizeNumber(value, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(0, number);
}
