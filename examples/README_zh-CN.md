# 示例

[English](README.md)

运行这些示例前配置运行时。源视频与预览索引见[参考视频](../references/README.md)。

## 新运动工作区

复制或执行前，先认领场景和运行路径：

```bash
python tools/task_claim.py claim new-scene --owner example-owner \
  --title 'Create a new scene workspace' --paths scenes/new_scene runs/new_scene
cp -r examples/new_scene scenes/new_scene
bash tools/indoor plan new_scene --recipe walk
bash tools/indoor run new_scene --recipe walk --motion-only
```

motion-only 范围使用 Kimodo 和 SMPL-X 生成、重采样并蒙皮人体，不打开房间。配方请求 5 秒、24 fps（120 个输出帧）。完整组装需要提供自己的 `scenes/new_scene/blender/room.blend`，在 `STATE.md` 记录来源，检查摆放和相机后去掉 `--motion-only` 运行。

## 办公室演示场景

[office48](office48/README_zh-CN.md) 是已完成的房间重建，包含恢复的源相机。使用 Blender 5.2 打开 `office48/whitebox.blend`；不需要运行时配置。

## 检查可复用 Blender 库

将 `BLENDER_BIN` 指向兼容的 Blender 可执行文件：

```bash
"$BLENDER_BIN" --background --factory-startup \
  --python tools/inspect_bundle_assets.py -- --out /tmp/indoor-assets-check.json
```

该命令追加每个注册库中声明的集合/材质，检查依赖是否位于本地并记录几何边界。它不保存源场景，不渲染或评判外观。`tests/blender/` 中已有的 Blender 集成脚本单独检查摆放和关节活动。
