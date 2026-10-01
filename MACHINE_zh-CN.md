# 运行时策略

[English](MACHINE.md)

流水线运行在一台 Linux 工作站（Ubuntu 或 Windows WSL2）和一块 NVIDIA GPU 上。没有调度器，每个阶段直接在本机执行。安装与运行时配置见[设置](docs/SETUP_zh-CN.md)。

## 硬件

目标硬件为单块 24 GB NVIDIA GPU（RTX 4090 / RTX 6000 Ada 级别）、当前版本驱动，以及足够容纳权重、缓存和渲染结果的内存与磁盘。

原流水线只在一块 96 GB NVIDIA RTX PRO 6000 上验证过。更小显存是目标但尚未测试。Pi3X 64 帧推理、SAM3 跟踪、带 Llama 文本编码器的 Kimodo 和 Cycles 渲染等重型阶段可能需要采用 32 帧档位、降低分辨率或像素上限、缩短视频或减小批量。任何降低规格的操作都应随结果记录。

## 环境

使用隔离的 Python 环境，以及单独提供的 Blender 和模型资产。本地可执行路径与缓存属于配置（`configs/runtimes/local.json`、`kimodo_blender/env.local.sh`）；源代码不包含个人部署配置。不要修改其他项目或共享环境来适配本项目。

每个 shell 都需 source `kimodo_blender/env.sh`。CPU 线程数依次取自 `INDOOR_THREADS`、运行时配置的 `threads`、全部核心。GPU 使用配置的 `gpu`（默认 0），或已设置的 `CUDA_VISIBLE_DEVICES`。

本地运行单元测试：

```bash
source kimodo_blender/env.sh
python -m unittest discover -s tests -v
```

## 执行

- 同时只运行一个 GPU 任务。批量任务在脱离终端的本地后台 worker 中顺序执行，不要同时启动另一 GPU 阶段。
- 使用新的输出目录，不覆盖先前结果。
- 进程结束不证明任务完成；检查退出码（`*.log.exit`）、日志和验证产物。
- 只停止当前任务启动的进程。
- 日志、配置和命令中不要包含凭据或 token。
