<a id="shared-scene-pipeline"></a>

# 共享场景流水线

[English](PIPELINE.md)

源、房间、相机、PMPose/GVHMR、v2、计划的 Kimodo 空缺补全和交付路由见[完整 Real2Sim 流水线](REAL2SIM_PIPELINE_zh-CN.md)。

从项目根目录使用 `bash tools/indoor`。使用已有 Kimodo Python 环境，无需安装；执行规则见[运行时策略](../MACHINE_zh-CN.md)。写入前按[协作协议](COORDINATION.md)认领配方、代码和运行路径。

已部署预检、全时长预览和布局审查接口在主线中；见[场景工作流](SCENE_WORKFLOW_zh-CN.md#submission-preflight-and-full-clip-preview-acceptance)和[布局检查](LAYOUT_INSPECTION.md#pipeline-and-gvhmr-review-gates)。

<a id="commands"></a>

## 命令

新高层请求先用 `bash tools/indoor intake` 和[需求指南](SCENE_REQUESTS.md)。它收集缺少的范围并产生持久制作计划，不加载运行时路径或启动工作；与读取已有可执行配方的 `plan` 独立。已有 run/resume 行为不变。

`plan` 读配置但不加载 Blender/模型。`run` 在 GPU 前台准备并执行；`batch` 启动脱离终端的后台 worker。准备开始时快照代码和源文件。`--preview` 限制为 640×360、8 samples，帧数和时长不变。

每个批量场景/配方组合有独立目录。一个 worker 在单 GPU 上顺序运行，失败后继续；批量配方须同一运行时。目录 `runs/batches/<id>/` 含 `job.sh`、`batch.log`、每任务 `<i>.log`/`<i>.log.exit` 和 `submission.json`（`job_id`、`pid`、`runs`）。启动不等于完成；`status --live` 显示 PID 存活和退出码，需检查这些和运行报告。

```bash
bash tools/indoor scenes
bash tools/indoor plan living_room_kitchen_g0025 --recipe walk_generate
bash tools/indoor run living_room_kitchen_g0025 --recipe walk_generate --preview
bash tools/indoor status --live
```


```bash
bash tools/indoor batch living_room_kitchen_g0025:walk_replay \
  minimal_living_g0070:v4_replay pool_lounge_0a8d46c9:revised_stills \
  --preview
```


<a id="recipes-and-stages"></a>

## 配方与阶段

请求源运动对比时，可选[完整世界后优化](WORLD_POSTOPT.md)通过可恢复人体实验运行器执行新的 SAMURAI、bbox/生命周期、PMPose/GVHMR、密集 Pi3X、适配、v2 和审查。用脚滑动、接触高度、根加速度比较 GVHMR 全局后处理、相机提升初始化和修正 v2。逐人物摆放相机路径是坐标诊断，不是运动质量标准。它不替代默认原生路线，也不自动导入实验相机。显式缓存输入实验仍可用短 postopt-only 命令。

每场景含 `scene.json`、`STATE.md`、`recipes/<name>.json`。配方选择保存的源 .blend、时间、人体输入/摆放、组装、渲染和验证策略。未知字段或不一致时间失败。源场景先本地化链接库并打包文件纹理。[初始配方](../scenes/README.md)是示例，[配置验证器](../src/aha3d/config.py)定义字段。

| 人体模式 | 组装前阶段 |
| --- | --- |
| `keep` | 保留源烘焙动画，可选缓存提供关节 |
| `cache` | 导入提供的蒙皮缓存 |
| `native` | 重采样原生旋转，再用部署的 SMPL-X 插件蒙皮 |
| `generate` | Kimodo 生成，重采样旋转，再蒙皮 |

所有模式组装新场景、适用时导出标定/轨迹、重开验证并渲染。视频配方还编码并完整解码全帧序列。

时间使用显式 `frames`、有理 `fps` 和可选 `duration_seconds`：120 帧/24 为 5 秒，450 帧/30000/1001 为 15.015 秒。新动作在蒙皮前用旋转 SLERP。已有动画须已匹配时间。`cache_timing: match_scene_frames` 显式采用旧烘焙场景速率，用于归档 g0070 回放。

优先只写 frames、fps（可选 start）。duration_seconds 要准确相等，208 帧/24000/1001 的舍入小数无效。冻结配方含推导时长/终点，下游用其数量和节奏，不将归一化时间重新作为制作配置。

`preserve` 渲染要求已有 Cycles 场景；Workbench 源选 clay/material，转换默认 AgX，可显式设 view_transform/look/exposure。pool 配方沿用原预览 AgX/-0.30。

只有配方请求才平滑。`anchor: first_pelvis_xy` 把初始骨盆放到水平偏移；默认 cache_origin 平移缓存原点。ground_clearance 做逐帧垂直修正并记录到输出缓存。

<a id="run-contents-and-reproducibility"></a>

## 运行内容与可复现性

下方目录树列出状态/指纹/来源/审查、冻结代码/配方/运行时、复制输入、运动/重采样/蒙皮/组装/验证/渲染/视频和逐尝试日志。

安装运行时和许可模型保留本地、不入 Git。运行或批量活跃时不修改依赖。保存输出打包纹理且拒绝链接库；人体用烘焙形态键播放。恢复需冻结目录和已安装运行时；播放最终 .blend 不需 Kimodo。

```text
runs/<scene>/<run-id>/
  run.json                       status, fingerprints, provenance and review
  snapshot/                      frozen Python code, recipe and runtime profile
  inputs/                        copied source scene and supplied motion inputs
  stages/motion/                 generated native motion, when requested
  stages/resample/                target-timed AMASS motion and timing report
  stages/skin/                    skinned body cache and editable rig copy
  stages/assemble/                baked scene, body cache, tracks and calibration
  stages/verify/validation.json   saved-scene verification
  stages/render/                  PNG frames, receipts and completeness report
  stages/video/video.mp4          canonical encoded video
  stages/video/validation.json    full decode/timing report
  logs/                          one log per stage attempt
```


<a id="resume-and-reuse"></a>

## 恢复与复用

下方 submit 将已准备或中断运行交给新后台 worker。执行校验冻结输入，只跳过指纹/产物仍匹配的已完成阶段。仅复用仍匹配收据的渲染帧，变更/损坏帧重渲染；日志保留全部尝试。

执行锁防止同一运行并发写入，无自动过期。进程被杀后，确认记录 PID 已死亡再删除那个准确的陈旧锁。不编辑快照修代码，应新建运行。

相机/材质变体可新建配方，用下方 reuse-run 复用兼容运动。相机/渲染变化不改运动指纹；seed、时间、平滑、代码、运行时变化会使受影响复用失效。源运行须空闲。

前台 `prepare SCENE --recipe NAME --run-id ID` 只创建快照。`execute RUN --until STAGE` 在阶段后停止；`execute RUN --frame-budget 2` 在新渲染两帧后故意中断用于恢复测试。这些是诊断，不是完成验证。

```bash
bash tools/indoor submit runs/SCENE/RUN_ID
```


```bash
bash tools/indoor run SCENE --recipe VARIANT --reuse-run runs/SCENE/PREVIOUS_RUN
```


<a id="validation-and-review"></a>

## 验证与审查

检查有限几何、缓存/拓扑对应、相机标定、时间、保存播放、采样地板/取景/相交、完整渲染、视频数量/时长和全解码。碰撞策略 report/error/off；默认 5 帧，变化运动可选 all。报告注明实际采样。三角相交不证明包含、自碰撞、帧间净空或脚滑动。`in_frame` 只测视锥不测遮挡。无关节缓存回放导出零关节顶点轨迹。

validated 只表示配置的自动检查通过。先看代表性渲染帧再用下方 review/promote 记录审查。两命令本地校验产物，promote 必须有审查，写 `deliveries/<scene>/selected.json`，不复制/覆盖源。仅报告警告仍需审查。历史回放通过技术检查不自动成为接受的场景修订。

```bash
bash tools/indoor review runs/SCENE/RUN_ID --reviewer NAME \
  --frames 1 60 120 --note 'Concrete observations from these rendered frames.'
bash tools/indoor promote runs/SCENE/RUN_ID --name selected
```


<a id="adding-a-scene-or-asset"></a>

## 添加场景或资产

创建唯一场景 ID、scene.json/STATE.md，配方指向 `scenes/<scene>/blender/` 保存源，原视频放场景 references/。场景特定选项写配方，可复用行为写 `src/aha3d/`，不每场景复制运行器。便携家具/材质注册到[资产](../assets/README.md)。

已有场景 builder 保留作兼容和来源参考。历史变体现位于场景 blender/；[路径迁移](../configs/path_migrations.json)由解析器和任务认领处理旧输入。冻结运行输入/代码/报告保留原字节，恢复仍执行自身快照。

<a id="checks"></a>

## 检查

source env.sh 后在 Kimodo 解释器运行 `python -m unittest discover -s tests -v`（见[运行时](../MACHINE_zh-CN.md)）和 `python tools/check_docs.py`。单测用微型合成输入；真实 GPU 证据属于重构交接（历史/外部输入，不在本包）。

<a id="room-free-motion-and-complete-scene-coordination"></a>

## 无房间运动与完整场景协调

plan/prepare/run 的 `--motion-only` 适用于 generate/native。准备完全省略源 .blend，预期路径可不存在；仅执行 motion/resample/skin，仍用普通快照/锁/指纹。蒙皮成功也为 staged，不是 validated，因为未做场景/视频检查。恢复保留范围；batch 暂不暴露该标志，submit 可恢复。

按[场景工作流](SCENE_WORKFLOW_zh-CN.md)协调 Pi3X、白房间/相机审查、独立人物和交付。参数化 ensemble 验证补充本流水线单人体接口，覆盖最终保存场景全部声明人物。还有 CPU 相机预检、蒙皮前原生根诊断、固定 ensemble z_offset，以及 `workflow.compare --run RUN` 解析记录的视频和冻结时间，不依赖局部文件命名。

<a id="scene-ground-gvhmr-and-occlusion-completion"></a>

## 场景地面 GVHMR 与遮挡补全

[世界运动图](WORLD_POSTOPT.md)在 GVHMR 前接收已接受场景地面/直立方向，再直接相机提升和 v2。根据作者视觉反馈，Kimodo 补全默认跳过；弱证据帧保留 GVHMR，不证明准确。

显式 `--kimodo-completion --completion-prompt "Observed action description."` 加 complete。该实验使可靠掩码支撑关键点少于 5 的 PMPose 帧无效，Kimodo 使用前后各 3 个可靠帧（最低 2），不用无效 GVHMR 姿态/根做条件。未解决/拒绝区间停止 opt-in 图，证据/诊断在失败阶段 result/work。既有不可变运行保留原阶段；采用新默认需新运行，不能改旧快照。
