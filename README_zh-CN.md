# AHa-3D：使用 GPT-6 Astra 的 Real2Sim 智能体工具

[English](README.md) · [项目主页](https://kevinxu02.github.io/real2sim-indoor-site/)

AHa-3D 可以将普通室内视频转换为 Blender 中可编辑的 3D 场景。它会根据参考几何和可复用的家具、材质库重建房间，估计视频中人物的运动，将人物放入同一房间并进行脚-地面和人与物接触优化，最后使用原始相机和时间轴渲染结果。项目还可以为场景中的人物生成新动作，并将保存的场景导出为可交互的浏览器演示。

## 演示

[![重建办公室的白盒渲染结果](docs/media/office48_whitebox.jpg)](https://kevinxu02.github.io/real2sim-indoor-site/)

这是一个根据 10 秒视频重建的办公室，并通过恢复出的源相机进行渲染（[MP4 视频](https://raw.githubusercontent.com/KevinXu02/aha-3d/main/docs/media/office48_whitebox.mp4)）。使用 Blender 5.2 打开可编辑场景 [examples/office48](examples/office48/README.md)。[项目主页](https://kevinxu02.github.io/real2sim-indoor-site/)同时展示源视频和重建结果，并提供交互式场景。

## 快速开始

**环境要求：** 一台运行 Linux（Ubuntu 或 WSL2）的工作站、一块 NVIDIA GPU、Python 3.11，以及用于场景组装的兼容 Blender。人物蒙皮还需要 Blender 4.5 及其 body extension。详情请阅读[运行时策略](MACHINE.md)和[三种安装级别](docs/INSTALLATION.md)。

1. **克隆项目并选择安装级别。** 安装器会在修改环境前询问你要准备 Static、Human reconstruction 还是 Robotics motion generation。

   ```bash
   git clone https://github.com/KevinXu02/aha-3d.git && cd aha-3d
   bash tools/setup.sh
   ```

   非交互运行时，使用 `--level static`、`--level human` 或 `--level robotics` 指定级别；默认不会选择任何级别。`--plan` 只显示选定方案，不执行安装。

2. **完成所选级别的模型和 Blender 配置。** Static 需要 [Pi3X/SAM3 检查点和 Blender](docs/PI3X_GEOMETRY_REFERENCE.md#runtime)。Level 2 还需要 [PMPose、GVHMR 和 body skinning](docs/install/human-motion.md)，并安装在各自的独立环境中。Level 3 在 Static 基础上增加 [Kimodo、原生 G1 和文本模型](docs/install/kimodo.md)。选择器会准备 Level 2 所需的 Static 和 SAM3 解码代码，并列出剩余安装步骤。

3. **检查所选路线并启动场景。** 对于原生 G1 运动：

   ```bash
   python kimodo_blender/check_runtime.py --model g1
   python -m unittest discover -s tests -v
   ```

   要重建自己的视频，将视频放入 `references/`，使用 `bash tools/indoor intake` 描述场景，然后按照[场景工作流](docs/SCENE_WORKFLOW.md)操作。[示例](examples/README.md)介绍了模型和运行时配置完成后的动作生成流程。

使用 `python tools/asset_index.py tree` 浏览资产。[设置指南](docs/SETUP.md)介绍仅使用源代码安装和故障排查。

## 工具

### 场景流水线：`tools/indoor`

一个命令即可驱动从请求到交付的场景处理流程。运行可以恢复，每个运行实例都会在 `runs/` 下获得自己的目录。

| 命令 | 作用 |
| --- | --- |
| `intake` | 将场景请求转换为计划，并列出缺少的决策 |
| `scenes`, `plan` | 列出场景；总结配方的阶段和运行时，但不执行任何操作 |
| `preflight` | 在运行前检查配方、输入和可选的分割边界 |
| `run`, `batch` | 前台运行一个配方，或在后台 worker 中排队运行多个配方 |
| `status` | 显示运行和 worker 进度 |
| `preview`, `review-layout`, `accept-preview` | 渲染全时长预览并记录审查结果 |
| `check-placement` | 检查已保存房间的几何结构和物体稳定性 |
| `acceptance`, `results` | 跟踪完成标准并登记选定的交付物 |

运行 `bash tools/indoor --help` 查看全部选项，详见[流水线说明](docs/PIPELINE.md)。

### 能力范围

| 领域 | 功能 | 指南 |
| --- | --- | --- |
| 房间重建 | 从源视频提取参考几何和相机，并转换为可编辑的 Blender 房间 | [Real2Sim 流水线](docs/REAL2SIM_PIPELINE.md) |
| 视频人物 | 多人物跟踪、姿态和人体估计，以及在共享房间中的对齐 | [人物流水线](docs/HUMAN_PIPELINE_GUIDE.md) |
| 运动优化 | 世界空间优化，以及带滑动和碰撞检查的脚-地面、人与物接触优化 | [接触优化](docs/CONTACT_REFINEMENT.md) |
| 动作生成 | 为场景中的人物生成或修改动作，包括物体交互 | [运动控制](docs/MOTION_CONTROLS.md) |
| 资产库 | 带有搜索和朝向元数据的家具、植物、可动柜体及程序化材质 | [资产目录](assets/INDEX.md) |
| 场景变体 | 在保存的场景中替换家具和材质，同时保留 ID 与朝向 | [场景变体](docs/SCENE_VARIANTS.md) |
| 渲染与审查 | 预览、完整渲染、视频解码检查和审查图像 | [渲染](docs/RENDERING.md) |
| 浏览器演示 | 支持家具拖拽、柜体控制和烘焙动画的交互式 Web 查看器 | [浏览器演示](.agents/skills/blender-browser-demo/SKILL.md) |

### 辅助脚本

| 脚本 | 用途 |
| --- | --- |
| `tools/asset_index.py` | 搜索并重建资产索引 |
| `tools/build_catalog.py` | 构建可浏览的目录，输出到 [docs/catalog](docs/catalog/README.md) |
| `tools/scene_variant.py` | 对场景应用家具和材质替换 |
| `tools/export_articulated_asset.py` | 导出柜体、抽屉等可操作家具 |
| `tools/configure_runtime.py` | 写入本地运行时配置 |
| `tools/task_claim.py` | 协调多个智能体或人员在同一检出目录中工作 |

项目还在 `.agents/skills/` 中提供了面向 AI 编程智能体的技能；请阅读[工具与技能](TOOLS_AND_SKILLS.md)。Opus 5.5 也可以根据初始实验驱动此仓库，但尚未经过完整测试。

## 项目结构

```text
aha-3d/
├── src/aha3d/        核心库：流水线阶段、Blender 组装、运动和工作流检查
├── tools/            命令行工具和阶段脚本
├── assets/           可复用的家具、植物和材质库
├── configs/          运行时模板、柜体布局和请求预设
├── examples/         示例场景配置
├── docs/             指南、工作流契约和安装说明
├── tests/            单元测试和可选的 Blender 集成检查
├── .agents/skills/   面向 AI 编程智能体的技能
├── references/       源视频（内容不纳入版本控制）
├── scenes/           场景工作区（内容不纳入版本控制）
└── runs/             流水线输出（内容不纳入版本控制）
```

完整指南请从[文档索引](docs/INDEX.md)开始。

## 许可证

项目作者编写的代码、技能和资产采用 [Apache License 2.0](LICENSE) 授权。发行范围见[分发说明](DISTRIBUTION.md)，模型和单独获取的库见[第三方依赖](THIRD_PARTY.md)。
