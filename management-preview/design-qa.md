# Finfusion 管理台视觉与交互验收

final result: passed

范围：用户要求“类似图中 UI 风格的简约网页”，不是对策略页逐像素复制。深色侧栏、蓝色导航选择、米白工作区、细边框卡片和清晰标题是视觉目标；内容改为 Finfusion 用户、客户端与授权管理。正式部署与真实 Casdoor 登录不属于此处的视觉通过结论。

## 证据

- Source visual truth：`D:\Finfusion Client\admin-console\reference.jpg`，1279 × 1367，用户拍摄的屏幕照片，有透视、色温、物理屏幕外区域，无法推定原网页 CSS 视口或像素密度。
- Implementation：`D:\Finfusion Client\admin-console\implementation-desktop.jpg`，1424 × 1362，浏览器 1440 × 1050 CSS 视口的全页截图，差额来自浏览器滚动条与全页高度。
- Full-view 同图比较：`D:\Finfusion Client\admin-console\comparison-full.jpg`。两幅真实图像等比例置于同一对比板，保留透视差异，不将屏幕照片误判为布局误差。
- Focused 侧栏比较：`D:\Finfusion Client\admin-console\comparison-sidebar.jpg`。品牌/菜单/组标题/底部管理员状态在放大图核对。
- 权限弹窗：`D:\Finfusion Client\admin-console\implementation-permissions.jpg`，1440 × 1050。
- 窄窗口：`D:\Finfusion Client\admin-console\implementation-mobile.jpg`，390 × 844 CSS 视口的全页截图；documentWidth 375 <= innerWidth 390，无页面横向溢出。
- 状态：桌面总览、虚构只读示例；参考状态为策略空间，两者数据内容有意不同。窄窗口没有来源截图，以适配可用性为判断标准。

## 五项视觉核对

1. Fonts / typography：Segoe UI / Microsoft YaHei 本机字体，标题 31px/600，正文 13px，表格 11px，英文小标题增加字距。延续参考的简洁无衬线层级；中文标签没有截断、重叠，客户端 ID 长文本可查看 title。未外联字体。
2. Spacing / layout：236px 固定侧栏、76px 顶栏、40px 工作区留白；204px 模块列与主卡片分列，22px 间距。保持参考主要区域关系。表格替代参考策略曲线，属于管理员任务所需的内容适配。
3. Colors / tokens：#090f20 深色侧栏、#f4f2eb 米白页面、#f8f6ef 卡片、#dedfd5 细分隔线、#244abe 强调色。未复制照片的相机暗角与屏幕色偏。状态使用浅色小标签。
4. Image / assets：复用已存在的 Finfusion 品牌 PNG；导航使用 MIT Bootstrap Icons 原始 SVG 文件，以 img 加载，没有手绘图标或图像替代物。全部 10 个实际图片引用已在浏览器确认 naturalWidth > 0。
5. Copy / content：策略文案替换为用户/API/账户管理。预览提醒持续可见，明确示例数据、未连接服务及只读操作。全局开关与实际交易就绪分别显示，没有将开启开关等同于交易可用。

## 比较与修复历史

- 首次桌面与窄窗口检查：整体布局符合风格目标；发现窄窗口跨页面导航后上次弹窗提示仍覆盖总览指标，P2。
- 修复：navigate() 主动隐藏旧提示；重载、重新捕获桌面与窄窗口。
- 修复后证据：implementation-mobile.jpg 中指标区域无遮挡；全页无页面横向溢出。最终对比板使用修复后的截图。
- 另补 dialog aria-labelledby/aria-describedby，使辅助工具读出表单名称和说明；退出登录清除交易就绪显示，避免残留状态误导。
- 最终无待修复 P0/P1/P2 项。P3：参考照片不能用于精确字体测量；可按实际显示器偏好再微调文字尺寸。

## 实际交互核查

- 5 个导航页面及 hash 刷新恢复。
- API 客户端搜索 monitor 只显示匹配记录。
- 客户端权限行按钮预填 clientId 与当前权限，没有将所有权限重置为默认。
- 创建用户、账户绑定、客户端授权弹窗打开和关闭；账户绑定正确预填 accountRef。
- 预览登录与全部管理提交禁用；全局开启、中断及分级控制禁用。
- 窄窗口横向导航可滚动，表格滚动局限于容器。
- 浏览器 error/warn 日志为空。

## 技术验证及边界

- Node --check：app.js 通过。
- Windows PowerShell 5.1：Open-Admin.ps1 -NoBrowser 通过；重复启动复用现有正确服务。
- 本地预览 POST /admin/v1/clients：405，未连接生产 API。
- 服务器隔离工作树现有 tests/test_server_api.py、tests/test_server_controls.py、tests/test_program_api.py：33 passed。
- git diff --check 与补丁反向应用检查：通过。
- 原服务器工作区仍只有原有 tests/test_server_infrastructure.py 修改；正式服务 inactive，连接验证/Nginx/Tunnel active，Casdoor inactive。
- 此轮没有验收真实身份服务、数据库写入、生产公钥批准、券商连接或订单；页面资源与管理接口的契约已保持，真实管理联调仍待部署。
