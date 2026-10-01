<a id="real2sim-indoor-pipeline-room-cameras-and-source-people"></a>

# 室内 Real2Sim 流水线：房间、相机与源人物

[English](REAL2SIM_PIPELINE.md)

更新于 2026-09-20。这里说明端到端路由/限制，不声称每阶段是一个全自动命令。智能体审源身份/几何/视觉，模型估参考/运动，Blender 生成可编辑场景。见[入口](PIPELINE_zh-CN.md)、[场景工作流](SCENE_WORKFLOW_zh-CN.md)、[世界实验](WORLD_POSTOPT.md)。

源人物前端 **SAM3 → 既有 bbox 后处理 → PMPose-h → GVHMR**，结合同镜头 Pi3X 相机。新完整世界运行在 GVHMR 内复用接受的场景地板/直立，**默认 v2** 对比场景引导 GVHMR。根据作者视觉反馈，Kimodo 空缺补全**默认跳过**，仅显式实验。native rigid 路线独立保留。候选验证不自动选择制作房间交付。

下方流程图保留原工具/阶段名称：源范围审查，Pi3X 参考/房间与 SAM3/PMPose 人物两支汇合，在场景地面提升、共享位置锚定、v2、有限物体/脚地接触验证后，重采样/蒙皮/保存审查/全解码，再版本化选择与 Gallery/请求演示。

```text
Source video + requested scope → shot, timing and actor review
  ├─ Pi3X geometry/cameras → reviewed floor, upright and scale → editable room/assets
  │                              │
  └─ SAM3 → bbox support/interpolation/smoothing → PMPose COCO-17 + image features
                                 │
                         GVHMR using scene floor/upright
                                 │
                dense whole-clip cameras → common scene-ground lifting
                                 │
                     shared-scene position anchoring → v2 with fixed floor/upright
                                 │
              finite-object + foot-ground contact refinement and validation
                                 │
Accepted motion + authored room + requested camera/object animation
  → rotation resampling → skinning/baking → saved-scene review → full decode
  → versioned delivery selection → Gallery / requested browser demo
```


<a id="completion-requirement"></a>

## 完成要求

完整默认包括全部请求阶段：可靠共享场景位置锚定、人-物和脚-地修正、最终验证/集成展示。复用房间不免这些人场阶段。中间结果是调试产物，锚/接触失败需修复继续，不缩交付。见[完成契约](MOTION_CONTROLS_zh-CN.md#full-pipeline-completion-contract)。

保留密集 Pi3X 深度/置信和匹配内参/相机及显式源帧映射；仅全率相机不能提供全率深度锚。接触前查裁剪到原像素变换和共享相机投影，v2 逐人拟合相机不是房间相机门。

<a id="1-establish-source-timing-and-scope"></a>

## 1. 确定源、时间与范围

记录准确源、镜头边界、时间戳、时长、人物身份、重要交互、房间覆盖/输出，保视频署名/许可证。相机运动、人物、家具关节、可动物分开；源视频不自动请求输出相机动画。窄改复用既决策。

新请求 intake，在 scene/run 工作，写/启动前认领代码/场景/输出，跨场景验证 runs/_tools。模型/机器路径保既有外部/本地配置。新场景下游前初始化/绑定验收范围，台账保用户发现，见[验收](WORKFLOW_ACCEPTANCE.md)。检测器更新等代码/文档实验不是重建验收。

完整 world harness 当前需 **1280×720、30 Hz** 归一视频，此接口拒别栅格，跟踪固定尺寸；归一时保源帧/时间映射。不在最后可见人物截场景，不接无关镜头。

<a id="2-estimate-same-shot-scene-references-and-cameras-with-pi3x"></a>

## 2. 使用 Pi3X 估计同镜头参考与相机

Pi3X 从适合观测估参考、相机/源视图；可靠静态证据建立一个审查世界基、地板方向、米尺度假设。记录单目不保证真实尺寸的未知。

源色鸟瞰/侧视和测量审墙长/开口/家具范围/关系；点云/网格是参考非成品。动态人、反射、玻璃、隐藏边界、无支撑深度非可靠静态测量。

后优化对照做**新全片密集 Pi3X forward**，相机位置对齐同镜头基，不是稀疏相机插值。外 harness 用 255000 像素预算，尺寸到 14 倍数。记约定/变换。平面/近静相机位置不足确定稳 3D 旋转，查朝向/静态投影。不重中心 frame0 抵消全局旋转，恢复相机仍估计。

<a id="3-author-the-editable-room-and-furniture"></a>

## 3. 制作可编辑房间与家具

自建前搜 assets/INDEX.md 或 asset_index.py，形状/尺寸/朝向/材质匹配则用注册资产。缺几何作可编辑完整语义根，变完整物非独立子。保前向、支撑面、纹理依赖、稳定 ID。

共同基建墙地/开口/主要家具，早中晚覆盖后来空间，比轮廓/朝向/尺寸/通行/遮挡；实际渲染查材质比例/饰面，合理粗模非完成纹理房间。终运动摆放前确定接触敏感家具。每主物含墙在隔离 X-ray focus 配源/计划/侧图审查，可见错保持开放直到修正源证关闭。

后台开保存源，保存独立输出，保源材质；clay 可输出覆盖。请求资产替换遵循稳定 ID 契约。

<a id="4-track-each-source-actor-with-sam3"></a>

## 4. 用 SAM3 跟踪每个源人物

完整图默认 --tracker sam3。审锚图/人物 bbox 后传播实例掩码。显式 --tracker samurai 和路径用于匹配对照。SAM3 以 --sam3/--sam3-python/--sam3-checkpoint 或 SAM3_ROOT/SAM3_PYTHON/SAM3_CHECKPOINT 配置，在独立解释器本地 GPU，PMPose 独立，余 30 Hz 图/场景地面范围不变。

保下方 bbox 后处理，SAM3 只替 tracker。PMPose 得平滑 XYXY 和原掩码；GVHMR 得 1.2x center/scale 裁剪。不虚造全身替局掩码。clip32 260 帧完成，重遮挡 7.8 秒观测跟到前景干扰人；裁剪平滑不证身份/姿态，采用前审区间。每传播方向新 predictor，锚晚于 0 需正向和反向前缀。逐人独存 raw masks/boxes、mask area、帧 ID 和来源。

交叉/遮挡/再现审身份；非空掩码/高置信骨架可错人。旧 clip42 反向早帧跟错；PMPose 以掩码为条件，不能修错身份。

<a id="5-separate-crop-support-from-physical-track-activity"></a>

## 5. 区分裁剪支撑与物理活动

world_pipeline.py 将 bbox 与约一秒最近接受观测最大值比：scale 至少参考 .5，真实 fill 至少 .25；长失败保最后历史不重 warmup。防坍裁剪，scale 非面积，fill 用真实掩码面积。

不支撑中心/范围插值，既有两次 5 帧平均，1.2x 放大，是**裁剪**不是 3D 根平滑。原掩码保给 PMPose/审查。独立 adapter 自己 bbox 策略；此 trailing-max 要完整 world 图。

掩码支撑不定义真实退出，需源审 lifecycle。边缘局身体/手仍活跃，完全确认退出才藏。当前 adapter 支持 active prefix/terminal inactive suffix，中间遮挡保持 active，再入需新审段。不能插值延长掩盖开头身份不明。

<a id="6-extract-mask-conditioned-2d-pose-with-pmpose-new-default"></a>

## 6. PMPose 掩码条件二维姿态（新默认）

samurai_reconstruct.py 和 world_pipeline.py prepare 默认 --pose-detector pmpose、PMPose-h，用逐帧真实人物掩码及 GVHMR 同预备 bbox。合并 COCO/AIC/MPII 为 23 joints，取前 17 canonical COCO，完整图像坐标/置信，形状 (active_frames,17,3)。

bbox 插值也不替局/坍 mask，它仍真实身份证。空 mask 零置信关键点，拒 maskless PMPose，不悄 ViTPose 回退。对照可显式 --pose-detector vitpose。旧 generic upstream demo/pilot 仍上游工具非默认。

PMPose 在独立 BBoxMaskPose，GVHMR 在兼容环境。参数 --pmpose-python/root/checkpoint/variant，可选 ld-preload；默认 PMPOSE_PYTHON/BMP_ROOT/PMPOSE_CHECKPOINT/PMPOSE_LD_PRELOAD，否则 .runtime/bmp，不改包/他环境。

PMPose **先于首次 GVHMR**。兼容文件名 preprocess/vitpose.pt 不是检测器来源。provenance.json 记检测器、运行时、实际 mask/bbox、置信、空帧、提取数；actual_model_inputs.npz 是真实模型输入，防复制旧运行换 pose 后 native/输入仍陈旧。

<a id="7-infer-source-motion-with-gvhmr"></a>

## 7. 用 GVHMR 推理源运动

新图像特征和审查裁剪、PMPose、相机旋转一起给 GVHMR。mask 注入禁默认 YOLO，用 Pi3X 非 DPVO。上游 estimate_K 假对角焦长，广角可抬相机深度（g0027 fx1469 vs Pi3X538，约3倍）。prepare --intrinsics pi3x 用同镜头 K_fullimg_pi3x；默认仍 upstream。新运行拒旧 pose/features/HMR 缓存，期望 PMPose=1、ViTPose=0、features=1。

保存 camera-frame/native global SMPL、真实输入、形状、活动、时间。新完整 world 用接受场景 prior（9B）替估重力/world rollout/体最小地板原点，保 contact-aware velocity/local pose 处理，来源记录。只 active prefix 做特征/推理。全轴可为存储重复末姿但标 inactive，填姿非观测/可见运动；终输出全时准确。

独立 native-only 导入保全片**一旋转/平移 scale1**、尺寸，不自动逐帧地板/根/平滑/IK。穿透先受影响人一常 roomZ。请求接触为独立证据候选。

<a id="8-compare-the-scene-guided-v2-candidate"></a>

## 8. 对比场景引导 v2 候选

用明确 camera-to-world 将相机身体经密集 Pi3X 提世界；只有明确启用的 Kimodo 补全先于此。GVHMR 同固定 scene-to-ground，地高/直立源自场景非人。无 prior 历史缓存仍旧人体地面并标。

只跑 **v2**，保形状/局部关节，关闭 trajectory scale。修正版用 global-branch 朝向、逐人位置、同学习率余弦衰减、加速度权重 .1；1000 iterations、postopt_lr_v2=.01、接触速度1000、高度10，平面目标2cm/Huber。不加终根平滑/frame0再对齐。

对照**场景引导 GVHMR global**，逐帧 Kabsch 回收记录相机；若补全明确开，两臂同接受补全并标混合基线。原始推理独存。旧 native_rigid 仅场景对齐诊断非主后处理对照。量脚滑、接触高/穿透、根加速，注明预测标签/人体地板未知。

各 v2 camera_world 为摆放表示非共享米相机；自变换重投影数学不变，SMPL/旋转序列小数值误，记最大相机 joint 残差查2mm。相机路长/原 Pi3X 投影为坐标诊断，**不用于拒运动估计**。fixed-world 展示仅去常 yaw/水平平移，尺度/高度不变。

旧因相机路长选 native 结论撤回，混用旧优化/不当相机指标。导入仍要共同基/支撑/视觉接触，改估计不自动选交付。检测置信非独立可见，自输入打分有偏，跨 detector 同 keypoint/源帧评两候选。

<a id="9-optional-kimodo-completion-of-low-evidence-intervals"></a>

## 9. 可选 Kimodo 弱证据区间补全

默认关补全：2026-09-17 作者认为生成视觉不满意，数值 seam 不证明好。遮挡保 GVHMR 然后提升/v2，仍可能不准，禁生成不补证据。

显式 --kimodo-completion --completion-prompt 加 bodies 后、提升/v2 前 complete；默认不需 Kimodo 环境/权重/prompt。opt-in 中 occlusion_completion.py 数 COCO17：置信>=.5、有限界内、源 mask 支撑（5px边），小于5则 active 帧无效。这是证据阈非可见测量/身份保证。

连续无效半开 [start,end)，前后立即各3可靠帧作约束，可降2，少2未解决；含锚窗口<=300帧。inactive末尾不生成/作锚。

原生 FullBodyConstraintSet 用准确帧源形世界 joints/global rotations，无效区 GVHMR pose **和 root** 都不作条件，Kimodo 都重生。原形状/时间/全部端帧和区外不变，原推理另存，生成帧在 NPZ/prediction/report 标。仅补区用生成脚标签替无效 logits，腕接触未观测。文本源动作与 seed 记。

修拼前归档 native。C2端桥仅可靠窗，Kimodo残差包络/前两导数两端零。根 cubic spline、旋转 SO(3)，不 matrix/Euler 混；只改区内。脚标签再按 FK 速/高门控，终候选过端误差/seam运动。3帧不保证平滑；失败/缺端阻后优化并保诊断。选前看源形网格/投影/地板/有限接触；错身份修跟踪非生成。

<a id="9b-reuse-the-reconstructed-scene-floor-and-upright"></a>

## 9B. 复用重建场景地板与直立方向

scene_ground.py 从先前审地面拟合导源绑定 prior。n dot x+d=0 和直立处于准确 Pi3X 相机世界，记源视频/相机包哈希、fit证、尺度/变换。camera-up 本身不是地板。平地需 normal/upright一致，斜/非平需他模型。

GVHMR world 重建用 prior，scene camera旋转替 gravity-view；contact-aware轨迹首骨盆锚场景，取消体最低点原点移，保场景高度不以身体定地。GVHMR联合预测重力，无独立模型可跳，不声称省模型调用。

固定刚性同时转身体/相机，地 Y0、直立+Y，不跑body地fit。v2固定平面、常位置旋转仅yaw，不倾直立。引导 global 已同框，不自由旋转再注册。留 ground-to-world inverse 导出，预测米未校准。不证身份/隐藏动作/家具触；数值/候选/接受分开，旧运行保body地。

`python -m tools.gvhmr.world_scene export` 可 v2 到房间，见[导出](WORLD_POSTOPT.md#export-v2-into-an-existing-authored-room)，复用房间相机/尺度，可选审深度先一水平平移再接触。

请求接触把 GVHMR 四脚通道与源手/座同解，当前 translation-only 固定所有关节，未试上身fit；禁止腿修/碰撞改关节，全身平滑平移可减相交，查运动/源拟合。2026-09-21 人体6D腿退役。v2 mesh receipt 自动供源绑定 logits/SMPL-X脚块，无手工检测。joint罚预测接触速/脚底地距，同重建地；最终再量滑动，根平移可破v2稳定。见[配置](WORLD_POSTOPT.md#export-v2-into-an-existing-authored-room)。

<a id="todo-gpt-6-guided-postprocessing-optimization"></a>

## 待完成：GPT-6 引导的后处理优化

2026-09-17 作者请求，更广优化待完。首范围保 GVHMR 预测脚速/高到场景fit，不证明运动/同时接触已解。

- [ ] GPT-6 看源、实际场景终网格和帧诊断，按具体失败改后处理代码。
- [ ] 有限手物、脚支撑/滑动、获取/释放、可靠源姿态约束；复用地/upright、native scale；评碰撞允许整体平移减穿透，不因碰撞改关节；显式遮挡/不确定触。
- [ ] 固关节下平滑根修正、稳支撑、合理转换、保动作风格；正脚净空也查，单抬人不能算接触修好。
- [ ] 联调权重、归一、时间计划、收敛；root-only冲突报告，不开腿/碰撞关节。Kimodo 默认跳过。
- [ ] 两clip同几何/时间/尺度/审接触 cohort 对比v2与接触基线，报间隙/穿透、支撑相对滑、根/joint速度加速、源一致/视觉。
- [ ] 拟合/评估 cohort分开，全审key拟合明确标，保code/config/权重/帧前后证，实际房间审和验收后才选，数值不够。

待查：clip32小物相交，clip42左脚部分支撑太高。遮挡pose和clip42开头身份需单独源审，调loss不能证明。

<a id="10-integrate-validate-and-deliver"></a>

## 10. 集成、验证与交付

蒙皮前重采样到交付时间，再烘焙人体/请求物柜动画到房间。独立ID、fixed形状、显退出藏；审场景相机，实验v2相机导入需一致候选。

请求触用真实有限几何和源接触/释放，地solver非椅/手solver。量间隙/穿透/支撑滑，诚实遮挡。重开blend，看真实渲染代表/最差指标/交叉/退出。全视频解码、帧数/率/长。in_frame非渲可见/遮挡，骨架非完整网格/家具碰撞。数值/视觉分开。

重建最终准确候选/证绑定scope，验收通过才完成/选；子进程或登记不等接受。deliveries/<scene>/versions 登记精确产物/证选接受项，重建/查认领Gallery。请求浏览器从选manifest导，不按新文件。跨场景算法对照不替交付。见[结果](RESULTS.md)和本地范围报告。

<a id="11-corrected-v2-validation"></a>

## 11. 修正 v2 的验证

更新实现在两个保留 PMPose输入上减少滑动，但 clip32 根加速度更高、clip42 穿透更坏；准确数/来源/范围见[修正对照](WORLD_POSTOPT.md#corrected-implementation-validation-2026-09-17)。旧笼统native偏好撤回，房间验收仍与已实现地/补全阶段分离。

<a id="12-historical-pmpose-integration-validation-old-v2-2026-09-17"></a>

## 12. 历史 PMPose 集成验证（旧 v2，2026-09-17）

下数是修正优化器前旧v2，不能排名当前v2/GVHMR，见[当前](WORLD_POSTOPT.md)。

新完整图 clip32 260/260 active、clip42 245/302，包括新 SAMURAI/PMPose/features/GVHMR/densePi3X/v2/review。旧 ViTPose 作记录对照，新掩码/实际bbox/dense相机精确相同。

| Clip | 运动 | ViTPose 滑动 m/s | PMPose 滑动 m/s |
| --- | --- | ---: | ---: |
| 32 | native rigid | 0.0461 | 0.0380 |
| 32 | v2 | 0.1883 | 0.2161 |
| 42 | native rigid | 0.0558 | 0.0539 |
| 42 | v2 | 0.2224 | 0.1621 |

是预测contact诊断非真值，PMPose混合非普遍改善。PMPose v2相机clip32 5.535m vs 原1.437，clip42 7.154 vs .868；错身份前缀拒绝。没选场景导入、不声称房间物理验证。

验证PMPose/实际输入、native/result准确同，调用1/0/1、inactive零key、两个关键点/world诊断全部帧；审代表源key/骨架含退出。25 focused tests通过。干净 remote-main adapter在其他共享编辑下仍准确复现clip32 bbox。

本地证 runs/_tools/pmpose-default/20260917/{REPORT.md,summary.json,visual_review.json,comparison.html} 和 clip32-r2/run、clip42-r2/run；报告区分复用/新推理及遮挡/身份/相机漂移。

<a id="portable-motion-installation"></a>

## 可移植运动安装

[人体安装](install/human-motion_zh-CN.md)记录 GVHMR/densePi3X、独立 SAM3/PMPose、可选 SAMURAI。作者v2和helper现位于 tools/gvhmr/world_backend/，world_pipeline.py prepare 默认用，无 PromptHMR 检出。上游库/权重/许可人体外部获取。
