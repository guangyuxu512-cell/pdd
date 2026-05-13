# 淘宝工具箱

按 `万能壳技术选型与AI预留.md` 收缩落地的第一阶段工程骨架：本地 FastAPI 后端、SQLite/SQLModel 数据层、店铺管理、运行配置、数据目录、任务表 + 线程池并发调度。

## 已包含

- 店铺管理：`/api/shops`
- 任务管理与自动补位调度：`/api/tasks`、`/api/tasks/dispatch`
- 请求日志和任务日志：`/api/logs/requests`、`/api/logs/tasks`
- 本地配置：`/api/config`
- 数据目录默认：`%APPDATA%/UniversalShell`

当前边界：只做店铺、配置、独立实例和并发底座。后续每个平台请求能力可以拆成不同应用，不在这个壳里混合平台业务。

## 启动后端

```powershell
.\scripts\run_backend.ps1
```

启动后打开：

```text
http://127.0.0.1:8800/docs
```

## 一键启动

Windows 下可以直接双击：

```text
start_app.cmd
```

它会打开一个后端命令窗口，并自动打开内置管理页面：

- 管理页面：`http://127.0.0.1:8800/`
- API 文档：`http://127.0.0.1:8800/docs`

使用时不要关闭后端窗口。停止时可以双击：

```text
stop_app.cmd
```

## 当前前端架构

当前可用界面由 FastAPI 直接托管，不依赖 Vite：

```text
backend/app/static/
  index.html                 页面入口
  assets/app.css             全局布局和组件样式
  js/api/client.js           API 请求封装
  js/core/dom.js             DOM 小工具
  js/core/state.js           菜单和业务日志状态
  js/components/shell.js     左菜单 + 右工作区壳
  js/components/table.js     可复用表格组件
  js/modules/shops/          店铺管理
  js/modules/products/       商品管理
  js/modules/logs/           固定业务日志面板
  js/modules/settings/       运行配置
```

布局固定为：左侧功能菜单，右侧上方操作区，右侧下方业务日志区。

## 店铺登录态流程

店铺管理现在采用网页登录流程：

```text
点击“网页登录”
系统自动分配一个独立浏览器 Profile
自动打开 https://loginmyseller.taobao.com/
人工完成淘宝商家后台登录
点击“读取店铺信息并保存”
系统自动用 `_m_h5_tk` 生成 mtop sign，并请求淘宝店铺信息接口
自动抓取店铺名和店铺 ID
保存到 SQLite
店铺进入列表
```

如果 cookie 失效，店铺行点击“重新登录”，会尽量复用该店铺原来的浏览器 Profile。

新增店铺只建议保存 `main` 普通 cookie。`promotion` 推广 cookie 需要绑定已有店铺，建议从店铺行点击“重新登录”后再保存。

当前淘宝版刷新状态时，会使用 SQLite 中最新保存的普通 cookie 做基础存在性检测。真实接口请求仍通过通用 `RequestClient` 复用店铺 cookie、UA 和请求日志能力。

Cookie 快照表已预留 `cookie_type`：

```text
main       普通商家后台 cookie
promotion  推广 cookie，后续接推广模块时单独保存
```

旧版平台能力已收缩；后续淘宝业务接口建议在独立模块中基于 `RequestClient.from_shop(...)` 接入。

## 前端入口

当前界面由后端直接托管，常规使用只需要：

```powershell
start_app.cmd
```

浏览器打开：

```text
http://127.0.0.1:8800/
```

## 启动 Electron 壳

前端启动后再运行：

```powershell
.\scripts\run_electron.ps1
```

## 第一版边界

这个版本先做管理壳，不直接实现真实平台接口。每个平台后续可以单独复制/拆分为独立应用，使用各自的数据目录、数据库和 Profile。

## 测试店铺 CRUD

```powershell
cd backend
..\.venv\Scripts\python.exe -m unittest tests.test_shop_crud
```
