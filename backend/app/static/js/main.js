import { addLog, state, subscribe } from "./core/state.js";
import { modules, renderMenu, renderShell, renderTaskBanner, setPageTitle } from "./components/shell.js";
import { renderLogPanel } from "./modules/logs/log-panel.js";
import { renderProductPage } from "./modules/products/product-page.js";
import { renderPxiPage } from "./modules/products/pxi-page.js";
import { renderSkuPage } from "./modules/products/sku-page.js";
import { renderSettingsPage } from "./modules/settings/settings-page.js";
import { renderShunshouPage } from "./modules/shunshou/shunshou-page.js";
import { renderShopPage } from "./modules/shops/shop-page.js";
import { startAutoSync } from "./core/auto-sync.js";

const renderers = {
  shops: renderShopPage,
  products: renderProductPage,
  skus: renderSkuPage,
  pxi: renderPxiPage,
  shunshou: renderShunshouPage,
  settings: renderSettingsPage,
};

renderShell(document.getElementById("app"));
subscribe(() => {
  renderMenu();
  renderTaskBanner();
  renderLogPanel();
});

window.renderActiveModule = renderActiveModule;

await renderActiveModule();
renderMenu();
renderTaskBanner();
renderLogPanel();
addLog("info", "前端已加载", "内置静态工作台");
startAutoSync();

async function renderActiveModule() {
  const container = document.getElementById("operation-area");
  const module = modules.find((item) => item.id === state.activeModule);
  setPageTitle(module?.title ?? "");
  try {
    await renderers[state.activeModule](container);
  } catch (error) {
    addLog("error", "页面渲染失败", error.message);
    container.innerHTML = `<section class="panel"><div class="panel-body">${error.message}</div></section>`;
  }
}
