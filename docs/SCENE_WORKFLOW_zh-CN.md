<a id="staged-reference-to-scene-workflow"></a>

# 分阶段的参考到场景工作流

[English](SCENE_WORKFLOW.md)

当前路由（2026-09-11 接受）：源人物默认 [GVHMR](../.agents/skills/gvhmr-body-reconstruction/SKILL.md)、同镜头房间对齐、导入制作 Blender 场景；房间仍 Pi3X 参考和现 Blender/资产工作流。本文记录的源路线在新 GVHMR 前用 SAMURAI，确认退出结束/隐藏轨迹。保留人体尺寸/局部运动；同镜头深度用于有证据轨迹尺度/平移和光滑漂移修正，另做固定 room Z 摆放。请求接触用审查源事件/有限制作支撑，见[可执行指南](HUMAN_TRACKING_AND_TRAJECTORY.md)。Kimodo 用新/改动作或记录回退，SAM 对生成路线可选。下方历史生成例不覆盖默认。

状态：2026-09-09 按用户改善钢琴流程并建立重复入口实现。调用 [$indoor-scene-workflow](../.agents/skills/indoor-scene-workflow/SKILL.md)。

<a id="plan-once-consume-results-at-the-appropriate-stage"></a>

## 一次规划，在对应阶段消费结果

新场景前用[统一需求入口](SCENE_REQUESTS.md)：intake 独立记录外观、交付/相机、人物/柜/物运动、时间和最终替换。预填已知，只问缺项。保存 request/brief 和依赖组指导制作，不提交计算、不替配方。窄修改复用范围，请求资产变体在完整集成前仍为明确延后 phase-3 义务。

从[协作](COORDINATION.md)、STATE.md 和源开始。简短分镜记源/时间、镜头边界、人物 ID、近似动作区间、重要触碰/转身、可见布局、未知和输出。是智能体推理记录非新模型输入。钢琴例（历史/外部，不随包）不是通用动作模板。

源指导 Kimodo 优先 root > hands >= feet > text-only；源根路线/有用 SAM 手脚，文本语义。记录限制并看结果。[运动策略](MOTION_CONTROLS_zh-CN.md)定义范围，实现由智能体/专门工具选。

| 阶段 | 主要输出 | 消费前证据 |
| --- | --- | --- |
| 源分析/Pi3X | 同镜头 RGB/PTS/预测/相机缓存，分镜 | 源帧/切镜审查、准确时间/源身份 |
| 对齐参考 | 源关联尺寸、地板/尺度状态、共同变换 | 可靠静态端点、地面假设、独立跨视角观测 |
| 白房间/请求相机 | 可编辑保存房间、比较静帧、可选全速相机 | CPU 预检、[逐物体布局](#furniture-layout-review-entrypoint)、比例/朝向/通行/遮挡/支撑，先于人体路线与全渲染 |
| 人物 | 审查 SAMURAI 身份/退出、native、固定身体轨迹、接触目标 | 准确源时间/活动、支撑证据、修正平滑/源风格、蒙皮前旋转重采样 |
| 集成 | 烘焙多人 .blend、摆放缓存、逐人检查 | 活跃人物齐全、退出隐藏、真实接触/地板/取景、相机保留 |
| 交付 | 全解码视频/最终场景、可选比较 | 请求帧数/率/时长、重开人体/相机、实际代表渲染 |

源分析即分析人物，让关键时刻进入 Pi3X/SAM 选源。昂贵运动迭代前稳定房间/相机。原生参考适配器需要的文本基线在摆放基已知后可先做，但非默认最终候选。技术/视觉由智能体审查，不需新用户确认。保留静态/动画范围和显式独立重建请求。

<a id="furniture-layout-review-entrypoint"></a>

## 家具布局审查入口

查位置/大小/朝向/间距时默认 **简化彩色轮廓 + 逐物体高亮**，属于 blender-roomkit 非新技能。首个保存粗模和相关修改后使用，尤其用户指出失配；即使整图不密集也有用。材质/正面细节、深度、源地标/测量补充；轮廓有歧义选证据更强比较并记录。

匹配完成共同框检查的保存场景，用下方 export_model、object_outline、agent_review 新目录命令。缺失或旧检查先按[布局检查](LAYOUT_INSPECTION.md)生成匹配证据，复用源预测/审查掩码，不绕哈希。可用时传 --inventory/--source-fit，缺失记未评估非接受。轮廓/高亮不需 SAM3。

读 summary.json 的发现/图路径；无需浏览器即可看 *_context.png 和发现驱动 focus_*.png，墙/其他几何保灰。report.html 可选物体。匹配平面和源 RGB 比较，不能证明朝向/遮挡时保留实际前后/深度证据。

首用/改分组时打开图检查库存：完整家具根需 furniture/... 分类；bare bed/chair 不在默认过滤，执行成功预览仍可空。生成 HTML/JSON 不等于检查有用轮廓。

记录场景版本、图、ID、残余发现。失配须有前后证据才关闭，执行不能关闭。程序优先复用不变视觉审查，不免初覆盖/终保真。流水线默认 export/outlines/agent_review --all-objects；门绑定场景/相机并要求 focus 图准确物体观察，缺/空/错/旧包不能授权接受。见[物体契约](LAYOUT_INSPECTION.md#object-review-default-and-repair-loop)。这是智能体审查非用户审批。

```bash
"$BLENDER_BIN" -b /absolute/model.blend --python-exit-code 1 \
  --python tools/layout_inspection/export_model.py -- \
  --cameras /absolute/cameras.json --out /absolute/new-export
"$PI3X_MESH_PY" -m tools.layout_inspection.object_outline \
  --geometry /absolute/new-export/model.npz --metadata /absolute/new-export/model.json \
  --inspection /absolute/matched-inspection --out /absolute/new-outlines
"$PI3X_MESH_PY" -m tools.layout_inspection.agent_review \
  --outlines /absolute/new-outlines/objects.json --out /absolute/new-agent-review
```


<a id="quality-before-batch-expansion"></a>

## 批量扩展前先保证质量

新批先完成一个代表场景的房间、材质、源相机比较和请求预览审查，再扩展。之后每 worker 一未完成制作场景。空 GPU/队列输入不证明建模容量。并行有限参考准备或已审查冻结场景渲染，不同时生多个房间延后验收。均属现请求智能体审查，非新暂停。

简记决策：

- **源覆盖**：早/中/晚和新露空间，主要墙/开口、家具数量、可见正面/饰面。类别大致或首视图合理不覆盖后走廊。
- **几何基**：共同 Pi3X/相机，合格表面测量及源端点；观测支撑/隐藏推断分开，空/拒绝区域无支撑。原深度中位、玻璃反射、孤像素不证明完整尺寸。
- **资产/材质**：自建前与注册资产比较，记自替理由，重复前看轮廓/结构/材质比例/饰面。纹理重建中彩盒/泛噪仍粗模。艺术/外景照片需正确投影/来源，静照不是镜/玻璃/房间重建。
- **完整物体**：变换带唯一 ID 全零件语义根，用 tag_root 返回或 adopt_group。已摆零件给审查 floor/mount-centered placement_matrix，或几何绕原点归一；默认世界原点枢轴不是家具推断。别继续把 mesh child 当根。支持直立静态有向物声明可信实际前面，用 place_root/place_asset 配源朝向。按[朝向](ASSET_ORIENTATION.md)限制；对称/倾斜/动画需审查摆放，不强塞朝向。看座/靠背不只 yaw。
- **证据**：真实解码帧/PTS 匹配模型时间，缺帧解码或失败，不偷换附近图。纹理绑定真实源帧/时间；builder 输出测量/检查，后续独立视觉记准确源/渲染和问题。生成“已审查”文字不证明实际看过。

源布局、摆放、相机缓存、材质、全片预览分开记 pending/failed/reviewed。缓存相等不证明房间匹配，独立脚本同门。版本场景/脚本身份/证据分路径。制作/验证失败先停，不渲染缺或旧场景；开下一场景前解决显著缺陷。

<a id="layout-inspection-before-people-and-final-rendering"></a>

## 人物与最终渲染前的布局检查

昂贵全布局包前做[早期源关系检查](LAYOUT_INSPECTION.md#early-source-relation-check)，优先用户修正、共享平面、大轮廓、朝向、重复数量；局部诊断修正后再冻结完整审查。

首白房间后用[共同框检查](LAYOUT_INSPECTION.md)，看顶/前/侧叠加和早/中/晚原生源相机。静态参考去 SAM3 人物，玻璃/镜独立开关，几何有效性与缺覆盖分开。人体对齐/全渲染前修明显布局错误，智能体无需新审批。

<a id="reuse-boundaries"></a>

## 复用边界

新场景遵循[语义资产契约](SCENE_VARIANTS_zh-CN.md)：完整可替物稳定根，墙地材质角色，桌面支撑关系。柜体显式可操作布局，门/抽屉/内部/独立控制复用。多样性属于共享生成器/配方，场景脚本只配置位置/时刻。导出保留 native 关节。旧代理需明确迁移，名称不足；不向静态请求加动画。

| 变化 | 可复用 | 重算/审查 |
| --- | --- | --- |
| 图标签/网格/色/切片 | 原 Pi3X/RGB | 展示可读性、尺寸和相机导出同一 |
| 地板基/统一尺度 | 原预测 | 对齐点/相机、尺寸/摆放/相机验证 |
| 仅相机/灯 | 兼容 native/重采样/蒙皮 | 组装、最终评估标定/轨迹、渲染/审查 |
| 一人 prompt/路线/native key | 房间/相机/其他人、同镜头观测 | 该人生成/重采样/蒙皮、集成/受影响检查 |
| SAM 选事件/朝向解释 | 适用原观测 | 选择/native 指导、受影响运动/检查 |
| 源镜头/输出节奏/体型 | 仅匹配输入/时间产物 | 依赖相机/运动/蒙皮/组装 |

普通修正先记变 ID、邻居、输入/阶段。顺序：① 在匹配源裁剪和计划/侧图查变物/支撑，除有相机错误证据保留审查相机，先解决具体问题；② 冻结修复，局部通过后完整当前布局/采样/最终审查，局图不能把旧全场接受给新几何；③ 完好帧恢复失败编码/解码/报告，坏图审查回应用不变图包新审查输出，两者不需重渲；④ 用[恢复/复用](PIPELINE_zh-CN.md#resume-and-reuse)，保快照并让 runner 查依赖，不改标签/收据强复用。

几何可改裁剪外遮挡/阴影/反射/接触，不能假设其余像素有效。材质/灯复用源重建/兼容几何诊断，需新外观/终验。全局基/相机/源/时间使依赖失效。同会话切渲染/CPU/图审查，不为换活动重启 batch。

不为装饰重跑 Pi3X，不在像素循环反复读密集 NPZ；NpzFile[key] 每次解压，跨视角每成员只读一次，见经验基准。别改冻结快照，用新变体/已验证复用。

源色米制视图/全身 SAM 裁剪助识别，切片只改显示不改测量端点。[彩参考/腿比较](lessons/colored-reference-leg-guidance.md)记录收益/限制。稀疏脚指导仍实验，查可见性、匹配基线、留出源时刻、实际蒙皮脚底地板后采纳；关键姿态更好不证明步态更好。

<a id="shared-commands-and-configuration"></a>

## 共享命令与配置

预处理、哈希、测试、Blender、编码本地运行。source env.sh，设 PYTHONDONTWRITEBYTECODE=1，从根 export PYTHONPATH="$PWD/src"。Pi3X Python 有 OpenCV/NumPy/SciPy/Pillow；Kimodo 跑共享流水线，Blender 执行 bpy。下方输出均为 runs/<scene>/<run>/ 的独立认领路径。变量替换为任务实际输入，不作全局设置。

<a id="camera-and-independent-static-cross-view-checks"></a>

### 相机与独立静态跨视角检查

Pi3X/审查对齐后用下方 camera/crossview。相机配置（历史/外部，不随包）需有理时间、[width,height]、continuous_shot_reviewed: true 和端点策略。source_start_seconds 可偏采样钟；error 拒观测外，显式 hold 记数量。平移 PCHIP、旋转 SLERP、内参线性。缩放前整数像素中心转边界中心，保偏心主点。不自动检测切镜或 VFR 重定时，先明确分镜/映射。

组合房间/动作前用计划 ensemble 配置 CPU preflight；人体缓存可未来路径，检查不加载。查完整相机时间/栅格/刚性/斜切，预测固定 pixel aspect 残差，不开 Blender，写 camera.json，超容差退出 2。调查约定/尺度/近似，记录刻意容差，不自动升。组装修改前重预检，仍有全帧 Blender 相机评估；解析成功不证明播放/源准确。

静态区配置用原生源 ID、处理像素排除矩形、帧对、descriptor ratio 和置信阈值；按真实人物、反射、图形/平面图、不可靠区调整。ORB 匹配独立于预测 3D，重复纹理有离群；度量一致性非尺度/绝对姿态。逐对报告数量/误差，尤其弱转/全玻璃，低总中位可藏弱窗。静态地板与 camera-up 回退/更高表面分审。world_transform 保刚性，校准统一尺度从测量接口同时作用点/相机平移，不能塞旋转块；假定相机高不是实测标定。

```bash
"$PI3X_PYTHON" -m aha3d.workflow.camera \
  --bundle "$ALIGNED_BUNDLE" --config "$CAMERA_CONFIG" --out "$CAMERA_OUTPUT"
"$PI3X_PYTHON" -m aha3d.workflow.crossview \
  --bundle "$ALIGNED_BUNDLE" --config "$STATIC_REGION_CONFIG" --out "$CROSSVIEW_OUTPUT"
```


```bash
"$PI3X_PYTHON" -m aha3d.workflow.preflight \
  --root "$PWD" --config "$ENSEMBLE_CONFIG" --out "$CAMERA_PREFLIGHT"
```


<a id="motion-without-a-room-copy"></a>

### 无需房间副本的运动

plan/prepare/run --motion-only 仅 generate/native。配方仍名预期 blend 可不存在，不打开/哈希/复制。快照代码、动作/约束、运行时，在 skin 后停；状态 staged 非 validated，无房间/视频验证。恢复保范围，集成新普通场景 run；submit 可恢复，batch 暂不暴露。

不确定路线/长支撑敏感动作先按下方阶段停止拆生成/蒙皮，前台运行。MOTION_RUN 为 runs/$SCENE_ID/$MOTION_ID；native 直接看文件无生成阶段。诊断原生 Y-up 根行程/位移/高度/步长/段接缝，可选 max-travel/max-root-step/min-root-height/max-height-range 为场景限，违反写证据退出 2。无约束为 diagnostic 非接受；蒙皮前看，解释耗时则停阶段释放 GPU。native FPS 默认匹配配方 source_fps 或 30，可覆盖。

每 prompt 最多 **10 秒**（30 fps 300 帧），验证器拒超长、每句点分隔 prompt 需一个时长；多段总片可超 10。ref33 两个 15.015 秒候选越限，不证明合法 10 秒不足。在合法范围按动作/候选分段；ref33 最终有界段+稀疏支撑，ref32 8.675 秒因接缝扰动改一 prompt 改善，都不证明通用 5 秒规则。蒙皮后看真实网格/源视角关键时刻和连接，根诊断不证明朝向/脚/门遮挡。

按优先审根/手脚，文本周边语义。路径不指定前/后走，查网格朝向/必要 native heading。手脚 keys 也携 root/heading，先协调。不用旧外臂 IK/关键朝向。支撑/碰撞诊断不自动重规划动作，记接受近似。

```bash
bash tools/indoor plan "$SCENE_ID" --recipe "$PERSON_RECIPE" --motion-only
bash tools/indoor run "$SCENE_ID" --recipe "$PERSON_RECIPE" --motion-only
```


```bash
bash tools/indoor prepare "$SCENE_ID" --recipe "$PERSON_RECIPE" --motion-only --run-id "$MOTION_ID"
bash tools/indoor execute "$MOTION_RUN" --until motion
"$KIMODO_ENV/bin/python" -m aha3d.motion.diagnostics \
  --motion "$MOTION_RUN/stages/motion/motion.npz" \
  --recipe "$MOTION_RUN/snapshot/recipe.json" --out "$NATIVE_DIAGNOSTICS"
```


<a id="parameterized-room-and-multi-person-assembly"></a>

### 参数化房间与多人组装

ensemble 配置（历史/外部，不随包）含时间、栅格、可选相机、唯一整数人 ID/标签、缓存、固定 scale/yaw、初骨盆 anchor_xy、可选 z_offset/ground_z、预览 ID/验证。路径相对 --root，ID 1 为 Person_001_Body。未知/重复/时间不兼容拒绝；源未列人物令 room extraction 失败，不悄省。

z_offset 为缩放后世界米固定竖移，记矩阵/组装。省略两竖字段保原。旧原缓存 Z +0.02 m 在 scale .9 等同原缓存 z_offset .018，不叠两移，省大派生缓存并保竖差。ground_z 显式逐帧整体抬最低点到地高；省略保竖运动，仅审平支撑非楼梯/跳/精准脚拟合。儿童均匀 scale 为近似身高非儿科形态。两者互斥；固定偏移可浮/穿，不修步态/证接触。

新房间经房间/相机审查可直接 assemble。room 分离已有场景只删声明人、保几何材质，不推房间，应 RoomKit/测量制作。共享 helper 无特定家具名/尺寸/路线/修正。定人路线前比占地/朝向/通道，歧义用计划/斜视区分布局/动作，保共同基。全渲前看家具支撑，低侧/剖切须可见支撑、灯、取景，黑/遮图不是证据；检查可见性/相机独立输出。

Blender pixel aspect 不能动画；用 median fx/fy、关键 lens/principal shift，与**全部**缓存矩阵比较。默认内参容差 2 px，按实际要求配置，超差保存成功报告前失败；这是表示非 Pi3X 准确性。每预览配置 GPU。pixel aspect 两轴最小 1，ratio<1 用 (1/ratio,1)，避免旧 y 静默夹 1；ref32 的额外误差源，先查实现/约定再认不可避免近似。

重开验证逐人拓扑/稳定顶点 ID/几何/摆放/取景/地板/相交，全帧相机。采样显式，变路径此处默认 all，不证自碰撞/包含/帧间净空/脚滑/精准手。

```bash
"$BLENDER" -b "$SAVED_SOURCE" -t 8 --python-exit-code 1 \
  --python src/aha3d/blender/ensemble.py -- --root "$PWD" \
  --config "$ENSEMBLE_CONFIG" --stage room --out "$ROOM_OUTPUT" --preview
"$BLENDER" -b "$ROOM_OUTPUT/scene.blend" -t 8 --python-exit-code 1 \
  --python src/aha3d/blender/ensemble.py -- --root "$PWD" \
  --config "$ENSEMBLE_CONFIG" --stage assemble --out "$ENSEMBLE_OUTPUT" --preview
"$BLENDER" -b "$ENSEMBLE_OUTPUT/scene.blend" -t 8 --python-exit-code 1 \
  --python src/aha3d/blender/ensemble.py -- --root "$PWD" \
  --config "$ENSEMBLE_CONFIG" --stage verify --assembly "$ENSEMBLE_OUTPUT" \
  --out "$ENSEMBLE_CHECKS"
```


<a id="final-render-and-comparison"></a>

### 最终渲染与比较

预览接受后按[渲染执行](RENDER_EXECUTION.md)批量就绪阶段/等待/最终审查。普通配方 source 指 ensemble scene.blend 保烘焙人体，用[共享流水线](PIPELINE_zh-CN.md)渲染/恢复/全解码。原流水线单人体中心，**最终**保存场景再运行 ensemble verify 覆盖全部，单人轨迹不能标多人。

下方 compare --run 拒活锁，不能猜 clip.mp4/animation.mp4；流水线外视频用 --render VIDEO --config TIMING_CONFIG，互斥。源仍显式；更新目录从 scene.json.reference 导别名并确认存在，各智能体可能不同别名。

FFmpeg 用静态标签图缩放/填充/拼接两流，不逐帧 Python/PIL。tile 默认 640×360 可配置；源/渲染恒率轴匹配、各从首帧开始。严格全解码后短 metadata probe，拼图解码另做。不保证通用 VFR/切镜对齐。比较独立渲染，末尾失败不破渲染证据但比较未完，修输入仅新目录重试该命令；不记录视觉接受/替代全人验证。

实际看白房间、网格、终渲/比较代表帧，观察与自动成功分记，更新状态/交接，用产物链接交付。最终 blend 烘焙人体，播放不需 Kimodo/人体插件。

```bash
bash tools/indoor run "$SCENE_ID" --recipe "$FINAL_RECIPE"
"$PI3X_PYTHON" -m aha3d.workflow.compare \
  --reference "$SOURCE_VIDEO" --run "$FINAL_RUN" --out "$COMPARISON_OUTPUT"
```


<a id="execution-and-repeatability"></a>

## 执行与可重复性

复用 runner 锁、不可变快照、指纹和失败传播，不造 .ready shell 队列。需要建模/视觉判断在有意义检查点停，不长期占空 GPU。小就绪 CPU 可与 GPU 同行；独立 helper 保存配置/代码/源，写新目录，不自带调度器。几何制作/审查是智能体工作。

显式并行批先质量门，每场景一写者、共享目录一 owner；CPU 独立，GPU 同时仅一 indoor batch/submit worker 顺序执行。交接在重要停止记 batch ID、阶段、接受/拒变体和下一步。shell/认领完成才依赖写；worker 消失按恢复，聊天更新非持久完成。

<a id="submission-preflight-and-full-clip-preview-acceptance"></a>

## 提交预检与全片预览验收

新视频运行组装/保存验证后、终渲前停 preview_required，属已授权技术检查非用户审批；execute 恢复复用已完组装/验证。旧无 preview_policy 保旧行为/交付。motion-only/静图无需全片门。

花 GPU 前统一只读 preflight；plan/run/batch/prepare 共用。recipe 是标识符不是 JSON 路径。下方可选 SAM selection/cameras 要一起传。检查 schema、分段/10秒、每段 int(duration*30)、末约束边界、根/heading 冲突、依赖、SAM 栅格/端点舍入。Kimodo global_root_heading=(cos,sin)，原生 +Z 为 [1,0]；SAM facing_xz 是 XZ，+Z 为 [0,1]。单位检查不能证明意图，查网格。界限不识别错人/错坐标比例/左右/可见，审准确处理帧全身叠加。预检不加载模型/开 Blender/查链接纹理/证保真；保存检查独立。

到 preview_required 后按下方 preview/accept-preview，再 submit（或前台 execute）。默认全源时长 **5 FPS**含两端，粗查用 1，快动作/接触提率，每帧需显式 source。最终保时不要求预览每源帧：899 帧约 15 秒在 5 FPS 约 75。终渲/全解码仍全部交付帧。

sampling.json 记准确场景索引/原时间，编码图连续编号。接近请求的有理播放率保精确时长含小数 FPS；场景/终配方/相机不变。短片保两可用端，不超源；原分辨率早/中/晚静帧保留。旧无采样快照需新 run 或显式 source，不改快照/静默全速回退。

默认 GPU，可用时复用任务 GPU；helper 配光栅或显式 Cycles GPU，CPU 明确无头 Cycles。低预览 4 samples，保 pixel aspect，整数栅格除数确保比例/偶数尺寸；特殊栅格可超 max-width。全解码**采样预览**查自身数量/率/时长，不证未采源。复用生成/蒙皮/组装。旧 run --preview 是质量标志非接受。

每次新 RUN/previews/<id>/：采样全时长 MP4、原配方分辨率早/中/晚（8–16 samples）、所有 person_id 的全帧网格/接触报告。数值区分三角重叠/视觉；collisions:error 相交失败，off/report 仅诊断，不证缓存对应/连续无碰撞/自碰撞/身份。保意图支撑并解释，未打标人不可自动发现。

实际看全采样预览、原分辨率源对照和全部人物摆放/接触。全帧数值与渲染采样独立。拼缩略图助覆盖但不够比例判断。下方 JSON 为技术审查例（路径绝对），示例帧列表缩写，审后复制**完整准确** sampling.json.scene_frames。采样接受需 preview_reviewed、准确 reviewed_scene_frames、sampling_limitations，仅旧 whole_clip_reviewed:true 不够；原率仍用旧字段。

预览自己提原分辨率无损 source_keyframes/ PNG，记视频/图哈希、0-based 解码索引，审这些准确图。默认映射仅源/输出帧数/FPS/时长相同；裁/重定时显式 --source-frames INDEX_FIRST INDEX_MIDDLE INDEX_LAST，对应 render_report keyframes，审对齐。外 source_image 须哈希匹配提取 PNG，无关全尺寸图不能过。

用真实 render_report 帧，列全部 ID（无人空）。默认 people_report.json；可指定同场景 SHA256/人 ID/完整采样的更强 ensemble 报告，单体不能替多人。无 scene.json.reference 的文本场景用 no_reference_rationale/render_keyframes 替 source_video/source_comparisons，结构同帧/说明无源图。源要求由冻结来源而非看房间像真。

接受哈希源、全部冻结配方/运行时/代码/输入、预览/审查；改视频/源/相机时间/网格报告/证据使失效，重生成/审受影响后继续，证据持久。是实际智能体记录非自动视觉分/人审批；改动新不可变 run。

实际 generation/assembly/final render 和 GPU preview 前查 GPU 可见，CUDA_VISIBLE_DEVICES 隐全部失败；复用已完 GPU 无需 GPU，CPU verify/resample/video/preview 可用。Blender 另查 OptiX。当前 assembly 配 GPU，执行仍需 GPU。

在 additional44/45/47、真实小数 FPS full47 和无头 CPU fixture 验证（报告私有，不分发）。真实测试先拒难辨单采样预览，再采此可读默认。已有终视频未重渲。

```bash
bash tools/indoor preflight desert_view_lounge_g0061 --recipe actor2_final --motion-only \
  --sam-selection scenes/desert_view_lounge_g0061/workflow/sam_2_reviewed.json \
  --sam-cameras runs/desert_view_lounge_g0061/reconstruction-20260911/pi3x/cameras.json
```


```bash
bash tools/indoor preview runs/SCENE/RUN --backend gpu --max-width 320 --preview-fps 5
bash tools/indoor accept-preview runs/SCENE/RUN --evidence /absolute/path/review.json
```


```bash
bash tools/indoor submit runs/SCENE/RUN
```


```json
{
  "reviewer": "scene-agent",
  "preview_reviewed": true,
  "reviewed_scene_frames": [1, 13, 25],
  "sampling_limitations": "Describe between-sample risks and any higher-rate follow-up.",
  "note": "Describe observed camera, action timing, framing and remaining approximations.",
  "source_video": "/absolute/path/to/registered/source.mp4",
  "source_comparisons": [
    {"frame": 1, "note": "Opening source/render proportions reviewed at original resolution."},
    {"frame": 450, "note": "Midpoint sofa, actor and circulation reviewed."},
    {"frame": 900, "note": "Endpoint window/table projected extents reviewed."}
  ],
  "people": [
    {"id": 1, "placement_contact_note": "Describe floor/support/contact observations and any accepted approximation."}
  ],
  "people_report_limitations": "Describe all-frame integer sampling and any intended or unresolved overlaps."
}
```
