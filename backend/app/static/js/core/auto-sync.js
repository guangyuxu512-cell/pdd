import { api } from "../api/client.js";
import { addLog } from "./state.js";

const FEISHU_PRICE_SYNC_INTERVAL_MS = 60 * 1000;

let feishuPriceSyncRunning = false;
let feishuPriceSyncTimer = null;
let lastFailureMessage = "";

export function startAutoSync() {
  if (feishuPriceSyncTimer) return;
  window.setTimeout(() => runAutoFeishuPriceSync("启动自动同步"), 3000);
  feishuPriceSyncTimer = window.setInterval(() => {
    runAutoFeishuPriceSync("定时自动同步");
  }, FEISHU_PRICE_SYNC_INTERVAL_MS);
}

async function runAutoFeishuPriceSync(reason) {
  if (feishuPriceSyncRunning) return;
  feishuPriceSyncRunning = true;
  try {
    const result = await api.post("/products/skus/prices/sync");
    lastFailureMessage = "";
    const updatedCount = Number(result.updated_global_skus || 0) + Number(result.updated_shop_skus || 0);
    addLog(
      updatedCount ? "success" : "info",
      "自动飞书匹配价格完成",
      `${reason}；全局SKU更新${updatedCount}条，飞书有效${result.valid_rows}条，警告${(result.warnings || []).length}`,
    );
    if ((result.warnings || []).length) {
      addLog("error", "自动飞书价格警告", result.warnings.slice(0, 3).join("；"));
    }
  } catch (error) {
    if (error.message !== lastFailureMessage) {
      addLog("error", "自动飞书匹配价格失败", error.message);
      lastFailureMessage = error.message;
    }
  } finally {
    feishuPriceSyncRunning = false;
  }
}
