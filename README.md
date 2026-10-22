# Kimi Balance Widgets

在 Kimi Work（Kimi 桌面端）看板上实时展示各家 AI 账户余额 / 用量的小组件集合。每个组件 = `index.html` 卡片 + Python 自动刷新脚本（Kimi Work Blueprint Automation），数据每 4 小时自动更新一次。

## 组件一览

| 目录 | 组件 | 数据来源 | 鉴权方式 |
|---|---|---|---|
| `widgets/volc-engine-quota` | 火山引擎模型额度 | 火山方舟控制台 ListModelChargeItems 接口 | 登录 cookie（`volc_cookies.json`） |
| `widgets/deepseek-balance` | DeepSeek API 余额 | `api.deepseek.com/user/balance` | API Key |
| `widgets/kimi-api-balance` | Kimi 开放平台余额 | `api.moonshot.cn/v1/users/me/balance` | API Key（platform.kimi.com 创建） |
| `widgets/kimi-subscription-usage` | Kimi 订阅用量 | `kimi.com` 会员网关 `GetSubscriptionStats` | kimi.com refresh_token（自动轮换） |

## 在 Kimi Work 中部署一个组件

1. **建 Widget**：用 `widget.json` 创建小组件（slots.main 为 JSON 数据槽），把 `index.html` 写入组件的 workspace。
2. **建 Automation**：创建 Python 代码自动化，`automation/` 里的脚本是入口；触发器建议 `interval 4h`。
3. **放凭据**：在自动化的 assets 目录放对应凭据文件（见下表），文件名与脚本约定一致。
4. **建 Binding**：把 Automation 结果绑定到 Widget 的 main 槽。
5. **上板**：把 Widget 放到 Canvas 任意位置。

### 各组件需要的凭据文件（放在自动化 assets/ 目录，勿提交）

| 组件 | 文件名 | 内容 |
|---|---|---|
| volc-engine-quota | `volc_cookies.json` | `.volcengine.com` 会话 cookie 数组（浏览器登录 console.volcengine.com 后导出） |
| deepseek-balance | `deepseek_key.txt` | `sk-...`（platform.deepseek.com 创建） |
| kimi-api-balance | `kimi_key.txt` | `sk-...`（platform.kimi.com 创建） |
| kimi-subscription-usage | `kimi_refresh.txt` | kimi.com 账号 refresh_token（网页登录 kimi.com 后从 localStorage 读取；脚本运行时会自动轮换更新此文件） |

## 决策字段（v0.2）

每张卡片底部多了一行「决策行」，数据由自动化脚本算好写进 slot，前端只负责渲染。

| 字段 | 含义 | 出现在 |
| --- | --- | --- |
| `level` | `ok` / `warn` / `alert`，卡片配色跟着变 | 全部 |
| `burnPerDay` | 近 N 天日均消耗（余额=元/天，订阅=百分点/天，火山=tokens/天） | 全部 |
| `daysLeft` | 按日均外推还能撑几天 | 全部 |
| `exhaustAt` | 预计用完时间（ISO） | 全部 |
| `daysToReset` | 距订阅周期重置还有几天 | 订阅 |
| `totalValueOut` / `totalValueIn` | 免费额度折算成人民币（按输出价 / 输入价） | 火山 |
| `priority` / `priorityName` | 按剩余价值从高到低排的「先烧谁」 | 火山 |
| `hint` | 一句话结论（JSON 里也带，方便将来接通知渠道） | 全部 |

**算法**：每次运行把当前值追加到 `assets/history.json`（同一 5 分钟内重复运行只留最后一个点），
取最近 `windowDays`（默认 7 天）算斜率；值上涨超过 2% 视为充值/额度重置，只用跳变之后的点，
避免把充值算成负消耗。样本不足（不足 2 点或跨度 < 0.2 天）时 `daysLeft` 给 `null`，卡片显示「攒历史中」。

**已知边界**：4 小时跑一次，刚部署时没有历史，第二天才开始有日均；外推是线性假设，遇到突发大批量使用会偏乐观。

### 阈值配置

默认：余额 ≤ ¥20 警告、≤ ¥10 告急；额度剩余 ≤ 20% 警告、≤ 10% 告急；单模型剩余 ≤ 10 万 tokens 警告。
要改就在对应自动化的 assets 目录放 `thresholds.json`（已 gitignore），字段见 `shared/thresholds.example.json`。

## 开发与自测

```bash
python3 tools/sync_shared.py --check   # 四份 insights.py 是否与 shared/ 一致
python3 tools/selftest.py              # 斜率 / 外推 / 分级 / 折算 / 去重（纯函数）
python3 tools/e2e_test.py              # 假 HTTP 跑真实 run()，验证字段真的接上了
node tools/html_render_test.mjs        # 卡片渲染（DOM 桩，不联网）
```

> ⚠️ 改了 `shared/insights.py` 后必须跑 `python3 tools/sync_shared.py`，
> 否则下发的是各组件目录里的旧拷贝。`--check` 适合放在发版前或 CI 里。

## 说明

- 所有脚本只调用官方余额/用量接口，**不走模型，不消耗任何模型额度**。
- 卡片样式使用 Kimi Work 小组件的设计变量（`--kimi-*`），在别的容器里渲染时会优雅降级。
- 凭据均为本地保存，本仓库不包含任何真实密钥。
