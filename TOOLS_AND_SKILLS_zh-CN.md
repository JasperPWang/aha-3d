# 项目工具与技能

[English](TOOLS_AND_SKILLS.md)

选择当前操作所需的技能，仅在必要时加载详细参考。共享策略和任务路由见[文档索引](docs/INDEX_zh-CN.md)。

| 技能 | 用途 |
| --- | --- |
| [室内场景工作流](.agents/skills/indoor-scene-workflow/SKILL.md) | 完整重建或恢复阶段 |
| [Blender RoomKit](.agents/skills/blender-roomkit/SKILL.md) | 可编辑房间、家具/材质资产、柜体和相机 |
| [Pi3X 参考](.agents/skills/pi3x-scene-reference/SKILL.md) | 源几何、相机和标注尺寸的参考视图 |
| [GVHMR 重建](.agents/skills/gvhmr-body-reconstruction/SKILL.md) | 估计源人物运动并进行固定刚性房间对齐 |
| [Kimodo 运动](.agents/skills/kimodo-body-motion/SKILL.md) | 新增/修改动作或有记录的生成式回退 |
| [SAM 3D 运动参考](.agents/skills/sam3d-motion-reference/SKILL.md) | 为生成路线提供经过审查的稀疏姿态指导 |
| [本地运行时](kimodo_blender/RUNTIME.md) | 运行时配置、后台批量 worker 和故障排查（[策略](MACHINE_zh-CN.md)） |
| [浏览器演示](.agents/skills/blender-browser-demo/SKILL_zh-CN.md) | 将已保存 Blender 场景交付为浏览器交互演示 |
| [世界空间后优化](docs/WORLD_POSTOPT.md) | 跟踪人体的修正版 v2 世界空间优化和脚接触指标 |

项目技能位于 `.agents/skills/`，其链接使用当前检出目录。系统/插件技能不属于项目源码。

## 按操作选择工具

| 操作 | 接口和详细说明 |
| --- | --- |
| 协调写入者 | `python3 tools/task_claim.py list --compact`；[协作](docs/COORDINATION.md) |
| 声明范围并强制完成 | `bash tools/indoor acceptance`；[验收](docs/WORKFLOW_ACCEPTANCE.md) |
| 浏览资产和流水线阶段 | [生成目录](docs/catalog/README_zh-CN.md)、[HTML](docs/catalog/index.html) |
| 搜索家具 | `tools/asset_index.py`；[资产索引](assets/INDEX_zh-CN.md) |
| 审查物体摆放/源匹配 | [物体审查](docs/SCENE_WORKFLOW_zh-CN.md#furniture-layout-review-entrypoint)、[布局检查](docs/LAYOUT_INSPECTION.md)、[摆放检查](docs/PLACEMENT_CHECK.md) |
| 替换场景资产 | `tools/scene_variant.py`；[场景变体](docs/SCENE_VARIANTS_zh-CN.md) |
| 导出可操作资产 | `tools/export_articulated_asset.py`；[朝向](docs/ASSET_ORIENTATION.md) |
| 配置运行时 | `tools/configure_runtime.py`；[设置](docs/SETUP_zh-CN.md) |
| 登记/选择交付物 | `bash tools/indoor results`；[结果](docs/RESULTS.md) |

修改资产、技能、阶段或演示元数据后，用 `python tools/build_catalog.py build` 和 `check` 重建面向用户的目录。共享实现位于 `src/aha3d/`；阅读源码前先使用文档中的命令。

## 请求的运动实验

[运动控制](docs/MOTION_CONTROLS_zh-CN.md)定义默认行为和授权边界。显式请求优化时，根据需要使用[接触修复](docs/CONTACT_REFINEMENT_zh-CN.md)、[轨迹实验](docs/TRAJECTORY_REFINEMENT.md)或[可恢复的人体实验](docs/HUMAN_AUTOMATION.md)。
