# 从源码构建 Windows 客户端

在本目录使用独立 Python 3.12 x64 环境：先执行 `setup-dev.ps1`，运行 `run-tests.ps1 -q` 后执行 `build-windows.ps1`。

`build-installer.ps1` 默认使用 `packaging/tools/Inno/ISCC.exe`，也可传 `-Compiler` 指定本机已准备的 Inno Setup 7.1.0 x64 编译器。工具和下载的安装器不纳入仓库。若采用 `setup-build-tools.ps1`，需先按其要求将官方编译器安装器放入本机 `packaging/vendor`，脚本会检查签名。

完整离线 WebView2 运行时放到 `packaging/vendor/MicrosoftEdgeWebView2RuntimeInstallerX64.exe`。来源及原下载校验记录见 `packaging/vendor/SOURCE.json`，下载工具见 `tools/download-runtime.py`；构建时必须重新检查微软签名。不要将编译器、运行时、下载分片或安装包提交 Git。

历史验收记录里的 `D:\Finfusion Client` 指原工程位置。新的 clone 以本目录为客户端根；运行脚本通常使用 `$PSScriptRoot`。`build`、`dist`、用户 DPAPI 私钥与请求数据库均留在本机。安装器仍为未签名内部候选，不包含在线自动更新器。
