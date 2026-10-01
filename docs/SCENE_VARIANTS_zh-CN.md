<a id="semantic-scene-variants-and-operable-cabinets"></a>

# 语义场景变体与可操作柜体

[English](SCENE_VARIANTS.md)

用户于 2026-09-10 接受的范围：未来场景有显式物体/表面语义，模型和材质独立替换，柜体保留原生独立开合控制。实现和验证在集成交接中维护（历史/外部输入，不随本包）。

<a id="authoring-contract"></a>

## 制作契约

使用 [RoomKit](../.agents/skills/blender-roomkit/SKILL.md)，制作家具/装饰前搜索资产索引（历史/外部输入，不随包）。新的完整物体具有稳定语义根，椅子全部几何置于同一根下，不让座/腿/适配件游离。

- instance_id：摆放物体的稳定身份，独立于网格。
- semantic_class：斜杠分类，例如 furniture/seating/chairs、furniture/storage/cabinets、decor/tabletop/vases。
- asset_id：源库项目/生成器 ID，替换时更新。
- support_id：可选桌/柜/其他支撑根身份。
- surface_role：可渲染表面用途，如 wall_finish/floor_finish，也支持逐材质槽角色。

保存 Blender 的自定义属性是权威，导出 JSON 是派生，不是第二可编辑注册表。几何替换保留 ID；新增/复制实例必须唯一。

始终使用 tag_root 返回根：给网格/集合实例打标会包装 Empty 并保留世界变换。散旧零件的 adopt_group 要显式完整列表，可接受已审查 placement_matrix。名称辅助迁移映射，不保证自动分类。替换根在接触原点（地板/桌面），正面沿局部 -Y。按[朝向契约](ASSET_ORIENTATION.md)，槽需明确制作/审查坐标框，注册模型需逐项源朝向；place_asset 先归一实际轴。无审查朝向的旧根先迁移再自动替换。

```python
from aha3d.blender.roomkit import box, place_asset
from aha3d.blender.semantics import tag_root, tag_surface, tag_support

chair = place_asset('roomkit-v1/chair-walnut-lounge',
                    location=(1.2, 2.0, 0), rotation=30,
                    instance_id='dining-chair-01', project_root=project_root)
floor = box('Floor', (0, 0, -.06), (6, 5, .12), material=floor_material,
            surface_role='floor_finish')
table = tag_root(complete_table_root, 'furniture/tables', 'table-01')
tag_support(table, xmin=-.8, xmax=.8, ymin=-.4, ymax=.4, z=.75)
vase = tag_root(complete_vase, 'decor/tabletop/vases', 'vase-01',
                support_id='table-01')
```


<a id="independent-model-and-material-recipes"></a>

## 独立模型与材质配方

2026-09-13 采用的当前质量策略，在审查后的内容升级中保留资产 ID/路径；每配方仍记录准确库哈希。[刷新工具](../tools/asset_quality_upgrade/README.md)选升级 ID，以源内容签名保护场景本地几何/材质编辑。注册库升级不自动改变已保存场景/视频。

[变体工具](../tools/scene_variant.py)在后台 Blender 开源，预检选择器/注册资产，应用配方，保存独立 .blend 和来源/语义 JSON，不覆盖已有输出。needs_extraction 先归一注册。

模型/材质列表都可省略。选择器可指定 instance_ids；分类选择包含子类。用 asset_ids 从显式兼容池按种子选。fit 必须为 native（保留摆放变换下资产尺寸）或 uniform_footprint（均匀缩放以匹配旧局部占地），不是座高拟合或自动接触求解。

材质参数 color（线性 RGB/RGBA）、roughness 显式覆盖相关 shader 输入含已有连接。物体级材质槽将目标与共享网格/材质其他使用者隔离。保留纹理坐标；未实现通用图案缩放/旋转重映射，仍遵守[材质约定](../.agents/skills/blender-roomkit/references/assets.md#material-behavior)。clear_material_override 显式露出灰模场景材质，本身不选引擎/灯光。

认领输出，source env.sh，设 PYTHONDONTWRITEBYTECODE=1 后运行下方 dry-run。移除 dry-run 保存，再作为共享配方 source；已有快照不可变。同配方替换几何上的材质操作应在第二配方应用于保存结果，以无歧义选新表面。

支撑面边界/间隙是诊断，不证明完整碰撞/遮挡净空。活跃接触或动画家具替换在提供适当动作/接触更新前拒绝。交付渲染前审查地板支撑、取景、家具/人接触。种子只在固定配方/库存复现选择，不保证未来库版本。

```json
{
  "schema_version": 1,
  "seed": 42,
  "models": [
    {
      "selector": {"semantic_class": "furniture/seating/chairs"},
      "asset_id": "roomkit-v1/chair-walnut-lounge",
      "fit": "native"
    }
  ],
  "materials": [
    {"surface_role": "wall_finish", "asset_id": "roomkit-v1/warm-ivory-lime-plaster"},
    {"surface_role": "floor_finish", "asset_id": "roomkit-v1/natural-oak-floorboards"}
  ],
  "clear_material_override": true
}
```


```bash
"$KIMODO_ROOT/tools/blender-5.2.1-linux-x64/blender" -b -t 4 \
  --python-exit-code 1 --python tools/scene_variant.py -- \
  --source SOURCE.blend --recipe VARIANT.json --out NEW.blend --dry-run
```


<a id="configurable-cabinet-construction"></a>

## 可配置柜体构建

[柜体配方](../configs/cabinets/)按左到右列、底到顶分段；width/height 为相对权重。段选 open、door_left、door_right、double_door、drawers。搁板/分隔可数量或有序内部比例，抽屉数量或底到顶高度权重。

便捷预设 default、three_drawers、mixed、open_shelving。size 描述柜体，门/把手前凸。厚度、间隙、开角、行程可配置。构建前拒绝物理不可能布局：抽屉需高度、隔板需正可用间距、抽屉活动体积不能与固定搁板共享。目前支持矩形柜、铰链门和滑动抽屉；曲柜、滑/折门和电器机构需新生成器。

新控制器暴露 open_amount（0 关/1 全开）、joint_id、joint_type、roomkit_open_property。把手随门，抽屉有底/背/侧，内搁板固定。每柜独立层级，初始关闭；可操作资产不自动加相机/动画。

控制用原生驱动/关键帧，不需插件即可持久。cabinet_controls 发现；set_open(root, amount, joint_ids=None) 调整全部/指定；animate_open(root, joint_id, poses, frames, fps) 按稳定关节操作，无需场景脚本算铰链。语义 JSON 按 owner instance ID 分组导出关节。这些控制不防相邻开门/抽屉/障碍相交。

无 layout 的 cabinet 保留历史两门一抽屉和可写 Open；新构建显式传布局/预设。animate_property(...,'Open',...) 兼容新控制器声明属性，直接编辑用真实声明属性。

```python
from aha3d.blender.roomkit import cabinet

root, controls = cabinet(
    'Kitchen mixed cabinet', location=(1.5, 2, 0), size=(1.6, .65, 1.45),
    material=front_material, interior=inside_material,
    instance_id='kitchen-cabinet-01',
    layout={
        'columns': [
            {'width': 2, 'sections': [
                {'front': 'door_left', 'shelves': [0.35, 0.7]}]},
            {'width': 1, 'sections': [
                {'front': 'drawers', 'drawer_heights': [2, 1, 1]}]}
        ]
    })
```


```python
from aha3d.blender.roomkit import animate_property

animate_property(controls[0], 'open_amount',
                 poses=[[0, 0], [1, 1], [2, 1], [3, 0]], frames=96, fps=24)
```


<a id="portable-articulated-assets"></a>

## 便携关节资产

[关节导出/导入](../src/aha3d/blender/articulated.py)保留完整原生层级、驱动、限制、自定义属性、自包含材质。导出从副本去场景时间键并关闭控制，不改源。导入创建独立树并重映射驱动。普通共享集合实例适合静态家具，不提供独立柜控。

注册关节项用 place_asset 自动解析来源/语义。静态导出器也接受单根选择 JSON 的 --articulated。完成导出/导入、独立控制、重开和视觉检查后发布审查库内容并更新 manifest/registry checksum。拒绝不支持的外部驱动/材质/物体依赖，刻意限制为自包含 Empty/mesh 家具骨架。

```python
from aha3d.blender.articulated import export_articulated, import_articulated

manifest = export_articulated(root, new_library_directory,
                              asset_name='RK Cabinet - Mixed Storage')
instance = import_articulated(library_path, 'RK Cabinet - Mixed Storage',
                              location=(3, 0, 0), instance_id='cabinet-02')
```


<a id="demonstration-and-evidence"></a>

## 演示与证据

演示状态（历史/外部输入，不随包）链接当前保存场景、静帧和验证。它是制作的功能测试场景，不是视频重建。用于提取椅/花瓶的原版本保持只读和原状态。
