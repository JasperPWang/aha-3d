<a id="installation-levels"></a>

# 安装级别

[English](INSTALLATION.md)

根据需要的输出选择安装级别。需要可编辑静态房间的新视频使用 Static；源视频人物重建需要增加 Human；机器人动作生成则在 Static 上扩展 Kimodo。如果同时需要两种能力，可以组合 Human 和 Robotics。

模型权重、人体资产和 Blender 二进制文件需要单独获取，不会随 Python 包安装。请保持完整的代码检出目录。

| 级别 | 安装内容 | 可实现功能 |
| --- | --- | --- |
| **1. Static 3D scene** | Pi3X、SAM3 分割、Open3D、兼容的 Blender，以及 Pi3X/SAM3 检查点 | 首个视频的 `build_reference`、经过审查的相机/几何和可编辑房间。不包含 GVHMR、PMPose 或 Kimodo。[参考设置](PI3X_GEOMETRY_REFERENCE_zh-CN.md#runtime)、[Blender](install/blender.md) |
| **2. Human reconstruction** | Static，加上 SAM3 跟踪/PyAV、带 MMCV 的 PMPose、带 PyTorch3D 的 GVHMR、人体模型/权重和 Blender SMPL-X 蒙皮 | 默认的源视频人物运动、v2、接触优化和烘焙场景交付。[运动栈](install/human-motion_zh-CN.md)、[GVHMR](install/gvhmr.md) |
| **3. Robotics motion generation** | Static，加上 Kimodo、原生 G1 检查点、文本模型和 G1 网格依赖 | 在可编辑房间中生成原生机器人运动。如果还需要源视频人物重建，才需要 GVHMR/PMPose。[Kimodo](install/kimodo_zh-CN.md) |

SAM 3D Body 和 DINOv3 是 Kimodo 的可选稀疏视频姿态指导，默认不属于任何级别。SAMURAI 是明确指定的替代跟踪器。[完整视频到场景路线](REAL2SIM_PIPELINE_zh-CN.md)介绍了阶段顺序和验证方式。GVHMR 使用独立环境，因为其经过验证的 PyAV 版本与 Kimodo 的共享核心存在冲突。

## 安装所选级别

所有组件安装在一台运行 Linux（Ubuntu 或 WSL2）的 NVIDIA GPU 工作站上；请先阅读[运行时策略](../MACHINE_zh-CN.md)。从代码检出根目录运行受支持的安装器：

```bash
bash tools/setup.sh
```

安装器会**在运行任何组件安装前询问要安装哪个级别（1/2/3）**。无终端脚本或 CI 环境中，必须使用 `--level static`、`--level human` 或 `--level robotics` 显式指定级别；省略级别会在修改环境前失败。使用 `--plan` 可以只查看选中的路线。不会静默选择级别。

安装器负责准备 Python 代码。Static 还需要安装 [Blender](install/blender.md) 并获取 Pi3X/SAM3 检查点。Human 的选择器会准备 Static 和 SAM3 视频解码，然后引导你安装独立的 [PMPose/GVHMR 环境](install/human-motion_zh-CN.md)、Blender SMPL-X 扩展、人体资产和权重；这些步骤完成前不会声称 Level 2 已安装完毕。Robotics 会在 Static 的 Pi3X 环境中增加 Kimodo；请遵循[对应指南](install/kimodo_zh-CN.md)获取原生 G1/文本权重和 Blender。每份指南都包含冒烟检查。

请使用隔离环境；不要为了适配新的安装而升级其他项目的 Torch，或替换已有的人体插件。

对于 Robotics 运动配方，按照[运行时设置](SETUP_zh-CN.md#5-configure-the-runtime)使用 `tools/configure_runtime.py` 注册已安装的可执行文件和 G1 模型，source `kimodo_blender/env.sh`，然后运行 `python kimodo_blender/check_runtime.py --model g1`。Human 按运动栈自己的验证步骤操作。Static 参考适配器需要显式的运行时路径和检查点。请为所选检出目录运行单元测试。版本库中的运行时 JSON 只是模板，不代表已经安装好的环境。

## 检查结果的含义

环境/版本和 CPU 导入检查只能验证安装和适配器接口。加载检查点或运行 GPU 冒烟示例可以提供额外证据，但都不能证明参考重建的保真度、运动质量或整段视频的一致性。各指南会区分历史本地验证和新记录的安装步骤。编写本指南时没有运行新的安装器，也没有下载权重。此代码包执行过的检查列在[验证](VALIDATION.md)中。

模型和人体资产需要通过接收方获授权的上游渠道获取。请将身份验证信息放在检出目录和日志之外。详见[分发状态](../DISTRIBUTION_zh-CN.md)和[外部依赖](../THIRD_PARTY_zh-CN.md)。
