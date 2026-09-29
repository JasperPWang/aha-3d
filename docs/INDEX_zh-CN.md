# 文档索引

[English](INDEX.md)

开始任务时先阅读一次[协作说明](COORDINATION.md)，然后根据当前阶段选择下面的入口。本索引是路由表，不是必须逐项阅读的清单。已有运行时配置不要求重新阅读安装指南。

| 当前任务 | 现在阅读 |
| --- | --- |
| 代码或文档 | [Git 工作流](GIT_WORKFLOW.md)、受影响的接口和测试 |
| 新建或恢复重建 | [验收入口](WORKFLOW_ACCEPTANCE.md#declare-scope-before-downstream-work)、当前场景/任务状态、[场景技能](../.agents/skills/indoor-scene-workflow/SKILL.md) |
| 房间、家具或材质编辑 | [Blender RoomKit](../.agents/skills/blender-roomkit/SKILL.md)，以及本次操作所需的参考资料 |
| 源视频人物重建 | [运动策略](MOTION_CONTROLS.md)、[GVHMR 技能](../.agents/skills/gvhmr-body-reconstruction/SKILL.md) |
| 启动或恢复长任务 | [执行策略](RENDER_EXECUTION.md)、[运行时策略](../MACHINE.md) |
| 发布场景/演示 | [验收](WORKFLOW_ACCEPTANCE.md)、[结果](RESULTS.md) |
| 配置或修复环境 | [设置](SETUP.md)、对应组件的安装指南 |

## 参考资料查找

| 需求 | 参考资料 |
| --- | --- |
| 开发、运行并同步固定 Git 检出目录 | [Git 工作流](GIT_WORKFLOW.md) |
| 浏览资产、技能、流水线和视频 | [生成目录](catalog/README.md)、本地 [HTML 界面](catalog/index.html) |
| 浏览场景结果并批量导出演示 | [场景结果与 Gallery](RESULTS.md) |
| 在一个环境中使用核心模型 | [共享安装](install/core.md) |
| 放置自己的参考视频 | [参考视频](../references/README.md) |
| 通用输入文件和首条命令 | [示例](../examples/README.md) |
| 只安装需要的组件 | [组件安装](INSTALLATION.md) |
| 项目技能 | [技能索引](../TOOLS_AND_SKILLS.md) |
| 可复用的源运动接触修复 | [接触优化](CONTACT_REFINEMENT.md) |
| 当前场景/人物流水线及 GPT-6 参与位置 | [脚本与 GPT-6 审查](HUMAN_PIPELINE_GUIDE.md) |
| SAMURAI 退出、固定人体轨迹和接触约束 | [人物跟踪与轨迹](HUMAN_TRACKING_AND_TRAJECTORY.md) |
| 可恢复的人体实验和自动检查 | [人体自动化](HUMAN_AUTOMATION.md)、[运行器接口](../tools/human_experiments/RUNNER.md) |
| 实验性的有界轨迹优化 | [轨迹优化](TRAJECTORY_REFINEMENT.md) |
| TSDF 核心、保留背景、测量和原生视角叠加 | [Pi3X 几何参考](PI3X_GEOMETRY_REFERENCE.md) |
| 一键生成房间碰撞、支撑和稳定性报告 | [摆放检查](PLACEMENT_CHECK.md) |
| 公共坐标系中的房间/参考图像叠加与语义不确定性 | [布局检查](LAYOUT_INSPECTION.md) |
| 检查摆放错误的家具 | [场景工作流](SCENE_WORKFLOW.md#furniture-layout-review-entrypoint) |
| 视频到房间的各个阶段 | [场景工作流](SCENE_WORKFLOW.md) |
| 记录所需外观、运动和时间信息 | [场景请求](SCENE_REQUESTS.md) |
| 强制执行任务范围、证据、发现和智能体完成状态 | [工作流验收](WORKFLOW_ACCEPTANCE.md) |
| 配方、不可变快照和阶段恢复 | [流水线](PIPELINE.md) |
| Workbench/EEVEE 预览和明确的 Cycles 质量渲染 | [渲染](RENDERING.md) |
| 等待渲染并审查完成结果 | [渲染执行](RENDER_EXECUTION.md) |
| 运动指导和近似限制 | [运动控制](MOTION_CONTROLS.md) |
| 可复用家具/材质发现 | [资产](../assets/README.md) |
| 有种子的 PBR 纹理和材质对比 | [程序化材质](PROCEDURAL_MATERIALS.md) |
| 资产摆放和材质/模型变体 | [场景变体](SCENE_VARIANTS.md) |
| 正面朝向和安装点 | [资产朝向](ASSET_ORIENTATION.md) |
| 座椅和植物质量 | [资产质量](ASSET_QUALITY.md) |
| 可选 SAM3 物体分割 | [物体生成](OBJECT_GENERATION.md) |
| 网格缓存和合成轨迹 schema | [集成](../kimodo_blender/INTEGRATION.md) |
| 空白状态/交接文档 | [模板](templates/STATE.md)、[交接](templates/HANDOFF.md) |
| 此代码包执行过的检查 | [验证](VALIDATION.md) |

历史经验保留方法论观察，但不包含场景文件和视频。缺失证据引用会明确记录在 `omitted_references.json` 中；不要把这些历史报告当作一次新的运行。
