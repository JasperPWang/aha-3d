<a id="pi3x-initial-geometry-reference"></a>

# Pi3X 初始几何参考

[English](PI3X_GEOMETRY_REFERENCE.md)

默认参考结合 **TSDF 结构核心和保留的源上下文**，用于制作可编辑的 Blender 房间。它是近似单目几何参考，不是完成的房间或测量真值。交付顶/前/侧视图和 **3–5 个原生源相机叠加视图**（默认 5 个）；几何使用全部缓存推理帧。

该命令使用 Pi3X、SAM3 和 Open3D，属于[静态安装级别](INSTALLATION_zh-CN.md#installation-levels)的参考阶段。将参考变成可编辑静态场景还需要 Blender；人体重建和机器人运动使用独立安装级别。

<a id="runtime"></a>

## 运行时

首次为新视频构建静态参考，按下方命令安装 Pi3X、SAM3 和 Open3D。不指定 `--level static` 时安装器会询问级别。Static 为 Pi3X 推理、SAM3 分割和 Open3D 网格/叠加准备独立环境；Blender 单独安装。Human 增加 PMPose、GVHMR 和源人物蒙皮，Robotics 增加 Kimodo。

`reference` extra 固定 Open3D 0.18.0、NumPy 1.26.4 和 OpenCV headless 4.11.0.86；物体轮廓和源匹配审查也需要同环境中的 OpenCV。辅助工具不安装包。已有兼容环境可通过 `--pi3x-python`、`--semantic-runtime`、`--semantic-python`（默认 `SAM3_PYTHON`，否则运行时的 `venv/bin/python`）、`--mesh-python` 指定。

代码安装不提供权重，见 [Pi3X 检查点指南](install/pi3x.md#download-authorized-weights)。取得 [facebook/sam3](https://huggingface.co/facebook/sam3) 授权后，用下方准备命令下载并注册。SAM3 设置在运行时生成 `checkpoints/sam3.pt` 和 `runtime.json`。SAM3 分割与 SAM 3D Body 不同。已部署 Open3D 用于验证；此干净安装方案未在所有平台重跑。

| 运行时输入 | 默认值 | 覆盖方式 |
| --- | --- | --- |
| 推理 Python | 当前解释器 | `PI3X_PY` 或 `--pi3x-python` |
| Pi3 检出目录 | `external/Pi3` | `PI3X_UPSTREAM` 或 `--upstream` |
| 网格/叠加 Python | `.runtime/pi3x-mesh/venv/bin/python` | `PI3X_MESH_PY` 或 `--mesh-python` |
| SAM3 运行时根目录 | `.runtime/sam3-segmentation` | `--semantic-runtime` |
| 模型文件 | 新视频必须显式提供 | `--checkpoint` |

从仓库根目录运行，遵守[机器策略](../MACHINE_zh-CN.md)和[协作](COORDINATION.md)，选择已认领的新输出目录。新推理或未缓存掩码需要 GPU；同时复用密集预测和完整语义掩码时仅需 CPU。

```bash
bash tools/setup.sh --level static --plan
bash tools/setup.sh --level static
export PI3X_PY="$PWD/.runtime/pi3x-inference/venv/bin/python"
export PI3X_MESH_PY="$PWD/.runtime/pi3x-mesh/venv/bin/python"
export PI3X_UPSTREAM="$PWD/external/Pi3"
```


```bash
.runtime/sam3-segmentation/venv/bin/python \
  tools/object_pilot/segmentation/prepare_runtime.py \
  --runtime .runtime/sam3-segmentation
export PI3X_CHECKPOINT="$PWD/.runtime/pi3x/checkpoint/model.safetensors"
```


<a id="build-the-reference"></a>

## 构建参考

对连续源镜头，用下方 GPU 命令执行推理、所有选定帧的 SAM3、共享地板/墙体对齐假设、TSDF/上下文网格和源相机叠加。掩码审查、拟合诊断和显式回退见[结构对齐](STRUCTURAL_ALIGNMENT.md)。输出为 `pi3x/`、`masks/`、`alignment/`、`mesh/`、`source_views/` 和 `reference_build.json`，最终状态仍需视觉审查。正交/参考房间比较是独立的 [Blender 检查阶段](LAYOUT_INSPECTION.md)。

默认 32 帧或采用 64 帧档位，覆盖同一镜头两端。更短视频使用每个原生帧。低级重建辅助工具的 `--frame-indices` 必须唯一递增、符合档位并包含两端。不能用三个展示相机作为网格输入。

完整既有包与全帧掩码可用下方 CPU 命令重建。`--num-frames` 要匹配缓存档位。显式 `--cameras` 保留既定刚性世界基；未提供时默认提出新地板/墙基，需掩码含地板和墙。`--alignment preserve` 保留旧缓存的 `cameras.json`。使用 `reference_build.json` 中记录的最终相机路径，不混用旧采样与新基。未提供 `--semantic-cache` 会运行 SAM3，需要 GPU。校验缓存哈希、栅格、原生帧覆盖和相机基。空检测是已处理掩码；缺失/部分掩码不能当安全背景。

低级 `prepare` 接受旧完整缓存，包括 24 帧推理；重建它不等于新 32 帧推理。语义准备和网格都要使用全部缓存帧，省略 `--frames`。已有输出不重写。

```bash
"$PI3X_PY" -m tools.layout_inspection.build_reference \
  --video /absolute/reference.mp4 \
  --upstream "$PI3X_UPSTREAM" --checkpoint "$PI3X_CHECKPOINT" \
  --mesh-python "$PI3X_MESH_PY" \
  --num-frames 32 --reference-views 5 --out /absolute/new-reference
```


```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.build_reference \
  --bundle /absolute/pi3x --cameras /absolute/pi3x/cameras_reviewed.json \
  --semantic-cache /absolute/full-frame-masks \
  --mesh-python "$PI3X_MESH_PY" --num-frames 32 \
  --reference-views 5 --out /absolute/new-reference
```


<a id="geometry-and-background-contract"></a>

## 几何与背景契约

| 层或操作 | 默认策略 |
| --- | --- |
| TSDF 核心 | 0.03 个预测米体素，截断为 4 体素；静态语义、深度边缘合格且有限 sigmoid 置信度严格大于 0.1；积分前拒绝深度置零 |
| 保留背景 | 所有有限、相机深度为正的非人物观测，不设置信度下限 |
| 可见上下文三角形 | 与融合相同的严格阈值；当核心射线无支撑、深度不一致或材质/语义不确定时使用原生源邻接；附深度/形状防护和 1 像素重叠 |
| 无支撑上下文 | 无法构建三角形时仅展示置信度合格的源点；原始观测仍归档 |
| 测量表面 | 保留的静态源三角形，置信度至少 0.5、最大边长 0.15 个预测米 |
| 人、玻璃、镜面、未知 | 单独标签；人物排除于静态核心/背景，不确定材质保留为近似上下文 |

`--human-mask-radius` 默认 **3 个处理图像像素**。每帧人物掩码在积分前用欧氏圆盘独立膨胀，不做时间膨胀。0 为原掩码，5 可对比更宽边界。排除作用于融合、可见上下文三角形、回退点和测量支撑；源三角形不能使用新增防护带。保留原人物标签和原始背景，边界不记为新语义检测。`layers.npz` 的 `human_exclusion` 记录有效掩码，清单记录半径和逐帧原始/扩展数量。叠加在扩展掩码区域保留源 RGB，并导出两种掩码。应用改动须在新目录重建。

`--fusion-confidence` 同时控制融合与可见上下文；`--voxel-size` 改变核心；`--confidence`、`--max-edge` 控制源测量支撑。降低融合阈值不降低测量条件。TSDF 对合格观测使用均匀权重，不是校准置信度权重；使用相机 Z 深度、`depth_scale=1`，不设固定 3 m 传感器裁剪。

噪声参考先在 Blender 检查配置中设 `reference_layers: ["static"]` 只看核心。默认上下文保留与核心不一致的源观测，因此即使融合干净，重叠表面仍可能有噪声。先将 `--human-mask-radius 3 --fusion-confidence 0.3 --voxel-size 0.03` 与既有 0.1 阈值比较，再独立改变半径为 5 或体素为 0.05。这些是诊断设置，不是已验证的质量提升；更大边界/阈值减少覆盖，粗体素损失细节。截断始终 4 体素。持续双重表面需要深度/姿态一致性审查，而非更强平滑。

固定上游 [Pi3X 示例](https://github.com/yyfz/Pi3/blob/9fa3ddb3f8d53041f8b2738df404f62223bbaa7b/example_mm.py#L114)采用 `sigmoid(raw_conf) > 0.1` 后做深度边缘掩码。`predictions.npz` 保存原 logits，`layers.npz` 保存 sigmoid 分数；raw-logit 0.1 对应 sigmoid 约 0.525。非有限置信度不合格。拒绝上下文不能从 1 像素膨胀或回退点返回。清单记录置信度空间、严格比较和逐帧接受/拒绝量；旧参考在新目录重建以应用过滤。

schema-2 `mesh/layers.npz` 含原始源数组及 `measurement_valid`、`fusion_eligible`、`context_eligible`、`finite_depth`、`background_valid`、`human_exclusion`，内嵌 `display_*` 顶点/颜色/面/角色、源索引和回退点索引。哈希绑定测量和显示几何。融合源索引 -1 表示无准确源像素；像素索引是来源记录，不是物理特征轨迹。`background_all_finite.ply` 导出完整背景 RGB、置信度、原生帧/像素身份和语义。

Blender 默认显示核心与过滤后的非人物上下文，分别建立玻璃/镜面/未知/上下文点集合。`reference_layers: ["static"]` 只看核心。显示裁剪和记录的点子采样不从 NPZ/完整 PLY 删除观测。`retain_view_geometry: false` 渲染全部输入视图，但保存副本只保留最后视图几何和全部检查相机。schema-1 保留旧显示默认值。

源关联尺寸使用[网格测量接口](../.agents/skills/pi3x-scene-reference/references/mesh-measurements.md)，选择原静态源三角形和严格测量条件；TSDF/上下文显示网格不提供测量支撑。可见表面范围不能证明完整或隐藏家具边界。

<a id="source-camera-overlays"></a>

## 源相机叠加视图

`--reference-views 5` 在均匀源时间附近选择不同缓存观测并含两端，可请求 3 或 4。检查是否揭示有用墙、开口和家具。手动选择或已有网格用下方 CPU 命令。

可选 `--source-frames` 接受 3–5 个按序原生缓存 ID，跨早/中/晚。少于 3 个时自动选择器记录不足，不虚构或插值相机。

每个视图包含准确处理后的源 RGB、投影源色几何和叠加：**青色为 TSDF 核心，琥珀色为保留上下文**。默认透明度 32%，强调轮廓和深度跃变，不画所有三角边。无命中和源人物掩码区域保留 RGB。遗漏人物区域仍可能含几何，需审查掩码。不投影未三角化回退点；RGB 不变不表示已知空空间。

`source_overlays.jpg` 为拼图。`reference_views.json` 记录参考/输入/输出哈希、原生 ID、时间戳、内参、姿态和图例。逐视图投影 NPZ 保留相机 Z 深度、几何角色、叠加可见性、轮廓及人物掩码。相机、栅格、世界基和尺度共享，不逐视图单独拟合。

完成房间后，还要通过 Blender 检查交付 3–5 个原生相机 **模型边缘比较**并列源 RGB，注明初始 Pi3X 几何还是制作模型边缘。正交视图展示整体布局，源视图揭示可见对齐、遮挡和尺度不一致。

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.reference_views \
  --reference /absolute/reference/mesh/layers.npz \
  --cameras /absolute/pi3x/cameras.json --inputs /absolute/pi3x/inputs.npz \
  --view-count 5 --out /absolute/new-source-views
```


<a id="classical-reconstruction-comparisons"></a>

## 经典重建方法对比

TSDF 是有符号距离表示，体素网格描述空间存储；TSDF 通常用 Marching Cubes 生成三角网格，二者不是互斥输出格式。[研究导出器](../tools/layout_inspection/geometry_study.py)在固定缓存预测/相机上对比原生网格、宽松/自适应网格、0.03/0.06 m TSDF、占用体素边界、滚动球和 Poisson，命令见下方。

网格保留原生邻接但跨帧可重叠；TSDF 合并重复观测但姿态/深度不一致可模糊或删除表面；体素边界块状，滚动球依赖法线和采样，Poisson 可能封闭未观测区域。混合默认保留紧凑核心和近似上下文。`--mesh-method grid` 在生产 builder/prepare 中仍可用于显式旧方法对比。

[Curless–Levoy 论文](https://graphics.stanford.edu/papers/volrange/)说明体积融合，[Open3D](https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html)说明姿态/深度约定；点方法见[滚动球论文](https://research.ibm.com/publications/the-ball-pivoting-algorithm-for-surface-reconstruction)和[Screened Poisson](https://www.cs.jhu.edu/~misha/Fall13b/Papers/Kazhdan13.pdf)。

历史试验使用 32 帧客厅缓存和旧餐厅 24 帧全部观测，生成场景产物不随本包提供。与同一 Pi3X 预测比较的覆盖/深度一致性衡量一致性而非独立准确性。置信度不是校准误差条。深度仍是未校准预测米，除非物理线索建立统一修正，并一致作用于几何与相机。

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.geometry_study \
  --bundle /absolute/pi3x --cameras /absolute/pi3x/cameras.json \
  --semantic-cache /absolute/full-frame-masks --out /absolute/new-study
```
