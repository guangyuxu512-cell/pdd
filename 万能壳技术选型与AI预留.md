# 万能壳技术选型与 AI 预留

## 结论

第一版建议这样定：

```text
前端：Vue 3 + Vite + Pinia + Element Plus
桌面壳：Electron
后端：FastAPI + Python
数据库：SQLite 本地库
ORM：SQLModel
数据库迁移：Alembic
请求组件：HTTPX
重试组件：Tenacity
浏览器登录：Playwright Persistent Context
任务调度：任务表 + ThreadPoolExecutor
AI 预留：独立 AI Service，只做判断和文案生成，不直接执行平台操作
验证码预留：CaptchaService，支持人工、第三方、自建识别
```

不要一开始就上太重的架构。你现在一般并发 5 个店铺以内，本地 SQLite + FastAPI + 线程池够用。等后面任务量、机器数量、平台数量上来，再升级 MySQL/PostgreSQL、Redis、Celery。

## 总体架构

```text
Electron 桌面壳
  |
  | 调用本地接口
  v
FastAPI 后端服务
  |
  | 读写数据
  v
SQLite / MySQL
  |
  | 执行平台请求
  v
平台插件：拼多多 / 淘宝 / 抖音 / 其他平台
  |
  | 登录态维护
  v
Playwright 浏览器 Profile
```

桌面壳只负责界面、店铺管理、任务查看、配置管理。真正的 cookie、请求、数据库、任务执行都放在 FastAPI 后端。

## 数据库组件

不用原生 SQL 为主。

第一版推荐：

```text
SQLModel
```

原因：

```text
和 FastAPI 很搭
模型定义简单
少写重复代码
底层还是 SQLAlchemy
以后可以平滑升级复杂写法
```

例如店铺表、任务表、日志表、新品表，都可以先用 SQLModel 定义：

```python
from sqlmodel import SQLModel, Field
from datetime import datetime


class Shop(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    platform: str
    shop_id: str
    shop_name: str
    profile_path: str | None = None
    cookie_status: str = "unknown"
    created_at: datetime = Field(default_factory=datetime.now)
```

后面如果查询越来越复杂，再引入：

```text
SQLAlchemy 2.0 ORM
```

数据库版本管理用：

```text
Alembic
```

这样后面新增表、新增字段，不用手动到处执行建表 SQL。

## 数据库选择

第一版：

```text
SQLite
```

适合：

```text
本地单机运行
店铺数量不大
并发 5 个左右
部署简单
备份简单
```

后续升级：

```text
MySQL 或 PostgreSQL
```

适合：

```text
多台电脑共用数据
任务量变大
多人协作
需要更强的查询和锁控制
```

建议先把代码写成 ORM，不要和具体数据库绑定死。这样 SQLite 换 MySQL 时，业务代码不用大改。

## 请求组件

不用每个接口都原生写一堆 `requests.post(...)`。

第一版推荐：

```text
HTTPX
```

原因：

```text
API 和 requests 接近
支持连接池
支持同步和异步
超时控制清楚
后续更容易做统一封装
```

再配：

```text
Tenacity
```

用来做：

```text
失败重试
限流等待
超时重试
指定错误码重试
```

平台请求不要散落在业务里，统一包一层：

```text
RequestClient
```

RequestClient 负责：

```text
cookie 注入
公共 headers
anti-content 生成
代理配置
超时设置
请求日志
响应日志
敏感信息脱敏
错误码标准化
重试策略
```

业务插件只写平台逻辑，例如：

```python
result = client.post_json(
    "/goods/chance/publish",
    json=payload,
    extra_headers={"anti-content": anti_content},
)
```

这样后续拼多多、淘宝、抖音都可以共用同一套请求底座。

## Playwright 和 Requests 的分工

推荐设计：

```text
Playwright：只负责登录、短信验证、保持浏览器 Profile、提取 cookie
HTTPX：负责大部分接口请求
```

不要所有流程都用 Playwright 点页面。浏览器适合处理登录态，接口适合跑任务。

每个店铺一个独立 Profile：

```text
profiles/
  pdd/
    shop_10001/
    shop_10002/
  douyin/
    shop_20001/
```

这样 cookie、localStorage、设备痕迹、登录态不会互相污染。

## 插件模式

壳不要写死平台请求。建议每个平台一个插件目录：

```text
backend/
  app/
    core/
      db.py
      request_client.py
      task_runner.py
      browser_profile.py
      ai_service.py
    models/
      shop.py
      task.py
      log.py
    plugins/
      pdd/
        client.py
        login.py
        chance_goods.py
        promotion.py
        order_export.py
      douyin/
        client.py
        login.py
```

平台插件只关心自己的接口：

```text
拼多多插件：拼多多 cookie、anti、机会商品、全站推广、订单导出
抖音插件：抖音 cookie、签名、商品、推广
淘宝插件：淘宝 cookie、商品、订单
```

核心壳只负责：

```text
店铺
账号
浏览器 Profile
任务
日志
数据库
AI
```

## 任务系统

第一版不用 Celery。

推荐：

```text
任务表 + ThreadPoolExecutor + 店铺锁
```

任务表字段大概：

```text
id
platform
shop_id
task_type
status
priority
payload_json
result_json
error_message
retry_count
created_at
started_at
finished_at
```

状态：

```text
pending
running
success
failed
cancelled
```

关键点：

```text
同一个店铺同一时间只跑一个高风险任务
不同店铺可以并发
默认并发 3-5 个
失败任务可以重试
每次请求和返回都落日志
```

后续任务量大了，再升级：

```text
Redis + RQ
或
Celery + Redis
```

## AI 预留

AI 要先预留，但定位是“判断和生成回复”，不是让 AI 直接执行平台操作。

第一版建议做成独立模块：

```text
AIService
```

AIService 只提供判断和生成能力，不直接操作平台：

```text
标题优化
商品 JSON 包检查
接口报错解释
订单/推广报表分析
30 天无单商品清理建议
类目/属性补全建议
同款搜索结果排序建议
日志异常归因
售后场景判断
售后回复生成
客服话术生成
平台消息分类
```

AI 输出只进入“建议/草稿/候选回复”，不要直接执行：

```text
AI 分析 -> 生成建议/回复草稿 -> 人确认 / 规则确认 -> 再由业务流程执行
```

比如售后场景：

```text
读取售后消息
读取订单、物流、商品、历史沟通
AI 判断售后类型
AI 生成回复草稿
前端展示给人工确认
确认后再发送
```

这样 AI 不掌握平台执行权限，风险低，也方便后续换模型。

建议预留这些表：

```text
ai_prompt_template
ai_task
ai_result
ai_model_config
```

### ai_prompt_template

用于管理提示词版本：

```text
id
name
scene
version
prompt_text
enabled
created_at
updated_at
```

### ai_task

用于记录每次 AI 调用：

```text
id
scene
input_json
status
model_name
prompt_version
created_at
finished_at
```

### ai_result

用于保存 AI 返回结果：

```text
id
ai_task_id
result_json
summary
confidence
created_at
```

### ai_model_config

用于以后切换不同模型：

```text
id
provider
model_name
base_url
api_key_name
enabled
created_at
updated_at
```

API key 不要明文存在普通表里。第一版可以放本地 `.env`，后面再加加密存储。

## AI 接入方式

后端统一封装：

```python
class AIService:
    def analyze_goods_payload(self, payload: dict) -> dict:
        ...

    def explain_error(self, request_log: dict, response_log: dict) -> dict:
        ...

    def suggest_cleanup(self, goods_stats: list[dict]) -> dict:
        ...
```

业务代码不要直接调用具体模型接口。这样以后换模型，只改 AIService。

## 数据库连接配置

数据库接口不要在打包时写死进代码，也不建议只靠一个固定 JSON 文件。

推荐方式：

```text
前端系统设置页面配置
后端保存到本地配置库或配置文件
敏感字段加密保存
启动时读取配置
支持前端一键测试连接
```

第一版可以这样：

```text
默认内置 SQLite，本地直接可用
系统设置里预留 MySQL/PostgreSQL 配置
用户填写 host、port、database、user、password
点击测试连接
测试通过后保存
```

配置保存位置建议：

```text
普通配置：SQLite config 表
敏感配置：系统凭据管理器或本地加密文件
```

如果第一版先简单做，也可以先放 `.env` 或 `config.local.json`，但这更适合开发阶段，不适合最终交付给用户长期使用。

### 不同配置方式对比

```text
打包时写死 JSON：
不推荐。每换电脑、换数据库、换密码都要重新改文件，后续维护麻烦。

前端系统设置：
推荐。用户可以自己改数据库、AI key、并发数、浏览器路径、代理等配置。

.env：
适合开发和内测。简单，但普通用户不方便操作。

config.local.json：
可以作为系统设置的落地文件，但不要让用户手动改，应该由前端设置页写入。
```

建议第一版配置分层：

```text
默认配置：程序内置
本地配置：config.local.json 或 SQLite config 表
敏感配置：加密保存
运行配置：启动时合并生成
```

## 系统设置建议

前端系统设置里建议预留这些页面：

```text
基础设置
数据库设置
AI 设置
浏览器设置
并发设置
代理设置
日志设置
平台插件设置
```

数据库设置字段：

```text
数据库类型：SQLite / MySQL / PostgreSQL
SQLite 文件路径
host
port
database
username
password
测试连接按钮
保存按钮
```

AI 设置字段：

```text
AI 服务商
模型名称
base_url
api_key
超时时间
最大回复长度
温度参数
测试 AI 按钮
```

后续如果售后要用 AI，可以再加：

```text
售后判断提示词
售后回复风格
禁止自动发送开关
人工确认开关
```

## 验证码处理预留

验证码不要写死到某个平台插件里，也不要第一版就强行做自动识别。建议预留一个统一模块：

```text
CaptchaService
```

它只负责验证码识别流程，不负责具体业务请求。

第一版先支持：

```text
人工处理
```

也就是任务遇到验证码时：

```text
1. 后端识别到需要验证码
2. 任务状态改成 waiting_captcha
3. 前端弹出提醒
4. 用户在浏览器里手动完成验证码
5. 后端重新提取 cookie / token
6. 任务继续执行或重新排队
```

后续再扩展：

```text
第三方打码平台
自建 OCR / 视觉模型
平台专用验证码处理器
```

### 为什么要预留

不同平台验证码差异很大：

```text
滑块
点选
文字识别
短信验证
扫码验证
行为验证
无感验证失败后的二次验证
```

如果一开始写死，后面换平台会很难维护。统一抽象之后，每个平台只需要告诉系统“遇到验证码了”，具体怎么处理交给 CaptchaService。

## 验证码接口设计

建议后端预留这些接口：

```text
POST /api/captcha/challenges
GET  /api/captcha/challenges/{challenge_id}
POST /api/captcha/challenges/{challenge_id}/submit
POST /api/captcha/challenges/{challenge_id}/cancel
POST /api/captcha/providers/test
```

### 创建验证码任务

平台插件遇到验证码时，创建一个 challenge：

```json
{
  "platform": "pdd",
  "shop_id": "10001",
  "scene": "login",
  "captcha_type": "manual",
  "page_url": "https://...",
  "screenshot_path": "data/captcha/xxx.png",
  "payload_json": {}
}
```

后端返回：

```json
{
  "challenge_id": "cap_20260511_000001",
  "status": "waiting"
}
```

任务系统看到 `waiting` 后暂停当前任务。

### 提交验证码结果

人工或第三方处理完后，提交结果：

```json
{
  "challenge_id": "cap_20260511_000001",
  "status": "solved",
  "result": {
    "ticket": "...",
    "randstr": "...",
    "cookie_updated": true
  }
}
```

不同验证码返回字段可能不同，所以 `result` 保持 JSON，不要一开始设计得太死。

## 验证码数据库表

建议预留一张表：

```text
captcha_challenge
```

字段：

```text
id
platform
shop_id
task_id
scene
captcha_type
provider
status
page_url
screenshot_path
payload_json
result_json
error_message
created_at
updated_at
expired_at
```

状态：

```text
created
waiting
solving
solved
failed
cancelled
expired
```

provider：

```text
manual
third_party
self_hosted
platform_specific
```

## 验证码 Provider 设计

统一定义一个接口：

```python
class CaptchaProvider:
    name: str

    def can_handle(self, challenge: dict) -> bool:
        ...

    def solve(self, challenge: dict) -> dict:
        ...
```

第一版先做：

```text
ManualCaptchaProvider
```

后续可以加：

```text
ThirdPartyCaptchaProvider
SelfHostedCaptchaProvider
PddCaptchaProvider
DouyinCaptchaProvider
```

第三方打码配置不要写死，放在系统设置：

```text
服务商名称
api_url
api_key
超时时间
最大重试次数
余额查询接口
启用状态
```

## 验证码和任务的关系

任务遇到验证码时不要直接失败，应该进入等待状态：

```text
running -> waiting_captcha -> running -> success
```

如果超时：

```text
running -> waiting_captcha -> failed
```

任务日志里要记录：

```text
哪个店铺遇到验证码
哪个接口触发
当时请求场景
截图路径
处理方式
处理结果
等待耗时
```

## 验证码处理原则

第一版建议保守处理：

```text
优先人工处理
浏览器 Profile 保持登录态
处理完成后重新提取 cookie
接口请求继续走 HTTPX
```

不要一开始投入大量时间研究自动验证码。先把“遇到验证码系统不崩、任务可暂停、人工可接管、后续可扩展第三方”做好。

## 推荐第一阶段功能

第一阶段先做这些：

```text
1. 店铺管理
2. 浏览器 Profile 管理
3. cookie 状态检测
4. 手动打开店铺浏览器登录
5. 提取 cookie
6. 请求插件执行
7. 任务列表
8. 请求日志
9. MySQL/SQLite 数据管理
10. AI JSON 包检查
```

不要第一版就做太多平台。先用拼多多跑通壳、插件、任务、日志、数据库，后面再接抖音、淘宝。

## 依赖建议

后端核心依赖：

```text
fastapi
uvicorn
sqlmodel
sqlalchemy
alembic
pydantic-settings
httpx
tenacity
playwright
python-dotenv
```

前端核心依赖：

```text
vue
vite
pinia
vue-router
element-plus
axios
```

桌面壳：

```text
electron
```

如果后面想更轻量，再考虑 Tauri。

## 最终建议

第一版不要追求“万能到什么都能做”，而是先把底座做稳：

```text
店铺隔离
浏览器 Profile 固定
cookie 可检测
请求统一封装
任务可追踪
日志可回放
数据库结构可迁移
AI 能力可插拔
```

只要这几个点稳，后续新增平台就是加插件，不是重写软件。

## 多店铺部署建议

不要每个店铺单独打包一个 exe。

推荐方式：

```text
一个 exe
多个店铺配置
每个店铺一个独立浏览器 Profile
每个店铺独立 cookie / 设备信息 / 任务状态
```

也就是软件本身只打包一次，店铺是在系统里新增，不是靠重新打包。

如果每个店铺都重新打包，会有这些问题：

```text
版本难维护
配置难统一
bug 修复要重新分发很多份
数据库结构升级麻烦
日志分散
后续多平台扩展困难
```

正确做法是：

```text
程序包：固定
店铺数据：运行时配置
数据库：运行时保存
浏览器 Profile：运行时生成
平台插件：随版本升级
```

## 多店铺数据库选择

### 单台电脑跑多个店铺

如果是一台电脑跑多个店铺，第一版可以全部用 SQLite。

推荐：

```text
一个本地 SQLite 数据库
所有店铺数据都放进去
所有业务表都带 platform、shop_id、shop_name
```

不要每个店铺一个 SQLite，除非你明确要把店铺数据完全拆开。

一个 SQLite 更方便：

```text
统一查询
统一备份
统一升级表结构
统一看任务和日志
跨店铺统计方便
```

注意点：

```text
开启 WAL 模式
写入操作尽量短事务
任务日志可以批量写
同一个店铺加任务锁
数据库定期备份
```

SQLite 适合：

```text
本地单机
几十个店铺以内
并发 3-5 个任务
以自动化请求和轻量报表为主
```

### 多台电脑分别跑店铺

如果以后是多台电脑分别跑不同店铺，不建议只靠每台机器自己的 SQLite。

因为会出现：

```text
数据分散
总后台看不到全局状态
任务重复执行不好控制
跨机器统计困难
备份困难
配置不统一
```

这时建议两种模式。

#### 模式一：中央数据库

```text
每台电脑安装同一个 exe
每台电脑运行本地 FastAPI 后端
所有电脑连接同一个 MySQL/PostgreSQL
```

适合：

```text
多机器协作
店铺数量多
需要统一看任务、日志、商品、订单、售后
```

推荐数据库：

```text
PostgreSQL 优先
MySQL 也可以
```

每台电脑需要一个机器编号：

```text
worker_id
device_name
allowed_shop_ids
heartbeat_at
```

任务表里增加：

```text
assigned_worker_id
locked_at
lock_expired_at
```

这样可以避免多台电脑抢同一个店铺任务。

#### 模式二：本地 SQLite + 中央同步

```text
每台电脑本地 SQLite
关键结果定时同步到中央库
```

适合：

```text
网络不稳定
希望本地离线也能跑
中央只做汇总和查看
```

缺点是同步逻辑更复杂，第一版不建议直接上。

## 多电脑分组管理

如果你的模式是：

```text
A 电脑管理 30 个店铺
B 电脑管理另外 30 个店铺
```

第一版最推荐：

```text
每台电脑独立运行同一个 exe
每台电脑有自己的本地 SQLite
每台电脑只保存自己负责的店铺
每台电脑只跑自己负责的任务
```

也就是：

```text
A 电脑：
  app.db
  profiles/pdd/shop_001
  profiles/pdd/shop_002
  ...
  profiles/pdd/shop_030

B 电脑：
  app.db
  profiles/pdd/shop_031
  profiles/pdd/shop_032
  ...
  profiles/pdd/shop_060
```

这种方式最简单，也最稳：

```text
不会互相抢任务
不会互相污染 cookie
不会因为一台电脑异常影响另一台
不需要一开始就上中央数据库
```

缺点是：

```text
A 和 B 的数据天然分散
如果想看全局统计，需要后续做同步或中央库
```

## 并发 5 个自动补位

可以做到自动补位。

每台电脑本地设置：

```text
最大并发数：5
```

任务调度逻辑：

```text
1. 扫描本机负责的店铺
2. 找出可执行任务
3. 同时启动最多 5 个
4. 任意一个任务完成
5. 自动从等待队列里补上下一个
6. 一直保持最多 5 个并发，直到没有可执行任务
```

也就是：

```text
30 个店铺排队
先跑 5 个
完成 1 个，补 1 个
完成 2 个，补 2 个
直到 30 个都跑完
```

关键是任务表要支持排队状态。

任务状态建议：

```text
pending
running
success
failed
waiting_login
waiting_captcha
paused
cancelled
```

调度器只捞这些任务：

```text
status = pending
店铺启用
cookie 有效
没有验证码等待
没有登录等待
next_run_at <= 当前时间
```

同时要有店铺锁：

```text
同一个 shop_id 同一时间只允许一个任务 running
```

这样不会出现一个店铺同时跑“上传商品”和“推广”导致 cookie、请求、状态互相打架。

## 自动补位规则

每个任务结束后，调度器释放一个并发槽位：

```text
running_count < max_concurrency
```

然后继续取下一个任务：

```text
按优先级 priority
按计划时间 next_run_at
按上次执行时间 last_run_at
```

建议排序：

```text
高优先级任务优先
到点任务优先
长时间没跑过的店铺优先
失败重试次数少的优先
```

如果某个店铺遇到验证码：

```text
当前任务 -> waiting_captcha
释放并发槽位
调度器补上下一个店铺
```

如果某个店铺 cookie 失效：

```text
当前任务 -> waiting_login
店铺 cookie_status -> invalid
释放并发槽位
调度器补上下一个店铺
```

这样不会因为一个店铺卡住，导致 5 个并发槽位被长期占死。

## A/B 电脑是否需要中央数据库

第一版不一定需要。

如果你只需要：

```text
A 电脑看 A 的 30 个店铺
B 电脑看 B 的 30 个店铺
```

那就：

```text
每台电脑本地 SQLite
```

如果你后续需要：

```text
一个总后台看所有 60 个店铺
统一看任务状态
统一看订单、商品、售后、推广
统一分配任务给 A/B 电脑
```

那就升级为：

```text
中央 MySQL/PostgreSQL + worker_id
```

每台电脑作为一个 worker：

```text
A 电脑 worker_id = worker_a
B 电脑 worker_id = worker_b
```

店铺表增加：

```text
assigned_worker_id
```

调度器只跑分配给自己的店铺：

```text
assigned_worker_id = 当前电脑 worker_id
```

这样即使所有电脑连接同一个数据库，也不会抢错店铺。

## 打包后的数据目录

数据库和浏览器 Profile 不要放在 exe 安装目录里。

推荐放到用户数据目录：

```text
Windows:
%APPDATA%/YourApp/
```

例如：

```text
%APPDATA%/ShopShell/
  config.local.json
  app.db
  logs/
  profiles/
    pdd/
      shop_10001/
      shop_10002/
    douyin/
      shop_20001/
  screenshots/
  captcha/
  exports/
```

原因：

```text
软件升级不会覆盖数据
不同 Windows 用户互不影响
权限问题少
方便备份和迁移
```

## 店铺隔离字段

所有核心表都建议带这些字段：

```text
platform
shop_id
shop_name
account_id
profile_id
worker_id
```

特别是这些表：

```text
shop
browser_profile
cookie_snapshot
task
request_log
goods
order
promotion
after_sale
captcha_challenge
ai_task
```

这样后面店铺多了，不会混数据。

## 备份和升级

第一版就要预留：

```text
手动备份数据库
自动每日备份
导出配置
导入配置
数据库迁移版本号
启动时自动执行迁移
```

SQLite 备份建议：

```text
保留最近 7 天每日备份
重要任务执行前备份一次
升级版本前备份一次
```

数据库迁移用 Alembic，不要每次靠手动建表。

## 推荐落地顺序

```text
第一阶段：
单机 SQLite + 多店铺 + 多 Profile + 本地任务

第二阶段：
增加系统设置，可切换 MySQL/PostgreSQL

第三阶段：
增加 worker_id、心跳、任务锁

第四阶段：
多电脑连接中央数据库

第五阶段：
如有必要，再上 Redis/Celery
```

你的当前场景，建议从第一阶段开始。不要先做分布式，先把单机多店铺跑稳定。
