<a id="rendering-engines"></a>

# 渲染引擎

[English](RENDERING.md)

日常房间、相机和运动审查默认快速光栅渲染。

| 外观要求 | 自动引擎 | 质量策略 |
| --- | --- | --- |
| 灰模/白模型 | Workbench | Matcap、凹腔、阴影、16-sample AA，保留原材质 |
| 材质预览 | EEVEE | 着色材质和场景灯光、请求采样，关闭 Raytracing |
| 显式最终质量 | Cycles | 路径追踪与降噪，显式选择 GPU/CPU |

只改变渲染，不改几何、相机时间或人体运动。EEVEE 与 Cycles 的间接光、反射、玻璃、曝光可不同；全视频前审查代表帧。Workbench 不计算材质 shader nodes，material 模式拒绝它。完整渲染预检、等待和最终审查遵循[渲染执行](RENDER_EXECUTION.md)。

<a id="standalone-clips-and-stills"></a>

## 独立视频片段与静帧

用配置的 Blender 在工作站 GPU 运行下方命令。白模型用 `--mode clay`；最终路径追踪材质加 `--engine cycles --samples 48`。显式 `--cycles-device CPU` 可用 CPU Cycles。缺 GPU/图形上下文应明确失败，不能悄悄把快预览变慢 CPU 渲染。省略 stills 并提供 ffmpeg 渲染完整时间轴。旧 clip helper 相机导出限制见技能工作流。

任务脚本每个渲染进程调用 `roomkit.configure_render(scene, mode, samples, engine='auto')`，返回实际设置用于报告。新材质渲染清除灰模覆盖，不改源文件。源灯光须存在；写独立输出并保留原 blend。

```bash
"$BLENDER_BIN" -b /absolute/scene.blend --python-exit-code 1 \
  --python .agents/skills/blender-roomkit/scripts/render_clip.py -- \
  --out /absolute/new-preview --mode material --samples 32 --stills 1,60,120
```


<a id="pipeline-recipes"></a>

## 流水线配方

新配方默认 material/auto（EEVEE）；clay/auto 为 Workbench；engine: cycles 为路径追踪。mode: preserve 保留源材质覆盖和色彩，auto 保留保存引擎，是显式选项不是默认。EEVEE 光追关闭。

组装记录实际引擎；渲染重开保存场景使用该引擎，不强制 Cycles，并重新配置进程本地设备。帧收据绑定引擎设置，拒绝混合配置。

`indoor preview RUN` 默认 GPU/快引擎；显式 `--backend cpu` 保留无图形上下文的 CPU Cycles。显式 Cycles 配方保留请求。低分辨率全轴预览和原分辨率关键帧记录设置。旧不可变快照保持旧实现，采用新行为需准备新运行。已有场景脚本不自动改变，未来渲染需采用共享 helper。

```json
{"render": {"mode": "material", "engine": "auto", "samples": 32}}
```


<a id="performance-boundaries"></a>

## 性能边界

比较时固定场景、相机、帧 ID、分辨率和硬件，首帧编译/设置与后续时间分开报告。render operator 时间含同步和 PNG 输出，不隔离光栅/追踪与 CPU 场景评估、I/O。

关闭 RT 不消除模型导入、依赖图更新、修改器/形态键评估、参考裁剪、边网格构建、PNG 编码、共享文件系统写入。Pi3X 布局检查已用 Workbench，几何准备需单独分析。帧输出、全视频解码和时间检查仍是交付部分。

<a id="validation-baseline"></a>

## 验证基线

2026-09-12，Blender 5.2.1、96 GB RTX PRO 6000，在同一已保存室内场景上渲染 5 个 1280×720 原生相机视图。排除每配方首帧的 operator 中位时间：

| 预览配方 | 秒/帧 | Cycles 对照 | 比率 |
| --- | --- | --- | --- |
| Workbench clay，16 AA | 0.215 | Clay 16 samples：1.095 | 5.1x |
| EEVEE material，32 samples，RT off | 0.232 | Material 48 samples：1.344 | 5.8x |

这是不同着色/采样的预览配方对比，不是同质量引擎对比，5 帧测量不保证全视频吞吐。Workbench/EEVEE 首帧为 0.576/1.570 s。5 视图均审查；EEVEE 保留可辨材质/布局，但反射和间接光不同；Workbench 突出形状。

真实 Blender 检查覆盖引擎选择、shader 保留、material 去灰模覆盖、保存 Workbench 重开、帧收据复用。两快引擎通过 12 帧/1 秒合成动画和完整 MP4 解码。流水线预览/关键帧保留显式曝光。该 GPU 无头 EEVEE/Workbench 成功；其他 Blender/驱动、WSL2 OpenGL 和 24 GB 仍需运行时检查。无图形上下文用 backend cpu 或显式 Cycles。
