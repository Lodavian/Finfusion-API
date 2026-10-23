> 2026-10-23 仓库汇总说明：最新整体状态见根目录 `docs/CURRENT-STATUS.md`；本文保留各阶段背景，历史机器路径不代表新 clone 的路径。

# Finfusion Client 1.0

开发版本 1.0.0-rc1。Windows x64 窗口内嵌 WebView2，复用极速下单原布局、颜色、动效和图标。客户端通过签名 Finfusion API 访问服务器，不访问券商，不保存券商 SDK 或凭据。

## 启动

项目目录 D:\Finfusion Client。运行 run.ps1；测试 run-tests.ps1；打包 build-windows.ps1、build-installer.ps1。
便携程序 dist\FinfusionClient\FinfusionClient.exe；安装器 dist\installer\FinfusionClient-Setup-1.0.0-rc1.exe。附微软完整离线 WebView2 运行时；内部候选未签名，无在线自动更新器。

## 功能和安全

配置 HTTPS 地址、clientId，生成或导入 P-256 私钥，导出公钥给管理员登记。DPAPI 按当前 Windows 用户保护私钥，网页不可获取；保存配置不代表鉴权成功。
支持账户选择、美元现金和购买力分开显示、持仓、股票候选、行情时间及盘口/成交、订单分页和详情、手动刷新及事件恢复。缺失、空持仓、过期及权限拒绝分别显示。
1.0 识别服务器明确允许的 SANDBOX/LIVE 部署及账户权限，服务器是风控和状态的最终依据。当前生产为 LIVE READ_ONLY，交易禁用。撤单权限与新单门禁独立；客户端不能开启服务器交易或改变风控。
交易先持久化唯一 UUID 和不可变内容，最多发送一次；超时/断线/500/重启后只查询原请求。待确认下单/改单阻止该账户后续新单及改单，其他账户隔离。

## 升级和存储

用户配置、DPAPI 私钥、SQLite 请求库和 WebView2 缓存位于 %LOCALAPPDATA%\Finfusion\Client，不写安装目录。保留原 AppId、互斥锁、数据目录和图标；升级/修复/卸载保留用户数据。同一 Windows 用户可继续使用旧 ZIP 数据，不将 DPAPI 私钥复制给其他 Windows 用户。
源码、SDK、UI 资源和固定依赖均归入本项目，不以 editable 安装、目录链接或 PYTHONPATH 引用旧项目。SDK/UI 来源及许可证见 docs 与 LICENSES。

## 验收

最新说明 docs\ACCEPTANCE-1.0.md；交付记录 docs\DELIVERY-1.0.md。实际只读联调和 LIVE 数据库隔离恢复已有证据。
干净 VM 安装/升级/卸载及第二电脑身份接入仍需管理员启用 Hyper-V、释放足够内存及完成 guest 安装；准备脚本见 packaging\vm\README.md，不在宿主交易电脑执行安装生命周期。
2026-10-12 的订单授权要求零成交、立即撤单，截止已延长至北京时间 19:00；真实下单无法保证零成交，本轮真实发单 0 次。模拟测试不替代真实订单验收。
Windows 长期运行设置、异机灾备、外部通知、代码签名及真实交易流转待另行完成。
