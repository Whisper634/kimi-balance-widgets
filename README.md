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

## 说明

- 所有脚本只调用官方余额/用量接口，**不走模型，不消耗任何模型额度**。
- 卡片样式使用 Kimi Work 小组件的设计变量（`--kimi-*`），在别的容器里渲染时会优雅降级。
- 凭据均为本地保存，本仓库不包含任何真实密钥。
