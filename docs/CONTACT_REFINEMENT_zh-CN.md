<a id="reusable-source-motion-contact-refinement"></a>

# 可复用的源运动接触优化

[English](CONTACT_REFINEMENT.md)

本文说明接触优化和原生摆放接口，并归档已退出当前路线的历史腿部求解器。

<a id="full-reconstruction-includes-contact-repair"></a>

## 完整重建包含接触修复

完整请求按 2026-09-20 [完成契约](MOTION_CONTROLS_zh-CN.md#full-pipeline-completion-contract)，在场景锚定后进行有限物体和脚地接触优化/验证。下方旧默认是软件行为，不允许完整任务在摆放停止。提供明确优化模式和源关联约束，场景接触求解包含 GVHMR 脚接触。无家具交互不虚构目标，但仍检查地板/接触/碰撞。

保留有源证据的手、座、预测脚接触优化。2026-09-22 允许整体人体平移改善接触/穿透，不允许因碰撞改关节或腿修复/IK。保留身体尺度和局部姿态，检查连续性、滑动、源对齐。源支持上身接触拟合为独立、受运动策略约束的方法。

solve_scene_coefficients 默认 collision_correction=False 是软件默认，不禁止改善穿透的平移。接触/深度目标已移动全身；改变显式碰撞目标需实现验证并固定关节，本文不启用标志。接触块间隙/速度仍运行。记录时间损失权重、加权贡献、增加的速度/加速度、实际接触转换播放。冲突残差须明确。refine_leg_contacts.py 现退出不出结果，旧输出不是当前交付。

<a id="legacy-native-motion-placement-interface"></a>

## 旧原生运动摆放接口

2026-09-12 接受：以尺度 1 的一个固定刚性房间对齐保留 GVHMR 原生全局运动/尺寸。现接口默认此模式，无支撑脚检测、自动高度、逐帧根/地板校正、平滑或 IK。原生参数重蒙皮校验缓存再现原运动，仍做源摆放/布局检查。

某人物腿低于地板，先将该人物 vertical_translation_m 设置为经审查的米标量（房间 Z，正向上），默认逐人 0，不放批 config。下方字段示例不是完整清单或推断偏移，要保留各人 motion/alignment/cache 和源证据。首人每帧上移 12 cm，第二人不额外移；顶点/关节一起，姿态、根 XY、时间、拓扑和帧间运动保留。源参数不变，输出记录合并固定平移；零偏移选缓存逐字节复制。

用 GVHMR 环境和认领新路径运行下方包装器。无多人组证据时先拟合固定单位刚性摆放，再验证原生保留并渲染。contact/ 命名为兼容，不说明修复执行。逐人报告/Blender 元数据记方法/偏移。native 验收只关于运动保留；contact_validated=false 表示物理接触未验证。源摆放独立门控。看完整源/房间片段剩余穿透/浮空，均不自动启用 IK。本更新未验证任何特定场景/偏移。

```json
[
  {"id": "person_001", "vertical_translation_m": 0.12},
  {"id": "person_002", "vertical_translation_m": 0.0}
]
```


```bash
bash tools/gvhmr/run_contact.sh --manifest /absolute/path/manifest.json \
  --models /absolute/path/body_models --output /absolute/path/new-native-run
```


<a id="historical-leg-solver-not-the-current-reconstruction-route"></a>

## 历史腿部求解器（非当前重建路线）

后文归档旧求解器。当前接触优化请求**不授权腿 IK**。仅历史复现可给包装器/直接 CLI 加 --refine-contact；所有人物共享一个求解配置。不能把自动支撑高度与非零 vertical_translation_m 混用。

<a id="scope-and-decisions"></a>

## 范围与决策

调用者提供审查过的水平 Z-up 地面并标 grounded_motion。楼梯、跳跃、高支撑坐姿和未知地板需不同模型，可见性排除显式声明。

0. 保留原生尺寸/名义米单位，尺度固定 1，只常量 yaw/摆放与房间/地面/源投影对齐。不允许个人或共享尺度拟合，证据改变、拟合尺度或刚性失败拒绝。接触前和选定修复缓存上都验证真实观测摆放；仅模型 incam 投影不能通过。
1. 从 native-global SMPL-X、时间重采样和记录的固定相似变换再现对齐缓存，拒绝不匹配。
2. 低速落地样本估计稳健固定竖移；小于 3 cm 不动，大于 50 cm 要审查。
3. 检测持续低/慢脚段，排除不可靠观测；脚顶点由 SMPL-X 踝/趾蒙皮权重定义。
4. 仍穿透/滑动时，历史方法全片优化髋/膝/踝/趾，限制关节、宽膝弯曲、偏好原姿态并时间平滑；精确脚蒙皮优化后重新全身蒙皮。
5. 同一前后样本验证穿透、静止脚速/加速度，根 XY 不变。

根朝向/上身旋转不变，根 Z 只有固定对齐；不用相机根替代/逐帧视线地板修正。有效掩码门控 IK 数据/地板损失，时间正则跨排除区间但不恢复它。

残余穿透容许到 5 mm；接触速度 P90 最多增加 2.5 cm/s，加速度 P90 最多 25% 加 0.5 m/s²。这是工程门，不是 benchmark 准确性。候选失败保留原选缓存，写批摘要后退出 2；数值/输入失败立即非零；no-op 人物逐字节保留 NPZ。单接触验收不验证尺度/源摆放。已拒 ref42 用 1.069/0.767/0.700 人物尺度，触地暴露尺寸错误，输出已撤回。组尺度门先于接触编辑。

<a id="invocation"></a>

## 调用

在已部署 GVHMR 环境使用新认领输出，遵循[机器](../MACHINE_zh-CN.md)及[示例清单](../configs/examples/contact_refinement.json)。直接 CLI 命令保留于下方。

清单路径相对文件解析。每人需 id、motion、alignment、cache、grounded_motion；可选 exclude_seconds 是含两端时间戳区间。共享缓存有 vertices/joints/faces/vertex_ids/time_seconds/fps。初始适配器支持中性 SMPL-X、12 PCA 手分量和原生 GVHMR 全局参数，不是通用网格变形。原生端点保持限 1 个 30 fps 间隔，上轴倾斜大于 15° 失败。

```bash
"$GVHMR_PYTHON" tools/gvhmr/contact_refine.py \
  --manifest /absolute/path/manifest.json \
  --models /absolute/path/body_models \
  --output /absolute/path/new-contact-run --device cuda --refine-contact
```

<a id="outputs-and-automation"></a>

## 输出与自动化

每人输出 candidate.npz、选定 body_room.npz、refined_parameters.npz、report.json；批输出 summary.json、manifest.json 和实现/模型来源。参数保留原数组并加 refined_body_pose 和新固定房间变换。候选不一定选定，消费前看 accepted/selected。

只把接受的选缓存交共享 Blender 导入。保留制作房间和源相机，保存独立场景，重开查全轴人物网格；渲染源/前/后比较，全视频解码和代表帧检查。不能移相机/改房间掩盖失配。

<a id="one-command-refinement-and-rendering"></a>

### 一条命令完成优化和渲染

--refine-contact 下，包装器对缺组报告的多人清单自动插入固定单位刚性对齐，再同一本地进程接触/渲染，输出 alignment/、contact/、contact/preview/。已有分组直接新 contact 目录。

render 节提供 scene（仅房间）、camera_cache、source_video；可选 output_blend 指独立场景，否则 preview/scene.blend。显式 visible_until_seconds 控制可见性，可靠性排除不自动隐藏。`--render-only` 渲染已接受批。拒绝已有预览/场景路径防覆盖。preview/ 含源比较、全视频、全帧 Blender 验证、解码报告和审查图。初始渲染器需源时刻 0 开始的均匀全片时间轴。

```bash
bash tools/gvhmr/run_contact.sh --manifest /absolute/path/manifest.json \
  --models /absolute/path/body_models --output /absolute/path/new-run --refine-contact
```

<a id="group-alignment-evidence"></a>

## 组对齐证据

多人对齐清单必须有 group_alignment.report 指向刚性报告，绑定原生单位锁定、有序身份、alignment/cache 哈希、相机哈希、投影/高度诊断。禁止个人/共享尺度拟合。GVHMR 相机投影诊断目标是近似预测非标注真值；无外部米制证据房间尺度仍暂定。即使数值通过，选结果前仍审查源比较。

<a id="native-unit-correction-after-audit"></a>

## 审计后的原生单位修正

Pi3X 已给点/相机平移施加预测米因子，地板变换刚性。旧逐人相似优化不是经验证单位转换，不能拟合人体大小补投影。替代仅优化固定 yaw/XY，由支撑推导固定 Z，scale=1。未来米制再标定需独立证据和独立显式单位变换，不属优化器。

旧共享尺度提案/输出未采纳。报告需 scale_policy=native_units_locked、scale_optimized=false；旧共享尺度报告即使所有尺度相等也拒绝。

<a id="standardized-source-placement-acceptance"></a>

## 标准化源摆放验收

全部人物/场景共用 placement_diagnostics.py，读取源 COCO17 XY/置信、原生时间、真实相机栅格/标定、对齐 SMPL-X 关节。仅解剖匹配髋/膝/踝/肩/肘/腕参与，推断脊柱/头不是观测；检测器/人体关节定义仍可不同。先用下方 placement-only CPU 诊断再花 GPU 时间。

清单逐人提供 pose_confidence，或发现 native motion 旁 preprocess/vitpose.pt。阈值为上游分数 0.5，不是校准概率。配置作用整个批，不单人物 ID。报告曝光时间覆盖/窗口误差，良好全片中位不覆盖坏窗口；缺/不足为未验证非零误差。排除区间保留覆盖限制。

常 XY 与分窗拟合探针判断刚性/时间失配，不改运动、不提供逐帧修正。可见范围无法分清深度/形态/关节语义；时间失配需单独验证轨迹/相机调查，此阶段没实现通用根优化。

contact_refine.py 加载模型前和接触接受后检查，写 placement_before/report.json、placement_after/report.json。直接 contact_render.py（组装/验证/--render-only）需接受的后接触证据，绑定完整清单、相机、缓存、native、对齐、观测、诊断实现。变排除/可见性/选缓存使失效；不能跳包装器晋升旧接触-only。诊断 CLI 的 --refinement 可查旧候选，但不授交付验收。

非零保留证据并停止。通过仅是观测投影工程检查，不证明身份、尺度、接触真值、可见/遮挡或完整保真，仍保留视觉比较。求解器限审查水平落地运动，楼梯/坐/跳/未知支撑报告不支持，不套平地法。lounge 是回归不是人物常量来源；源工作区证据/交接不随包，未建立第二真实场景接受验证。

```bash
bash tools/gvhmr/run_contact.sh --placement-only \
  --manifest /absolute/path/aligned-manifest.json \
  --output /absolute/path/new-placement-report
```

<a id="portable-runtime-setup"></a>

## 可移植运行时设置

按 [GVHMR 安装](install/gvhmr.md)准备独立环境/许可人体。包装器前设 GVHMR_PYTHON（或本阶段 CONTACT_PYTHON）、BLENDER_BIN，可选 FFMPEG_BIN。Python 默认 GVHMR_ROOT/venv/bin/python，根与指南一致；Blender/FFmpeg 支持 PATH。已有核心不修改、不当隐式 GVHMR。阶段在本地 GPU（--device cuda）。

可移植副本含 CPU 几何测试/CLI 检查；未在此副本重新安装预训练环境、GPU 优化或 Blender 交付，源工作区验证是独立证据。
