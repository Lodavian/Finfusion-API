# Finfusion Windows / WSL2 节点

唯一支持的部署路线：Windows x64 宿主服务 + 专用 Debian 12 WSL2。

请从项目根目录的 `docs/DEPLOYMENT.md` 阅读部署、环境隔离和验收步骤，从 `docs/DELIVERY.md` 确认已验证与未验证项目。本目录包含源码与配置模板，不表示当前机器已经安装节点。

- `windows/`：Windows 服务、管理窗口、安装及卸载脚本。
- `linux/`：Finfusion、Vault、Tunnel 状态与 systemd 配置。
- `config.example.json`：默认 Sandbox，需填入域名和独立凭据。
- `python-requirements.in`：锁定 Linux 依赖，构建阶段下载到项目内 wheelhouse 并记录哈希。
- `dependencies.lock.json`：基础制品版本与校验信息。

请勿把模板当作已填写配置；不要执行来源目录中的安装脚本。正式安装从本项目生成的包运行。原项目安装包不适用于 Finfusion。
