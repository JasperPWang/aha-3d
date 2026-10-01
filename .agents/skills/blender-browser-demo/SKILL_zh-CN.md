# Blender 浏览器演示

[English](SKILL.md)

将已保存的 aha3d Blender 场景转换为独立交互浏览器演示，支持按住抓取家具、包围盒移动限制、柜体控制，以及现有烘焙网格动画。适用于场景到 Web 的交付和无需逐场景修改查看器的重复转换。

使用维护中的项目脚本，而非复制查看器或补丁式修改场景 HTML。从工作目录或当前技能的解析路径定位 aha3d 仓库。实现位于 `tools/roomkit_browser/`。

提交前认领新的运行目录，遵循项目协作与运行时规则。此独立 CPU/浏览器流程在本地前台运行。从目标场景当前状态选择已保存的 `.blend`。源文件由后台 Blender 打开，不保存或覆盖。

```bash
python3 tools/roomkit_browser/demo.py \
  --source scenes/SCENE/blender/scene.blend \
  --out runs/SCENE/browser-RUN --blender /path/to/blender
```

无需场景配置。命令会发现已有语义根、完整旧式家具 empty、原生或受支持的 `Open` 柜体控制，以及形态键/骨架网格动画。它计算总览/平面取景和屋顶剖切，构建自包含 HTML 并运行浏览器检查。保留源帧范围和 FPS，不生成新人体动作。

按 `tools/roomkit_browser/README.md` 安装 Node 依赖和 Playwright 浏览器。

命令结束不代表交付完成。检查 `run.json`、`discovery.json`、`validation.json` 和 `orbit.png`/`plan.png`。失败保留 `pipeline.log`；修复可复用实现后在新运行目录重试。不要悄悄手改单个场景配置以绕过自动 QA。

自动识别是保守的。未归属的散网格保持静态，并在发现结果中列出。不支持的/嵌套关节活动或变化的网格拓扑会导致导出失败。不要声称所有物体可拖拽，或推断的根已证明语义完整。保留既有语义元数据和支撑 ID；新制作场景应使用项目的完整物体语义资产契约。已有角色动画仅回放，不会感知碰撞或重新规划。

访问时优先复用已有预览服务器。添加 `--serve /absolute/server-root/scene-name.html` 可在验证后原子镜像 HTML；也须认领该准确输出。该标志不启动服务器。需要服务器时，用 Python HTTP 在可用远程端口提供输出目录并保留进程。通过应用打开远程服务地址，不把浏览器本地转发端口当作远程目标。交付 URL 前确认 HTTP 成功；文件系统路径本身不等于可访问网站。

schema、限制和依赖见项目 `tools/roomkit_browser/README.md`。抓取和 AABB 限制属于共享查看器行为，后续转换能直接继承修复，无需自定义 HTML。

请求桌面物理或程序化替换时加 `--tabletop`。它使用注册资产模板、明确桌面支撑发现、凸刚体碰撞和有种子的初始摆放。除常规 QA 外，还要检查 `tabletop-validation.json` 和 `tabletop-original.png`/`tabletop-final.png`。当前替换范围为桌面物体；椅子替换使用 `--chairs`。区分物理假设和源动画限制，扩展前阅读 README 的 “Tabletop physics and seeded swaps”。

侧栏默认打开 Scene graph，显示实时世界包围盒布局、指定支撑边、关节值、联动选择和 JSON 下载。Controls 标签保留交互控制。修改层级或布局展示时检查 `scene-graph-validation.json` 和图截图。支撑分组并不证明当前物理接触。

完整椅子替换使用 `--chairs`，并指定可信的规范源椅根。它保留座位数、原生资产尺度和朝向，针对组件代理、所有已导出人体帧、采样柜体运动和相对导航验证当前位置，再应用整组替换。共享源模型的椅子获得一种匹配的同声明座椅类型替代。缺失类型元数据或无替代项时保留当前布局。替换保留椅锚点，替换前后都能拖拽；源模型不能计为替换。

检查 `chair-validation.json` 和 `chairs-*.png`。准确限制见 README；这些检查不证明人体工学合规或连续接触。
