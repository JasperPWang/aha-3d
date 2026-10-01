# 办公室演示场景

[English](README.md)

![办公室重建的白盒渲染](../../docs/media/office48_whitebox.jpg)

这是一个带拱形梁顶的家庭办公室，由智能体工作流从 10 秒视频重建，也是[项目主页](https://kevinxu02.github.io/real2sim-indoor-site/)中的办公室示例。

`whitebox.blend`（Blender 5.2）包含可编辑房间和从视频恢复的相机：

- 401 个物体：墙体、梁顶、窗、玻璃门、支架书桌、旋转椅和访客椅、梯形书架、边柜、吊灯及道具。物体按用途命名，如 `furniture/...` 和 `architecture/...`。
- 源相机动画覆盖第 1–303 帧，30 fps，1280×720。
- 一个中性材质；文件自包含。

## 打开和渲染

```bash
blender examples/office48/whitebox.blend
```

不打开界面渲染单帧（此处为第 152 帧），并写入仓库之外：

```bash
blender --background examples/office48/whitebox.blend \
  -o /tmp/office48/frame_#### -F PNG -f 152
```

将 `-f 152` 替换为 `-a`，即可使用 Cycles 渲染完整镜头。
