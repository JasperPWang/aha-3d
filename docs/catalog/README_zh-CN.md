# 室内工作流目录

[English](README.md)

目录根据资产索引、注册表、技能 frontmatter、流水线源码和可选演示清单生成。用 `python tools/build_catalog.py build` 重建英文目录，`python tools/build_catalog.py check` 验证；本文件为对应中文版本。

[资产](#assets) · [技能](#skills) · [流水线](#pipeline) · [演示](#demos) · [本地 HTML](index.html)

[安装](../INSTALLATION_zh-CN.md) · [项目主页](../../README_zh-CN.md)

<a id="assets"></a>

## 资产

仅包含注册的可复用库和共享辅助工具，不包括历史场景候选。

### 资产库

| 资产库 | Blender 文件 | 清单 |
| --- | --- | --- |
| additional-444547-44-v1 | [Blender 库](../../assets/additional-444547/v1/scene44/roomkit_furniture_materials.blend) | [清单](../../assets/additional-444547/v1/scene44/manifest.json) |
| additional-444547-45-v1 | [Blender 库](../../assets/additional-444547/v1/scene45/roomkit_furniture_materials.blend) | [清单](../../assets/additional-444547/v1/scene45/manifest.json) |
| additional-444547-47-v1 | [Blender 库](../../assets/additional-444547/v1/scene47/roomkit_furniture_materials.blend) | [清单](../../assets/additional-444547/v1/scene47/manifest.json) |
| cabinets-v1 | [Blender 库](../../assets/cabinets/v1/articulated_furniture.blend) | [清单](../../assets/cabinets/v1/manifest.json) |
| ceramic-vase-v1 | [Blender 库](../../assets/scene-extracted/v1/vase/roomkit_furniture_materials.blend) | [清单](../../assets/scene-extracted/v1/vase/manifest.json) |
| dining-chair-v1 | [Blender 库](../../assets/scene-extracted/v1/chair/roomkit_furniture_materials.blend) | [清单](../../assets/scene-extracted/v1/chair/manifest.json) |
| faucet-simple-v1 | [Blender 库](../../assets/fixtures/v1/simple_faucet/roomkit_furniture_materials.blend) | [清单](../../assets/fixtures/v1/simple_faucet/manifest.json) |
| plants-v1 | [Blender 库](../../assets/plants/v1/roomkit_furniture_materials.blend) | [清单](../../assets/plants/v1/manifest.json) |
| plants-v2 | [Blender 库](../../assets/plants/v2/roomkit_furniture_materials.blend) | [清单](../../assets/plants/v2/manifest.json) |
| roomkit-v1 | [Blender 库](../../assets/roomkit/v1/roomkit_furniture_materials.blend) | [清单](../../assets/roomkit/v1/manifest.json) |
| seating-refined-v1 | [Blender 库](../../assets/seating/refined_v1/roomkit_furniture_materials.blend) | [清单](../../assets/seating/refined_v1/manifest.json) |
| tabletop-plants-v1 | [Blender 库](../../assets/plants/tabletop_v1/roomkit_furniture_materials.blend) | [清单](../../assets/plants/tabletop_v1/manifest.json) |

registered = 可复用库条目；callable = 源码辅助工具；needs_extraction = 需单独提取/审查的候选。

| 条目 | 分类 / 状态 | 尺寸（m） | 来源 / 预览 |
| --- | --- | --- | --- |
| **Additional 45 \| Lounge window frame**<br>Additional 45 \| 休息区窗框<br>additional-444547-45-v1/additional-45-lounge-window-frame<br>源中独立开口饰框组件；不含玻璃、铰链、墙或室外景。安装原点在包围中心。源派生近似静态资产，无真实人物数据；见 provenance.json。 | architecture/windows<br>registered | 2.4 × 0.25 × 2.63 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 47 \| Bedroom window casing**<br>Additional 47 \| 卧室窗套<br>additional-444547-47-v1/additional-47-bedroom-window-casing<br>两个重复分格窗框之一，蓝色景观卡作为场景背景省略。原点归一到组件安装中心。源派生近似静态资产，无真实人物数据；见 provenance.json。 | architecture/windows<br>registered | 1.01 × 0.11 × 1.88 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **Additional 45 \| Six candle group**<br>Additional 45 \| 六支蜡烛组<br>additional-444547-45-v1/additional-45-six-candle-group<br>用圆蜡体、凹蜡顶和六根棉芯替换实心蜡烛块。六底均置于组支撑面，保各高度和整体范围；材质改蜡/芯而非亚麻软包。 | decor/candles<br>registered | 0.865 × 0.065 × 0.48 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/quality_previews/additional-444547-45-v1__additional-45-six-candle-group.png) |
| **Additional 47 \| Banded linen curtain pair**<br>Additional 47 \| 带条带的亚麻窗帘对<br>additional-444547-47-v1/additional-47-banded-linen-curtain-pair<br>用薄褶亚麻面与原生网格厚度替换两块 100 mm 实心板。每帘四灰褐条带作为布上材质区域，去独立条带盒。顶部布聚到杆接触，保安装原点、杆与下摆高度。静态制作褶皱，未验证布模拟。 | decor/curtains<br>registered | 1.48 × 0.133 × 2.05 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) · [预览](../../assets/quality_previews/additional-444547-47-v1__additional-47-banded-linen-curtain-pair.png) |
| **RK Plant - Broadleaf Ceramic**<br>RK Plant - 阔叶植物陶瓷盆<br>plants-v1/plant-broadleaf-ceramic<br>保叶、基质和盆位置，沿测量地标平滑原盆剖面。48边盆改128边封闭器，完整内腔、径向壁8mm/底16mm。源派生或制作近似，无物理认证。 | decor/plants<br>registered | 0.742 × 0.79 × 0.71 | [来源](../../assets/plants/v1/manifest.json) · [预览](../../assets/quality_previews/plants-v1__plant-broadleaf-ceramic.png) |
| **RK Plant - Peace Lily Natural**<br>RK Plant - 自然白掌<br>plants-v2/plant-peace-lily-natural<br>保叶、基质和盆位置，沿测量地标平滑原盆剖面。48边盆改128边封闭器，完整内腔、径向壁8mm/底16mm。源派生或制作近似，无物理认证。 | decor/plants<br>registered | 0.755 × 0.7 × 0.719 | [来源](../../assets/plants/v2/manifest.json) · [预览](../../assets/quality_previews/plants-v2__plant-peace-lily-natural.png) |
| **RK Flowers - Pink Hydrangea Bowl**<br>RK Flowers - 粉色绣球花盆<br>tabletop-plants-v1/flowers-pink-hydrangea-bowl<br>焊接容器/基质网格重复轴极点，关闭假边界环并恢复有效实体拓扑。保肋碗/盆形、全部叶、材质和几何位置。源派生或制作近似，无物理认证。 | decor/plants<br>registered | 0.248 × 0.232 × 0.294 | [来源](../../assets/plants/tabletop_v1/manifest.json) · [预览](../../assets/quality_previews/tabletop-plants-v1__flowers-pink-hydrangea-bowl.png) |
| **RK Plant - Compact Fern**<br>RK Plant - 紧凑蕨类<br>tabletop-plants-v1/plant-compact-fern<br>焊接容器/基质网格重复轴极点，关闭假边界环并恢复有效实体拓扑。保肋碗/盆形、全部叶、材质和几何位置。源派生或制作近似，无物理认证。 | decor/plants<br>registered | 0.353 × 0.355 × 0.276 | [来源](../../assets/plants/tabletop_v1/manifest.json) · [预览](../../assets/quality_previews/tabletop-plants-v1__plant-compact-fern.png) |
| **RK Vase - Rounded Ceramic**<br>RK Vase - 圆润陶瓷花瓶<br>ceramic-vase-v1/vase-rounded-ceramic<br>平滑原外地标、不超半径，浅内颈延为全深腔。封缺底，圆唇/14mm底连接内外壳。源派生或制作近似，无物理认证。 | decor/tabletop/vases<br>registered | 0.342 × 0.342 × 0.438 | [来源](../../assets/scene-extracted/v1/vase/manifest.json) · [预览](../../assets/quality_previews/ceramic-vase-v1__vase-rounded-ceramic.png) |
| **Additional 44 \| Silver serving platter**<br>Additional 44 \| 银色托盘<br>additional-444547-44-v1/additional-44-silver-serving-platter<br>用连续盛放面、凹槽、卷边和支脚替重叠厚圆盘/环。保外径308mm、总高18mm和银材质。源派生或制作近似，无物理认证。 | decor/tableware<br>registered | 0.308 × 0.308 × 0.018 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/quality_previews/additional-444547-44-v1__additional-44-silver-serving-platter.png) |
| **Additional 44 \| Stylized stemmed vessel**<br>Additional 44 \| 风格化高脚器皿<br>additional-444547-44-v1/additional-44-stylized-stemmed-vessel<br>三个相交24边实体代理改连续128边器壳，制作开口杯、2.4mm直壁、封底、软边、连续柄底连接。源派生或制作近似，无物理认证。 | decor/tableware<br>registered | 0.09 × 0.09 × 0.305 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/quality_previews/additional-444547-44-v1__additional-44-stylized-stemmed-vessel.png) |
| **Additional 45 \| Folded linen napkin**<br>Additional 45 \| 折叠亚麻餐巾<br>additional-444547-45-v1/additional-45-folded-linen-napkin<br>厚盒替为四贴合亚麻层、卷边/细微起伏，保桌面占地/支撑。静态折布几何，无布求解器/模拟声明。 | decor/tableware<br>registered | 0.19 × 0.1 × 0.0249 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/quality_previews/additional-444547-45-v1__additional-45-folded-linen-napkin.png) |
| **Additional 45 \| Small porcelain vase**<br>Additional 45 \| 小瓷花瓶<br>additional-444547-45-v1/additional-45-small-porcelain-vase<br>带盖实心瓷柱重建为128径向分段的封闭空心器，保测得圆外轮廓/陶瓷，径向壁3mm、底7mm。源派生或制作近似，无物理认证。 | decor/vases<br>registered | 0.08 × 0.08 × 0.12 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/quality_previews/additional-444547-45-v1__additional-45-small-porcelain-vase.png) |
| **Additional 45 \| Tall porcelain vase**<br>Additional 45 \| 高瓷花瓶<br>additional-444547-45-v1/additional-45-tall-porcelain-vase<br>带盖实心瓷柱重建为128径向分段的封闭空心器，保测得圆外轮廓/陶瓷，径向壁4mm、底7mm。源派生或制作近似，无物理认证。 | decor/vases<br>registered | 0.13 × 0.13 × 0.2 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/quality_previews/additional-444547-45-v1__additional-45-tall-porcelain-vase.png) |
| **Additional 44 \| Classical vase wall panel**<br>Additional 44 \| 古典花瓶墙板<br>additional-444547-44-v1/additional-44-classical-vase-wall-panel<br>两个重复浅浮雕之一；画作是可编辑几何，不是源图。源派生近似静态资产，无真实人物数据；见 provenance.json。 | decor/wall_art<br>registered | 0.6 × 0.0765 × 0.78 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) |
| **Additional 45 \| Abstract wall panel**<br>Additional 45 \| 抽象墙板<br>additional-444547-45-v1/additional-45-abstract-wall-panel<br>可编辑浅层几何颜料板，无参考图片纹理。源派生近似静态资产，无真实人物数据；见 provenance.json。 | decor/wall_art<br>registered | 2.45 × 0.09 × 0.95 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 47 \| Framed portrait panel**<br>Additional 47 \| 带框肖像板<br>additional-444547-47-v1/additional-47-framed-portrait-panel<br>源特定静态可编辑近似，尺寸为制作值非校准测量。源名 mirror 仅哑光框板，无反射玻璃。源派生近似静态资产，无真实人物数据；见 provenance.json。 | decor/wall_art<br>registered | 0.62 × 0.062 × 0.79 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **Additional 47 \| Landscape wall panel**<br>Additional 47 \| 风景墙板<br>additional-444547-47-v1/additional-47-landscape-wall-panel<br>源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | decor/wall_art<br>registered | 0.72 × 0.062 × 0.58 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **Additional 47 \| Small gallery panel**<br>Additional 47 \| 小画廊墙板<br>additional-444547-47-v1/additional-47-small-gallery-panel<br>源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | decor/wall_art<br>registered | 0.35 × 0.062 × 0.44 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **RK Faucet - Simple Gooseneck**<br>RK Faucet - 简易鹅颈水龙头<br>faucet-simple-v1/faucet-simple-gooseneck<br>给原开放单面管加1.2mm向内壁和环形端边，出口/安装端保持开口。以拉丝不锈钢替提取灰模，保原中心线/安装原点。无阀、内部流动或管道模拟。 | fixtures/plumbing/faucets<br>registered | 0.024 × 0.254 × 0.363 | [来源](../../assets/fixtures/v1/simple_faucet/manifest.json) · [预览](../../assets/quality_previews/faucet-simple-v1__faucet-simple-gooseneck.png) |
| **Additional 47 \| Four poster bed**<br>Additional 47 \| 四柱床<br>additional-444547-47-v1/additional-47-four-poster-bed<br>源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | furniture/beds<br>registered | 1.73 × 2.03 × 1.91 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **Additional 44 \| Clear polycarbonate dining chair**<br>Additional 44 \| 透明聚碳酸酯餐椅<br>additional-444547-44-v1/additional-44-clear-polycarbonate-dining-chair<br>源制作透射材质和六独立零件，便携支撑连接单独审查。源派生近似静态资产，无真实人物数据；见 provenance.json。便携副本延靠背下板与座重叠10mm，消除原17.5mm无支撑间隙，保顶部高/透射材质。 | furniture/seating/chairs<br>registered | 0.45 × 0.43 × 1.26 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) |
| **Additional 44 \| Upholstered open frame chair**<br>Additional 44 \| 软包开放框架椅<br>additional-444547-44-v1/additional-44-upholstered-open-frame-chair<br>由 dining-chair-v1/chair-open-frame-dining 改静态软包开放餐椅。藤编/板条换为原支撑背框范围内炭灰垫，接触重叠2mm。仅便携副本替源未旋转浮空叠层，原场景不变。独立可编辑网格，源尺度未校准。 | furniture/seating/chairs<br>registered | 0.49 × 0.442 × 0.86 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) |
| **Additional 45 \| Occupied walnut lounge chair**<br>Additional 45 \| 人物使用的胡桃木休闲椅<br>additional-444547-45-v1/additional-45-occupied-walnut-lounge-chair<br>改 roomkit-v1/chair-walnut-lounge：均匀.62尺度上宽x1.15，垫+.012m，去腰枕，尺度烘焙可编辑网格。源派生近似静态，无真实人物数据；见 provenance.json。原范围内加两胡桃木后支撑板。 | furniture/seating/chairs<br>registered | 0.602 × 0.552 × 0.669 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/quality_previews/additional-444547-45-v1__additional-45-occupied-walnut-lounge-chair.png) |
| **RK Chair - Open Frame Dining**<br>RK Chair - 开放框架餐椅<br>dining-chair-v1/chair-open-frame-dining<br>现有源特定扶手餐椅、简化板条背，已归一复用。 | furniture/seating/chairs<br>registered | 0.49 × 0.443 × 0.86 | [来源](../../assets/scene-extracted/v1/chair/manifest.json) |
| **RK Chair - Walnut Lounge**<br>RK Chair - 胡桃木休闲椅<br>roomkit-v1/chair-walnut-lounge<br>胡桃木软包座/背休闲椅，独立可编辑零件，正面局部-Y。原范围内加两后支板，腰枕/滚边降18mm使座支撑接触。修封闭网格 Lounge chair A lumbar pillow.001 内向法线，保顶点、UV、材质图。 | furniture/seating/chairs<br>registered | 0.845 × 0.89 × 1.09 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../assets/quality_previews/roomkit-v1__chair-walnut-lounge.png) |
| **RK Chair - Accent Supported**<br>RK Chair - 带支撑装饰椅<br>seating-refined-v1/chair-accent-supported<br>原倒角背/座仅相切；保顶部/占地，增加重叠和连续内部后立柱。 | furniture/seating/chairs<br>registered | 0.48 × 0.46 × 0.84 | [来源](../../assets/seating/refined_v1/manifest.json) |
| **RK Chair - Walnut Lounge Supported**<br>RK Chair - 带支撑胡桃木休闲椅<br>seating-refined-v1/chair-walnut-lounge-supported<br>原背有扶手支撑，加后横杆到垫直接支撑，闭合测得6.59132mm腰枕到座间隙。修 Lounge chair A lumbar pillow.001 内向法线，保顶点、UV、材质图。 | furniture/seating/chairs<br>registered | 0.845 × 0.89 × 1.09 | [来源](../../assets/seating/refined_v1/manifest.json) · [预览](../../assets/quality_previews/seating-refined-v1__chair-walnut-lounge-supported.png) |
| **Additional 47 \| Low back chaise**<br>Additional 47 \| 低靠背躺椅<br>additional-444547-47-v1/additional-47-low-back-chaise<br>源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | furniture/seating/daybeds<br>registered | 0.65 × 1.28 × 0.81 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **Additional 45 \| Central island sofa**<br>Additional 45 \| 中央岛式沙发<br>additional-444547-45-v1/additional-45-central-island-sofa<br>独立可编辑底座、平台、软包和枕；源特定近似尺寸。源派生静态近似，无真实人物数据；见 provenance.json。 | furniture/seating/sofas<br>registered | 3.25 × 0.95 × 0.88 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 45 \| Lounge rear sofa**<br>Additional 45 \| 休息区后排沙发<br>additional-444547-45-v1/additional-45-lounge-rear-sofa<br>独立可编辑底座、平台、软包和枕；源特定近似尺寸。源派生静态近似，无真实人物数据；见 provenance.json。 | furniture/seating/sofas<br>registered | 2.8 × 0.95 × 0.88 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 45 \| Main right return**<br>Additional 45 \| 主右侧转角模块<br>additional-444547-45-v1/additional-45-main-right-return<br>独立可编辑底座、平台、软包和枕；源特定近似尺寸。源派生静态近似，无真实人物数据；见 provenance.json。 | furniture/seating/sofas<br>registered | 1.65 × 0.95 × 0.88 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 45 \| Main right sofa**<br>Additional 45 \| 主右侧沙发<br>additional-444547-45-v1/additional-45-main-right-sofa<br>独立可编辑底座、平台、软包和枕；源特定近似尺寸。源派生静态近似，无真实人物数据；见 provenance.json。 | furniture/seating/sofas<br>registered | 2.3 × 0.95 × 0.88 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 45 \| Right sectional assembly**<br>Additional 45 \| 右侧组合沙发<br>additional-444547-45-v1/additional-45-right-sectional-assembly<br>用source45主/转角沙发制作可拆模块L对。保独立平台、底、座、背、枕、扶手，以外背/15mm连接净距替源角重叠。便携布局是制作适配，不是连续软包转角。源近似尺寸，无校准尺度声明。 | furniture/seating/sofas<br>registered | 2.15 × 3.27 × 0.88 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **RK Sofa - Linen Three Seat**<br>RK Sofa - 亚麻三人沙发<br>roomkit-v1/sofa-linen-three-seat<br>三人亚麻沙发，独立座/背/装饰垫，地板中心摆放，朝向局部 -Y 轴。修正 Sofa A \| below tall windows loose pillow 0.001、1.001、2.001、3.001 封闭网格的内向法线，保留顶点、UV 和材质贴图。 | furniture/seating/sofas<br>registered | 2.81 × 0.995 × 1.14 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../assets/quality_previews/roomkit-v1__sofa-linen-three-seat.png) |
| **RK Stool - Upholstered Counter**<br>RK Stool - 软包吧台凳<br>roomkit-v1/stool-upholstered-counter<br>胡桃木框/脚踏厨房软包吧台凳，中性静态姿态，前局部-Y。 | furniture/seating/stools<br>registered | 0.498 × 0.606 × 1.16 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/furniture_03.png) |
| **Additional 44 \| Six drawer mahogany sideboard**<br>Additional 44 \| 六抽屉桃花心木餐边柜<br>additional-444547-44-v1/additional-44-six-drawer-mahogany-sideboard<br>静态六抽屉立面和把手，无可用抽屉/隐藏柜内。源派生静态近似，无真实人物数据；见 provenance.json。 | furniture/storage<br>registered | 2.11 × 0.568 × 0.958 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) |
| **Additional 45 \| Staff counter block**<br>Additional 45 \| 工作人员柜台块<br>additional-444547-45-v1/additional-45-staff-counter-block<br>最小独立柜台块代理，无隐藏服务配件/可操作门。源派生静态近似，无真实人物数据；见 provenance.json。 | furniture/storage<br>registered | 4.5 × 0.7 × 1.02 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 47 \| Six drawer dresser**<br>Additional 47 \| 六抽屉斗柜<br>additional-444547-47-v1/additional-47-six-drawer-dresser<br>源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | furniture/storage<br>registered | 1.48 × 0.541 × 0.885 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **RK Cabinet - Mixed Storage**<br>RK Cabinet - 混合储物柜<br>cabinets-v1/cabinet-mixed-storage<br>可编辑柜，独立原生门/抽屉控制。 | furniture/storage/cabinets<br>registered | 1.65 × 0.708 × 1.45 | [来源](../../assets/cabinets/v1/manifest.json) |
| **Additional 44 \| Formal dining table**<br>Additional 44 \| 正式餐桌<br>additional-444547-44-v1/additional-44-formal-dining-table<br>源特定桌面/四腿，无餐具。源派生静态近似，无真实人物数据；见 provenance.json。便携副本腿顶伸入桌底5mm，修原2.5mm支撑隙。 | furniture/tables<br>registered | 2.1 × 0.8 × 0.777 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) |
| **Additional 45 \| Round brass side table**<br>Additional 45 \| 圆形黄铜边桌<br>additional-444547-45-v1/additional-45-round-brass-side-table<br>五重复边桌之一，花瓶另导。源派生静态近似，无真实人物数据；见 provenance.json。便携副本柱顶伸入桌面5mm，修原2.5mm支撑隙。 | furniture/tables<br>registered | 0.78 × 0.78 × 0.498 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 45 \| Square dining table**<br>Additional 45 \| 方餐桌<br>additional-444547-45-v1/additional-45-square-dining-table<br>默认方桌面，六重复未适配摆放之一。源派生静态近似，无真实人物数据；见 provenance.json。 | furniture/tables<br>registered | 1.08 × 1.08 × 0.562 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 45 \| Square dining table wide support**<br>Additional 45 \| 宽支撑方餐桌<br>additional-444547-45-v1/additional-45-square-dining-table-wide-support<br>宽支撑变体用源最终腿偏移±0.46m。源派生静态近似，无真实人物数据；见 provenance.json。 | furniture/tables<br>registered | 1.08 × 1.08 × 0.562 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) |
| **Additional 47 \| Foot desk**<br>Additional 47 \| 床尾书桌<br>additional-444547-47-v1/additional-47-foot-desk<br>源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | furniture/tables<br>registered | 1.52 × 0.54 × 0.655 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **Additional 47 \| Walnut bedside table**<br>Additional 47 \| 胡桃木床头柜<br>additional-444547-47-v1/additional-47-walnut-bedside-table<br>源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | furniture/tables<br>registered | 0.61 × 0.49 × 0.647 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) |
| **Configurable operable cabinet**<br>可配置可操作柜体<br>generator/roomkit-cabinet<br>可操作柜生成器：显式布局支持加权列/段、可变抽屉数/高、单/双门、搁板/内分隔。省布局保原两门一抽屉接口。 | generators/furniture<br>callable | 未记录 | [来源](../../src/aha3d/blender/roomkit.py) |
| **Beveled box**<br>倒角盒体<br>generator/roomkit-box<br>盒体生成器：显式尺寸、材质、目标集合和边半径。 | generators/primitives<br>callable | 未记录 | [来源](../../src/aha3d/blender/roomkit.py) |
| **Additional 44 \| Double ring chandelier**<br>Additional 44 \| 双环吊灯<br>additional-444547-44-v1/additional-44-double-ring-chandelier<br>可编辑双环黄铜吊灯代理，六源外立杆，制作斜悬链/径向杆把两环接中心杆/顶盘。原点顶盘安装面中心。新增支撑是便携副本补全，不是源观察细节/结构认证，无光度灯源。 | lighting/fixtures<br>registered | 1.22 × 1.22 × 0.722 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) |
| **Additional 44 \| Wall sconce**<br>Additional 44 \| 壁灯<br>additional-444547-44-v1/additional-44-wall-sconce<br>实心灯罩替2mm上下开口矩形壳；加内部安装支撑、灯座、磨砂泡，保墙板、安装原点/外范围。 | lighting/fixtures<br>registered | 0.15 × 0.195 × 0.32 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/quality_previews/additional-444547-44-v1__additional-44-wall-sconce.png) |
| **Additional 47 \| Brass linen table lamp**<br>Additional 47 \| 黄铜亚麻台灯<br>additional-444547-47-v1/additional-47-brass-linen-table-lamp<br>灯罩重建1.6mm开口锥壳，可见内壁/边环；加三黄铜内支撑/磨砂泡，保灯高、底、杆/材质外观。无光度标定。 | lighting/fixtures<br>registered | 0.33 × 0.33 × 0.566 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) · [预览](../../assets/quality_previews/additional-444547-47-v1__additional-47-brass-linen-table-lamp.png) |
| **RK \| Charcoal ceramic bowl**<br>RK \| 炭灰陶瓷碗<br>roomkit-v1/charcoal-ceramic-bowl<br>可编辑程序化材质：RK \| 炭灰陶瓷碗 | materials/ceramic<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_22.png) |
| **RK \| Glazed cream ceramic**<br>RK \| 釉面奶油色陶瓷<br>roomkit-v1/glazed-cream-ceramic<br>可编辑程序化材质：RK \| 釉面奶油色陶瓷 | materials/ceramic<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_21.png) |
| **RK \| Charcoal woven upholstery**<br>RK \| 炭灰编织软包<br>roomkit-v1/charcoal-woven-upholstery<br>可编辑程序化材质：RK \| 炭灰编织软包 | materials/fabric<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_12.png) |
| **RK \| Cream linen cushions**<br>RK \| 奶油色亚麻靠垫<br>roomkit-v1/cream-linen-cushions<br>可编辑程序化材质：RK \| 奶油色亚麻靠垫 | materials/fabric<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_09.png) |
| **RK \| Ivory linen sofa**<br>RK \| 象牙色亚麻沙发<br>roomkit-v1/ivory-linen-sofa<br>可编辑程序化材质：RK \| 象牙色亚麻沙发 | materials/fabric<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_08.png) |
| **RK \| Ivory woven rug with charcoal border**<br>RK \| 炭灰边象牙色编织地毯<br>roomkit-v1/ivory-woven-rug-with-charcoal-border<br>可编辑程序化材质：RK \| 炭灰边象牙色编织地毯 | materials/fabric<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_14.png) |
| **RK \| Lampshade ivory linen**<br>RK \| 象牙色亚麻灯罩<br>roomkit-v1/lampshade-ivory-linen<br>可编辑程序化材质：RK \| 象牙色亚麻灯罩 | materials/fabric<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_29.png) |
| **RK \| Olive brown accent cushions**<br>RK \| 橄榄棕装饰靠垫<br>roomkit-v1/olive-brown-accent-cushions<br>可编辑程序化材质：RK \| 橄榄棕装饰靠垫 | materials/fabric<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_11.png) |
| **RK \| Taupe woven cushions**<br>RK \| 灰褐编织靠垫<br>roomkit-v1/taupe-woven-cushions<br>可编辑程序化材质：RK \| 灰褐编织靠垫 | materials/fabric<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_10.png) |
| **RK \| Warm grey drapery**<br>RK \| 暖灰窗帘<br>roomkit-v1/warm-grey-drapery<br>可编辑程序化材质：RK \| 暖灰窗帘 | materials/fabric<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_13.png) |
| **RK \| Aged brass handles**<br>RK \| 仿旧黄铜把手<br>roomkit-v1/aged-brass-handles<br>可编辑程序化材质：RK \| 仿旧黄铜把手 | materials/metal<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_17.png) |
| **RK \| Aged bronze table drums**<br>RK \| 仿旧青铜鼓形桌体<br>roomkit-v1/aged-bronze-table-drums<br>可编辑程序化材质：RK \| 仿旧青铜鼓形桌体 | materials/metal<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_15.png) |
| **RK \| Brushed stainless steel**<br>RK \| 拉丝不锈钢<br>roomkit-v1/brushed-stainless-steel<br>可编辑程序化材质：RK \| 拉丝不锈钢 | materials/metal<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_18.png) |
| **RK \| Satin blackened iron**<br>RK \| 缎面发黑铁<br>roomkit-v1/satin-blackened-iron<br>可编辑程序化材质：RK \| 缎面发黑铁 | materials/metal<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_16.png) |
| **RK \| Book pages and artwork**<br>RK \| 书页与画作<br>roomkit-v1/book-pages-and-artwork<br>可编辑程序化材质：RK \| 书页与画作 | materials/other<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_31.png) |
| **RK \| Dark television glass**<br>RK \| 深色电视玻璃<br>roomkit-v1/dark-television-glass<br>可编辑程序化材质：RK \| 深色电视玻璃 | materials/other<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_27.png) |
| **RK \| Deep green orchid leaves**<br>RK \| 深绿兰花叶<br>roomkit-v1/deep-green-orchid-leaves<br>可编辑程序化材质：RK \| 深绿兰花叶 | materials/other<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_23.png) |
| **RK \| Green pears**<br>RK \| 青梨<br>roomkit-v1/green-pears<br>可编辑程序化材质：RK \| 青梨 | materials/other<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_28.png) |
| **RK \| Ivory orchid petals**<br>RK \| 象牙色兰花瓣<br>roomkit-v1/ivory-orchid-petals<br>可编辑程序化材质：RK \| 象牙色兰花瓣 | materials/other<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_24.png) |
| **RK \| Warm practical bulbs**<br>RK \| 暖色实景灯泡<br>roomkit-v1/warm-practical-bulbs<br>可编辑程序化材质：RK \| 暖色实景灯泡 | materials/other<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_30.png) |
| **RK \| Warm ivory lime plaster**<br>RK \| 暖象牙色石灰灰泥<br>roomkit-v1/warm-ivory-lime-plaster<br>可编辑程序化材质：RK \| 暖象牙色石灰灰泥 | materials/paint_and_plaster<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_01.png) |
| **RK \| Warm white painted joinery**<br>RK \| 暖白漆木作<br>roomkit-v1/warm-white-painted-joinery<br>可编辑程序化材质：RK \| 暖白漆木作 | materials/paint_and_plaster<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_02.png) |
| **RK \| Brass**<br>RK \| 黄铜<br>additional-444547-44-v1/brass<br>可编辑程序化材质：RK \| 黄铜 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_01.png) |
| **RK \| Brown floor**<br>RK \| 棕色地板<br>additional-444547-44-v1/brown-floor<br>可编辑程序化材质：RK \| 棕色地板 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_02.png) |
| **RK \| Charcoal upholstery**<br>RK \| 炭灰软包<br>additional-444547-44-v1/charcoal-upholstery<br>可编辑程序化材质：RK \| 炭灰软包 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_03.png) |
| **RK \| Clear polycarbonate**<br>RK \| 透明聚碳酸酯<br>additional-444547-44-v1/clear-polycarbonate<br>可编辑程序化材质：RK \| 透明聚碳酸酯 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_04.png) |
| **RK \| Dark stone**<br>RK \| 深色石材<br>additional-444547-44-v1/dark-stone<br>可编辑程序化材质：RK \| 深色石材 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_05.png) |
| **RK \| Glass approximation**<br>RK \| 近似玻璃<br>additional-444547-44-v1/glass-approximation<br>可编辑程序化材质：RK \| 近似玻璃 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_06.png) |
| **RK \| Mahogany sideboard**<br>RK \| 桃花心木餐边柜<br>additional-444547-44-v1/mahogany-sideboard<br>可编辑程序化材质：RK \| 桃花心木餐边柜 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_07.png) |
| **RK \| Picture ink**<br>RK \| 图像墨色<br>additional-444547-44-v1/picture-ink<br>可编辑程序化材质：RK \| 图像墨色 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_08.png) |
| **RK \| Silver platter**<br>RK \| 银色托盘<br>additional-444547-44-v1/silver-platter<br>可编辑程序化材质：RK \| 银色托盘 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_09.png) |
| **RK \| Warm grey wall paint**<br>RK \| 暖灰墙漆<br>additional-444547-44-v1/warm-grey-wall-paint<br>可编辑程序化材质：RK \| 暖灰墙漆 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_10.png) |
| **RK \| Warm white**<br>RK \| 暖白<br>additional-444547-44-v1/warm-white<br>可编辑程序化材质：RK \| 暖白 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene44/manifest.json) · [预览](../../assets/additional-444547/v1/scene44/previews/material_11.png) |
| **RK \| Aged brass**<br>RK \| 仿旧黄铜<br>additional-444547-45-v1/aged-brass<br>可编辑程序化材质：RK \| 仿旧黄铜 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_01.png) |
| **RK \| Artwork pigment 0**<br>RK \| 画作颜料 0<br>additional-444547-45-v1/artwork-pigment-0<br>可编辑程序化材质：RK \| 画作颜料 0 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_02.png) |
| **RK \| Artwork pigment 1**<br>RK \| 画作颜料 1<br>additional-444547-45-v1/artwork-pigment-1<br>可编辑程序化材质：RK \| 画作颜料 1 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_03.png) |
| **RK \| Artwork pigment 2**<br>RK \| 画作颜料 2<br>additional-444547-45-v1/artwork-pigment-2<br>可编辑程序化材质：RK \| 画作颜料 2 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_04.png) |
| **RK \| Dark bronze**<br>RK \| 深色青铜<br>additional-444547-45-v1/dark-bronze<br>可编辑程序化材质：RK \| 深色青铜 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_05.png) |
| **RK \| Honed limestone**<br>RK \| 磨光石灰石<br>additional-444547-45-v1/honed-limestone<br>可编辑程序化材质：RK \| 磨光石灰石 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_06.png) |
| **RK \| Navy upholstery**<br>RK \| 海军蓝软包<br>additional-444547-45-v1/navy-upholstery<br>可编辑程序化材质：RK \| 海军蓝软包 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_07.png) |
| **RK \| Pale woven linen**<br>RK \| 浅色编织亚麻<br>additional-444547-45-v1/pale-woven-linen<br>可编辑程序化材质：RK \| 浅色编织亚麻 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_08.png) |
| **RK \| Porcelain**<br>RK \| 瓷器<br>additional-444547-45-v1/porcelain<br>可编辑程序化材质：RK \| 瓷器 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_09.png) |
| **RK \| Walnut**<br>RK \| 胡桃木<br>additional-444547-45-v1/walnut<br>可编辑程序化材质：RK \| 胡桃木 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_10.png) |
| **RK \| Warm pale concrete**<br>RK \| 暖浅色混凝土<br>additional-444547-45-v1/warm-pale-concrete<br>可编辑程序化材质：RK \| 暖浅色混凝土 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene45/manifest.json) · [预览](../../assets/additional-444547/v1/scene45/previews/material_11.png) |
| **RK \| Aged brass**<br>RK \| 仿旧黄铜<br>additional-444547-47-v1/aged-brass<br>可编辑程序化材质：RK \| 仿旧黄铜 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) · [预览](../../assets/additional-444547/v1/scene47/previews/material_01.png) |
| **RK \| Ivory linen**<br>RK \| 象牙色亚麻<br>additional-444547-47-v1/ivory-linen<br>可编辑程序化材质：RK \| 象牙色亚麻 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) · [预览](../../assets/additional-444547/v1/scene47/previews/material_02.png) |
| **RK \| Ivory trim**<br>RK \| 象牙色饰条<br>additional-444547-47-v1/ivory-trim<br>可编辑程序化材质：RK \| 象牙色饰条 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) · [预览](../../assets/additional-444547/v1/scene47/previews/material_03.png) |
| **RK \| Muted landscape artwork**<br>RK \| 柔和风景画<br>additional-444547-47-v1/muted-landscape-artwork<br>可编辑程序化材质：RK \| 柔和风景画 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) · [预览](../../assets/additional-444547/v1/scene47/previews/material_04.png) |
| **RK \| Pale wool carpet**<br>RK \| 浅色羊毛地毯<br>additional-444547-47-v1/pale-wool-carpet<br>可编辑程序化材质：RK \| 浅色羊毛地毯 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) · [预览](../../assets/additional-444547/v1/scene47/previews/material_05.png) |
| **RK \| Soft blue window view**<br>RK \| 柔蓝窗景<br>additional-444547-47-v1/soft-blue-window-view<br>可编辑程序化材质：RK \| 柔蓝窗景 | materials/scene_palette_variants<br>registered | 未记录 | [来源](../../assets/additional-444547/v1/scene47/manifest.json) · [预览](../../assets/additional-444547/v1/scene47/previews/material_06.png) |
| **RK \| Honed ivory stone countertop**<br>RK \| 磨光象牙色石台面<br>roomkit-v1/honed-ivory-stone-countertop<br>可编辑程序化材质：RK \| 磨光象牙色石台面 | materials/stone<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_20.png) |
| **RK \| Soot-dark refractory brick**<br>RK \| 烟灰深色耐火砖<br>roomkit-v1/soot-dark-refractory-brick<br>可编辑程序化材质：RK \| 烟灰深色耐火砖 | materials/stone<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_25.png) |
| **RK \| Warm limestone**<br>RK \| 暖色石灰石<br>roomkit-v1/warm-limestone<br>可编辑程序化材质：RK \| 暖色石灰石 | materials/stone<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_19.png) |
| **RK \| Aged oak mantel**<br>RK \| 仿旧橡木壁炉架<br>roomkit-v1/aged-oak-mantel<br>可编辑程序化材质：RK \| 仿旧橡木壁炉架 | materials/wood<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_06.png) |
| **RK \| Espresso-stained island cabinetry**<br>RK \| 深咖染色岛台柜<br>roomkit-v1/espresso-stained-island-cabinetry<br>可编辑程序化材质：RK \| 深咖染色岛台柜 | materials/wood<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_05.png) |
| **RK \| Honey oak beams**<br>RK \| 蜜色橡木梁<br>roomkit-v1/honey-oak-beams<br>可编辑程序化材质：RK \| 蜜色橡木梁 | materials/wood<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_03.png) |
| **RK \| Natural oak floorboards**<br>RK \| 自然橡木地板<br>roomkit-v1/natural-oak-floorboards<br>可编辑程序化材质：RK \| 自然橡木地板 | materials/wood<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_07.png) |
| **RK \| Pale cut firewood**<br>RK \| 浅色劈柴<br>roomkit-v1/pale-cut-firewood<br>可编辑程序化材质：RK \| 浅色劈柴 | materials/wood<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_26.png) |
| **RK \| Walnut furniture frames**<br>RK \| 胡桃木家具框架<br>roomkit-v1/walnut-furniture-frames<br>可编辑程序化材质：RK \| 胡桃木家具框架 | materials/wood<br>registered | 未记录 | [来源](../../assets/roomkit/v1/manifest.json) · [预览](../../.agents/skills/blender-roomkit/assets/library/previews/material_04.png) |
| **Hinge or slide existing parts**<br>铰接或滑动既有零件<br>utility/roomkit-rig-parts<br>用 Open 属性驱动，围绕物理枢轴分组运动几何。 | utilities/animation<br>callable | 未记录 | [来源](../../src/aha3d/blender/roomkit.py) |
| **Append and place collection**<br>追加并摆放集合<br>utility/roomkit-import-collection<br>追加命名集合，以位置、Z旋转、尺度摆实例。 | utilities/assets<br>callable | 未记录 | [来源](../../src/aha3d/blender/roomkit.py) |

<a id="skills"></a>

## 技能

| 技能 | 范围 | 用法 | 安装 |
| --- | --- | --- | --- |
| [blender-browser-demo](../../.agents/skills/blender-browser-demo/SKILL_zh-CN.md) | 核心 | 将保存的 Blender 场景转独立浏览器演示，含按住抓家具、包围盒移动限制、柜控和已有烘焙网格动画；用于重复场景到网页转换，无需逐场景编辑查看器。 | [设置](../INSTALLATION_zh-CN.md) |
| [blender-roomkit](../../.agents/skills/blender-roomkit/SKILL.md) | 核心 | 从参考构建/改进可编辑 Blender 室内，复用、摆放/替家具材质；用于房间建模、可复用资产和请求的柜/相机动画。 | [设置](../install/blender.md) |
| [gvhmr-body-reconstruction](../../.agents/skills/gvhmr-body-reconstruction/SKILL.md) | 核心 | 用审查跟踪、GVHMR和默认v2重建源人物，优化场景接触、烘焙验证运动到可编辑房间；新动作生成用Kimodo。 | [设置](../install/gvhmr.md) |
| [indoor-scene-workflow](../../.agents/skills/indoor-scene-workflow/SKILL.md) | 核心 | 协调从Pi3X参考到可编辑房间、源人物跟踪/动作、可选相机动画、验证交付；用于完整请求或阶段恢复。 | [设置](../INSTALLATION_zh-CN.md) |
| [kimodo-body-motion](../../.agents/skills/kimodo-body-motion/SKILL.md) | 核心 | Kimodo生成/审查新人体或原生G1动作，含物状态交互、约束子段/场景播放；用于生成、模型调用调试、动作/接触对比，观察人物重建用GVHMR。 | [设置](../install/kimodo_zh-CN.md) |
| [pi3x-scene-reference](../../.agents/skills/pi3x-scene-reference/SKILL.md) | 核心 | 生成Pi3X房间参考、时间戳相机、源色尺寸视图/关联测量；用于鸟瞰/侧参考、近似尺寸、视频/缓存尺度标定。 | [设置](../install/pi3x.md) |
| [sam3d-motion-reference](../../.agents/skills/sam3d-motion-reference/SKILL.md) | 核心 | 用SAM 3D Body和同镜头Pi3X估稀疏体姿、审全身叠加，将已审臂方向/实验腿方向转原生Kimodo约束；用于参考辅助近似手势/动作关键帧。 | [设置](../install/sam3d-body.md) |

<a id="pipeline"></a>

## 流水线

下方阶段来自 `runner.stages()`，实际选择依赖人体模式、渲染类型和 motion-only 范围。

先配置运行时，将通用示例复制到已认领的 `scenes/new_scene`；组装提供自己的房间。所有阶段在本地工作站运行。

```bash
bash tools/indoor plan new_scene --recipe walk
bash tools/indoor run new_scene --recipe walk --motion-only
bash tools/indoor prepare new_scene --recipe walk
bash tools/indoor submit /path/to/prepared-run
bash tools/indoor status --scene new_scene
```

| 阶段 | 用途 | 本地命令 | 设置 |
| --- | --- | --- | --- |
| motion | 生成近似动作与根路径 | `bash tools/indoor execute /path/to/prepared-run --until motion` | [设置](../install/kimodo_zh-CN.md) |
| resample | 保留请求时长并重采样旋转 | `bash tools/indoor execute /path/to/prepared-run --until resample` | [设置](../install/kimodo_zh-CN.md) |
| skin | 导出固定拓扑 SMPL-X 人体网格 | `bash tools/indoor execute /path/to/prepared-run --until skin` | [设置](../install/blender.md) |
| layout_inspection | 渲染/审查匹配源与房间布局证据 | `bash tools/indoor execute /path/to/prepared-run --until layout_inspection` | [设置](../LAYOUT_INSPECTION.md) |
| assemble | 将人体和资产放入可编辑房间副本 | `bash tools/indoor execute /path/to/prepared-run --until assemble` | [设置](../install/blender.md) |
| verify | 检查保存几何与合成投影产物 | `bash tools/indoor execute /path/to/prepared-run --until verify` | [设置](../VALIDATION.md) |
| render | 渲染所选相机/帧范围 | `bash tools/indoor execute /path/to/prepared-run --until render` | [设置](../install/blender.md) |
| video | 编码并完整解码渲染序列 | `bash tools/indoor execute /path/to/prepared-run --until video` | [设置](../VALIDATION.md) |

`execute --until` 也运行未完成前驱；停止阶段必须由配方启用。视觉审查与自动阶段完成独立。

参考适配器：[Pi3X 重建命令](../install/pi3x.md) · [SAM 3D Body 指导命令](../install/sam3d-body.md)

<a id="demos"></a>

## 演示

本包没有注册演示视频；通用配置示例不是生成的场景结果。

## 维护本界面

资产变化先编辑规范元数据并重建 `tools/asset_index.py`。技能名/说明来自各自 frontmatter，阶段名来自源码。

可选演示注册表 `references/unassigned/with_humans/manifest.json` 使用 `{"schema_version":1,"demos":[...]}`。每项需唯一 `id` 和相对包根 `video`；title、description、duration_seconds、poster、provenance 可选，也接受 HTTPS 视频/海报。只注册授权且审查媒体。

运行 `python tools/build_catalog.py build` 再 `python tools/build_catalog.py check`。调用源码模板脚本时用 `--root /path/to/export`。HTML 可从磁盘直接打开，不使用外部脚本、字体/服务。
