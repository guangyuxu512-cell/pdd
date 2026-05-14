# 淘宝工具箱架构与业务规则

本文档记录当前项目边界、模块职责、顺手报名规则、价格规则、后续拆分方向。后续改功能前应先对照本文，避免把报名价、正常价、活动状态和商品状态混用。

## 当前架构

项目是本地桌面工具，核心由三层组成：

```text
Electron 壳
  启动本地界面和后端

FastAPI 后端
  API 路由、业务服务、SQLite 数据读写、淘宝接口请求

静态前端
  后端直接托管，不依赖 Vite
```

关键目录：

```text
backend/app/api/routers/      API 入口
backend/app/models/           SQLModel 数据模型和请求响应模型
backend/app/services/         淘宝接口和业务服务
backend/app/static/js/        前端模块
backend/app/static/js/core/   前端通用工具
backend/app/static/js/components/ 前端通用组件
data/app.db                   本地 SQLite 数据库
```

## 模块边界

### 店铺和登录态

店铺信息在 `shop` 表中保存。Cookie 快照在 `cookie_snapshot` 表中保存。

当前接口请求主要使用 SQLite 中最新的 `main` cookie。长期更稳的方向是每个店铺保留独立浏览器 profile，通过常驻或按需启动浏览器续 cookie，而不是依赖一次性 cookie 字符串。

边界：

- 店铺管理只负责店铺、profile、cookie 状态。
- 业务服务不要直接操作前端登录流程。
- 请求前应先检测 cookie，失败时尝试从浏览器 profile 刷新，仍失败才提示重登。

### 商品、SKU、PXI

商品列表来自淘宝商品接口，保存到 `product`。

SKU 价格和库存保存到 `product_sku`：

- `taobao_price`：淘宝当前 SKU 价格。
- `stock`：当前 SKU 库存。
- `normal_sale_price`：正常售价，用于活动前恢复商品正常价。
- `shunshou_signup_price`：顺手报名价，用于提交顺手活动报名。

PXI 保存到 `product_pxi`。默认取数日期规则：

- 09:00 前默认取前天。
- 09:00 后默认取昨天。
- 手动填日期时按手动日期请求。

### 顺手报名

顺手报名涉及三类数据：

- `shunshou_activity`：活动 ID、活动名称、活动状态、报名容量。
- `shunshou_activity_item`：某活动下某商品的状态，例如可报名、已参加活动、其他原因。
- `product_sku`：SKU 正常价、顺手报名价、库存。

当前主流程：

```text
获取活动ID
获取活动商品
获取商品列表 / SKU / 飞书价格 / PXI
获取符合条件商品
在商品行中选择活动
提交报名变更
```

符合条件商品默认规则：

- 商品出售中。
- PXI 分大于设置值，默认 70。
- 累计销量大于等于设置值，默认 3。
- 至少一个有效 SKU 有顺手报名价。
- 默认已报名活动数为 0 到 0，即默认只看未报名商品。

可选筛选：

- 商品 ID：用于单独处理某个商品。
- 已报名活动数最小值。
- 已报名活动数最大值。

前端交互边界：

- 表格左侧勾选只代表选中商品，主要用于一键修改。
- 活动弹窗中的勾选才代表报名或取消报名变更。
- 已报名活动默认勾选。
- 取消已报名活动勾选表示取消该商品在该活动中的报名。

提交边界：

顺手接口是按活动更新明细，不应按商品单独提交。提交前端会整理成两个映射：

```text
assignments_by_activity        新增报名，结构：活动ID -> 商品ID列表
remove_assignments_by_activity 取消报名，结构：活动ID -> 商品ID列表
```

后端按活动 ID 归并处理：

```text
最终商品列表 = 原已报名商品 + 本次新增商品 - 本次取消商品
```

然后每个发生变化的活动提交一次。这样可以保留原本已经报名的商品，避免因为漏带原商品导致活动报名被误取消。

## 价格规则

必须区分三种价格：

```text
taobao_price             淘宝当前 SKU 价格
normal_sale_price        正常售价
shunshou_signup_price    顺手报名价
```

报名价和正常价不能混用。

### 正常价检测

提交报名之前，当前淘宝价应等于正常售价：

```text
taobao_price == normal_sale_price
```

如果不一致，说明商品还处于活动价或异常价，需要先一键修改恢复正常价。

### 报名价检测

顺手报名价只用于提交活动报名：

```text
promotionPrice = shunshou_signup_price
```

提交前应实时拉顺手 SKU 明细，检查：

- SKU 可编辑。
- SKU 有库存。
- SKU 有顺手报名价。
- 顺手报名价符合活动返回的价格上下限。

没有顺手报名价的 SKU 默认不报名。

### 报名价变动如何处理

推荐策略：不要在普通提交时静默自动改报名价，避免错误数据直接批量提交。

正确流程：

```text
飞书价格变动
  -> 点击飞书匹配价格，更新 normal_sale_price 和 shunshou_signup_price
  -> 获取符合条件商品或报名前检测
  -> 后端用最新 shunshou_signup_price 重新校验活动规则
  -> 通过后提交报名变更
```

也就是说：

- 如果只是顺手报名价变了，不需要一键修改淘宝价格。
- 如果正常价变了，且当前淘宝价不等于新的正常价，需要先一键修改恢复正常价。
- 报名前检测必须使用数据库里的最新报名价，不使用前端旧预览缓存。

后续可以增加一个“报名价变动提示”：

- 记录上一次预览时的报名价版本或更新时间。
- 提交前发现 SKU 报名价已变化，日志提示并自动按最新价重新检测。
- 只有检测通过才提交。

## 当前已抽出的公共代码

前端：

```text
static/js/components/table.js   表格组件
static/js/components/media.js   缩略图和图片预览
static/js/core/format.js        时间、金额、数字格式化
static/js/core/state.js         页面状态和日志
static/js/core/dom.js           DOM 创建工具
```

后端：

```text
services/shunshou_utils.py      顺手状态解析、价格规则、通用转换、随机等待
```

## 后续拆分计划

暂时不继续拆 `shunshou_service.py`，因为报名提交是高风险链路，测试覆盖不足。后续拆分建议按以下顺序：

```text
shunshou_client.py
  只负责淘宝顺手接口请求和响应解析

shunshou_repository.py
  只负责 shunshou_activity / shunshou_activity_item / product_sku 数据读写

shunshou_preview.py
  只负责候选商品、活动选择预览、筛选条件

shunshou_signup.py
  只负责报名/取消报名编排和最终提交
```

拆分前应补测试：

- 一个商品新增多个活动。
- 多个商品分布到多个活动。
- 已报名商品取消某活动。
- 新增和取消同时发生。
- 已报名商品必须保留，不得被误取消。
- 报名价变化后使用最新价格检测。
- 缺正常价、价格不一致、库存为 0、SKU 不可编辑的拦截。

## 生产环境风险

当前可以本地使用，但要达到更稳定的生产形态，还需要补这些能力：

- 请求前自动 cookie 检测和刷新。
- 浏览器 profile 级别的登录态续期。
- 关键接口重试、限速、失败分类。
- 报名提交前后保存完整变更记录。
- 对提交 payload 做审计日志，便于回溯误操作。
- 更完整的单元测试和端到端测试。
- 打包时保留用户 `data/`，禁止覆盖本地数据库。

## 禁止事项

- 不要把 `shunshou_signup_price` 当成淘宝当前价去改价。
- 不要只提交本次新增商品而漏掉活动原已报名商品。
- 不要让表格商品勾选直接改变活动勾选。
- 不要用前端旧预览数据绕过提交前检测。
- 不要在未确认活动最终商品列表的情况下调用 `addOrUpdateDetails`。
