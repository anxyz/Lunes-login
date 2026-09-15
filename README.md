## 🚀 lunes host 自动登录续期（GitHub Actions）

这是一个基于 GitHub Actions 的自动化脚本，用于定时登录自动续期[lunes host](https://betadash.lunes.host/) 应用。

⚠️ 有cf盾,太垃圾的机房节点可能过不了，建议用稍微干净点的节点  [B2proxy住宅代理](https://www.b2proxy.com/signup?code=0F5133)

━━━━━━━━━━━━━━━━━━━━━━

🔐 Secrets 配置说明

| Secret 名称         | 是否必填 | 说明                                              |
|---------------------|----------|---------------------------------------------------|
| LUNES_EMAIL     | ✅ 必填  | lunes 登录邮箱                                    |
| LUNES_PASSWORD  | ✅ 必填  | lunes 登录密码                                    | 
| NODE_LINK       | ❌ 可选  | 代理链接，如 vless:// vmess:// tuic:// hysteria2:// anttls:// socks5://|
| TG_BOT_TOKEN    | ❌ 可选  | Telegram Bot Token（用于发送通知）                     |
| TG_CHAT_ID      | ❌ 可选  | Telegram Chat ID（接收通知的用户或群组 ID）              |

━━━━━━━━━━━━━━━━━━━━━━
### 代理格式（确认在v2rayN里使用正常的节点）

`NODE_LINK` 支持以下任意一种代理协议的完整分享链接（不配置则直连）：

- **VLESS**：`vless://uuid@server:port?security=reality&sni=...&type=ws&...`
- **VMess**：`vmess://base64encoded...`
- **Trojan**：`trojan://password@server:port?sni=...&type=ws&...`
- **tuic**：`tuic://uuid:password@server:port...`
- **anytls**：`anytls://uuid@server:port...`
- **hysteria2**：`hysteria2://base64@server:port...`
- **SOCKS5**：`socks5://user:pass@server:port` 或 `socks://user:pass@server:port`

### 注意事项
- 尽量添加一个干净的节点，以免过不了cf盾

### 运行与排查

- 定时任务在每月 1、15、29 日北京时间 09:00 运行（当月存在该日期时）。
- 手动运行：进入 **Actions → Auto-login-Lunes → Run workflow**。调试时可取消勾选 `发送 Telegram 通知`。
- 登录后会等待账户页面加载，再访问服务器页面。登录、验证码或服务器访问失败时，Actions 会显示失败，日志会保留当前页面地址、标题和脱敏后的页面提示。
- 配置了 `NODE_LINK` 时，代理初始化失败会终止任务；请先修复代理配置再重试。
- 历史运行记录交由 GitHub 的保留策略管理，不再每次只保留最后一次运行，便于比较问题出现前后的日志。

开发时可运行 `python3 -m unittest discover -s tests -v`。验证码 JavaScript 回归检查需要 Node.js；GitHub Actions 的 Ubuntu 环境已提供。
