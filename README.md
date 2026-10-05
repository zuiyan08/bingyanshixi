# 冰岩实习 · 大模型接入版

一个网页聊天界面 + 一个本地小中转脚本（Python，零第三方依赖）。

网页负责界面，`llm-proxy.py` 负责把你的 **API Key 保存在本机**，并把对话以**流式**（一个字一个字）的方式转发给大模型。

> **为什么不让网页直接连厂商？**
> ① 浏览器会被跨域拦住；② 把 Key 写进网页 = 谁都能按 F12 偷走。
> 所以这里用一个小中转：Key 只存在你电脑上的 `llm-config.json` 里，网页里一个字符都没有。

## 文件说明

| 文件 | 作用 |
|---|---|
| `冰岩实习.html` | 前端页面：聊天界面、登录注册（本地演示）、新建对话、快捷标签等 |
| `llm-proxy.py` | 本地小中转：把页面托管到 <http://127.0.0.1:8000/>，并转发流式请求给大模型 |
| `llm-config.example.json` | 配置模板（**不含任何密钥**）。复制成 `llm-config.json` 后填自己的 Key |
| `完成日志` | 实习过程记录 |

## 你需要准备

1. **Python 3.9 或更新版本**。Windows 安装时记得勾选 `Add Python to PATH`；验证：命令行执行 `python --version` 有输出。
2. **一个大模型的 API Key**。两家便宜的国内厂商（地址与模型名请以官网/控制台为准）：
   - **智谱开放平台** <https://open.bigmodel.cn> —— 有免费模型可先用。`base_url` 填 `https://open.bigmodel.cn/api/paas/v4`，`model` 填控制台里带「免费」标签的模型名。
   - **DeepSeek** <https://platform.deepseek.com> —— `base_url` 填 `https://api.deepseek.com`，`model` 填 `deepseek-flash`。

**不需要**：Node.js、Docker、任何 `pip install`。

## 三步跑起来

### 第 1 步：准备配置文件

```powershell
Copy-Item llm-config.example.json llm-config.json     # Windows
```

```bash
cp llm-config.example.json llm-config.json            # macOS / Linux
```

### 第 2 步：填上你自己的 Key

用记事本打开 `llm-config.json`，把 `api_key` 换成自己的（下面用占位符表示，别照抄）：

```json
{
  "base_url": "https://open.bigmodel.cn/api/paas/v4",
  "model": "GLM-4-Flash",
  "api_key": "<YOUR_API_KEY>",
  "system_prompt": "你是一个友好、简洁的中文助手。",
  "timeout": 120
}
```

> `model` 必须填你控制台里真实存在的模型名，写错会报 `model not found`。

### 第 3 步：启动中转，然后打开网页

```powershell
python llm-proxy.py            # Windows
```

```bash
python3 llm-proxy.py           # macOS / Linux
```

看到这样的横幅就成功了：

```
  页面文件： 冰岩实习.html
  页面地址： http://127.0.0.1:8000/          ← 用浏览器打开这个
  运行模式： 真实调用
```

浏览器打开 **<http://127.0.0.1:8000/>** → 输入框打字 → 回车 → 回复会一个字一个字出现。

> **① 必须用 `127.0.0.1`，不要用 `localhost`**：Windows 上 `localhost` 往往先解析成 IPv6 的 `::1`，而中转只监听 IPv4，用 `localhost` 可能被拒绝连接。
> **② 不要直接双击 `冰岩实习.html`**：那样页面拿不到接口地址，只会提示「连不上本地中转」。
> **（可选）** 想先不填 Key 验证链路是否通：`python llm-proxy.py --mock`，会用假数据流式回复。

## 页面功能（如实说明）

- **与模型流式对话**：多轮上下文，回答逐字显示
- **新建对话**：清空当前会话与上下文
- **登录 / 注册**：仅本地演示 —— 账号密码存在浏览器 `localStorage` 里，**不是真实鉴权**
- **侧边栏**：「最近对话」「我的智能体」的下拉菜单
- **激励计划**：右上角小叉可以关掉（仅本页隐藏，刷新后恢复）
- **快捷标签 / 功能卡片**：静态展示元素

## 常见问题

| 现象 | 原因与解决 |
|---|---|
| 浏览器提示「**拒绝连接**」 | 中转没启动。确认 `python llm-proxy.py` 的窗口还开着；`netstat -ano \| findstr :8000` 应能看到 LISTENING |
| 用 `localhost` 打不开、用 `127.0.0.1` 可以 | 就固定用 `127.0.0.1` |
| 启动报 `WinError 10048` | 8000 端口被占用。关掉多余窗口，或 `python llm-proxy.py --port 9000`（页面改开 `http://127.0.0.1:9000/`） |
| 气泡里 `HTTP 401` | Key 不对或已失效：回控制台重新复制 |
| 气泡里 `HTTP 402` | 余额 / 免费额度用完了 |
| 气泡里 `HTTP 404 ... model not found` | `model` 名字写错，照控制台里的抄 |
| 气泡里 `HTTP 429` | 请求太频繁，等一会儿再试 |
| 提示「连不上本地中转」 | 中转没启动，或页面不是从 `http://127.0.0.1:8000/` 打开的 |

## 安全（重要）

- `llm-config.json` 里有你的 Key：**不要提交到 GitHub、不要发群里、不要截图**。
- 本仓库目前**还没有 `.gitignore`**，建议自己加一个，至少包含：

  ```gitignore
  llm-config.json
  *.log
  __pycache__/
  ```

  加完可以用 `git check-ignore -v llm-config.json` 验证是否生效。
- **万一 Key 泄露**（贴过群、发过截图、提交过）：立刻去厂商控制台**删掉这个 Key 并新建一个** —— 删除才能让它立刻失效。
- `llm-proxy.py` 只监听 `127.0.0.1`，局域网里的其他人访问不到，请不要改成 `0.0.0.0`。

## 已知限制

- 只能本机使用（出于安全考虑，没有绑定局域网或公网地址）。
- 对话不持久化：刷新页面后历史就没了。
- 登录 / 注册是本地演示，不构成真实用户体系。
