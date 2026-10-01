# 外部依赖

[English](THIRD_PARTY.md)

此源码包不包含第三方检出目录、已安装包、模型检查点、许可人体资产或认证状态。集成适配器仍属于项目代码，但需要另外获取下列依赖。获取或重新分发前请查阅各上游当前条款。

具体安装步骤和验证边界见[组件安装](docs/INSTALLATION_zh-CN.md)。

| 组件 | 来源 | 作用 |
| --- | --- | --- |
| GVHMR BEDLAM2 | [上游](https://github.com/mkocabas/GVHMR_BEDLAM2) | 独立运动运行时；版本 `cac2d9dacc6b4b6f145ca02c2e6e616719fff916` |
| SAMURAI | [上游](https://github.com/yangchris11/samurai) | 源人物掩码；外部模型库 |
| BBoxMaskPose/PMPose | [上游](https://github.com/MiraPurkrabek/BBoxMaskPose) | 掩码条件化的二维关键点；独立环境 |
| PyTorch3D | [上游](https://github.com/facebookresearch/pytorch3d) | GVHMR CUDA 支持；部分 v0.4.0 旋转函数附 BSD 声明随项目提供 |
| Kimodo | [上游](https://github.com/nv-tlabs/kimodo) | 运动模型代码；记录版本 `1aece8c124d73d255ceff5086d983b844c9f4e94` |
| Kimodo SMPL-X | [模型](https://huggingface.co/nvidia/Kimodo-SMPLX-RP-v1) | 外部检查点 |
| Llama 3 和 LLM2Vec | Kimodo 上游设置/下载配置 | 外部文本编码器和适配器 |
| SMPL-X 人体 | [项目](https://smpl-x.is.tue.mpg.de/) | 获授权的人体资产，不随项目提供 |
| Blender SMPL-X 扩展 | [原始扩展](https://gitlab.tuebingen.mpg.de/jtesch/smplx_blender_addon) | 适配器需要 `bl_ext.user_default.smplx_blender_addon`；见[兼容性](docs/install/blender.md) |
| Blender | [项目](https://www.blender.org/) | 资产制作、组装和渲染 |
| Pi3/Pi3X | [上游](https://github.com/yyfz/Pi3) | 仅图像输入的参考几何/相机 |
| SAM 3D Body | [上游](https://github.com/facebookresearch/sam-3d-body) | 稀疏姿态参考；MHR 模型单独提供 |
| SAM 3 | [上游](https://github.com/facebookresearch/sam3) | 可选物体分割 |
| Blender MCP | [上游](https://github.com/ahujasid/blender-mcp) | 可选交互 Blender 连接；不包含第三方插件副本 |

PyTorch、NumPy、SciPy、Pillow、FFmpeg、CUDA 等已安装依赖保留各自许可证。可复用资产清单保留来源记录。项目作者代码和资产采用 Apache-2.0；第三方代码与资产不会被重新授权。

## 随包提供的运动辅助工具

作者编写的跟踪器、相机、适配和 v2 优化辅助工具纳入[世界运动后端](tools/gvhmr/world_backend/README.md)的版本控制。它们此前是相邻 PromptHMR 检出目录中未跟踪的扩展，作者已确认其独立创作。项目不包含上游 PromptHMR 实现。

旋转兼容模块包含官方 PyTorch3D v0.4.0 的部分函数及完整上游 BSD 许可证，以保留旧数值行为。运行时隔离、已知源码版本缺口和外部模型输入见[运动安装](docs/install/human-motion_zh-CN.md)。
