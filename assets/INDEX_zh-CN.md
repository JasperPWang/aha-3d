# 资产索引

[English](INDEX.md)

英文索引由 `python3 tools/asset_index.py build` 生成，不应直接编辑；本文件是对应中文阅读版本。

[搜索与维护说明](README.md) · [完整 JSON 卡片](index.json) · [精选来源](catalog_sources.json)

仅包含注册的可复用库和共享辅助工具，不包括历史场景候选。

- `registered`：版本化库中的条目，通过注册 ID 导入。
- `needs_extraction`：源码候选，分组、依赖和可移植性仍需审查。
- `callable`：现有 Blender 生成器/工具，需要文档规定的运行时。

数量：callable=4，registered=108。

未知候选尺寸保留 null；源坐标不是已验证资产边界。

```text
Assets
├── callable
│   ├── generators
│   │   ├── furniture
│   │   │   └── 可配置可操作柜体 [generator/roomkit-cabinet]
│   │   └── primitives
│   │       └── 倒角盒体 [generator/roomkit-box]
│   └── utilities
│       ├── animation
│       │   └── 铰接或滑动既有零件 [utility/roomkit-rig-parts]
│       └── assets
│           └── 追加并摆放集合 [utility/roomkit-import-collection]
└── registered
    ├── architecture
    │   └── windows
    │       ├── Additional 45 | 休息区窗框 [additional-444547-45-v1/additional-45-lounge-window-frame]
    │       └── Additional 47 | 卧室窗套 [additional-444547-47-v1/additional-47-bedroom-window-casing]
    ├── decor
    │   ├── candles
    │   │   └── Additional 45 | 六支蜡烛组 [additional-444547-45-v1/additional-45-six-candle-group]
    │   ├── curtains
    │   │   └── Additional 47 | 带条带的亚麻窗帘对 [additional-444547-47-v1/additional-47-banded-linen-curtain-pair]
    │   ├── plants
    │   │   ├── RK Flowers - 粉色绣球花盆 [tabletop-plants-v1/flowers-pink-hydrangea-bowl]
    │   │   ├── RK Plant - 阔叶植物陶瓷盆 [plants-v1/plant-broadleaf-ceramic]
    │   │   ├── RK Plant - 紧凑蕨类 [tabletop-plants-v1/plant-compact-fern]
    │   │   └── RK Plant - 自然白掌 [plants-v2/plant-peace-lily-natural]
    │   ├── tabletop
    │   │   └── vases
    │   │       └── RK Vase - 圆润陶瓷花瓶 [ceramic-vase-v1/vase-rounded-ceramic]
    │   ├── tableware
    │   │   ├── Additional 44 | 银色托盘 [additional-444547-44-v1/additional-44-silver-serving-platter]
    │   │   ├── Additional 44 | 风格化高脚器皿 [additional-444547-44-v1/additional-44-stylized-stemmed-vessel]
    │   │   └── Additional 45 | 折叠亚麻餐巾 [additional-444547-45-v1/additional-45-folded-linen-napkin]
    │   ├── vases
    │   │   ├── Additional 45 | 小瓷花瓶 [additional-444547-45-v1/additional-45-small-porcelain-vase]
    │   │   └── Additional 45 | 高瓷花瓶 [additional-444547-45-v1/additional-45-tall-porcelain-vase]
    │   └── wall_art
    │       ├── Additional 44 | 古典花瓶墙板 [additional-444547-44-v1/additional-44-classical-vase-wall-panel]
    │       ├── Additional 45 | 抽象墙板 [additional-444547-45-v1/additional-45-abstract-wall-panel]
    │       ├── Additional 47 | 带框肖像板 [additional-444547-47-v1/additional-47-framed-portrait-panel]
    │       ├── Additional 47 | 风景墙板 [additional-444547-47-v1/additional-47-landscape-wall-panel]
    │       └── Additional 47 | 小画廊墙板 [additional-444547-47-v1/additional-47-small-gallery-panel]
    ├── fixtures
    │   └── plumbing
    │       └── faucets
    │           └── RK Faucet - 简易鹅颈水龙头 [faucet-simple-v1/faucet-simple-gooseneck]
    ├── furniture
    │   ├── beds
    │   │   └── Additional 47 | 四柱床 [additional-444547-47-v1/additional-47-four-poster-bed]
    │   ├── seating
    │   │   ├── chairs
    │   │   │   ├── Additional 44 | 透明聚碳酸酯餐椅 [additional-444547-44-v1/additional-44-clear-polycarbonate-dining-chair]
    │   │   │   ├── Additional 44 | 软包开放框架椅 [additional-444547-44-v1/additional-44-upholstered-open-frame-chair]
    │   │   │   ├── Additional 45 | 人物使用的胡桃木休闲椅 [additional-444547-45-v1/additional-45-occupied-walnut-lounge-chair]
    │   │   │   ├── RK Chair - 带支撑装饰椅 [seating-refined-v1/chair-accent-supported]
    │   │   │   ├── RK Chair - 开放框架餐椅 [dining-chair-v1/chair-open-frame-dining]
    │   │   │   ├── RK Chair - 带支撑胡桃木休闲椅 [seating-refined-v1/chair-walnut-lounge-supported]
    │   │   │   └── RK Chair - 胡桃木休闲椅 [roomkit-v1/chair-walnut-lounge]
    │   │   ├── daybeds
    │   │   │   └── Additional 47 | 低靠背躺椅 [additional-444547-47-v1/additional-47-low-back-chaise]
    │   │   ├── sofas
    │   │   │   ├── Additional 45 | 中央岛式沙发 [additional-444547-45-v1/additional-45-central-island-sofa]
    │   │   │   ├── Additional 45 | 休息区后排沙发 [additional-444547-45-v1/additional-45-lounge-rear-sofa]
    │   │   │   ├── Additional 45 | 主右侧转角模块 [additional-444547-45-v1/additional-45-main-right-return]
    │   │   │   ├── Additional 45 | 主右侧沙发 [additional-444547-45-v1/additional-45-main-right-sofa]
    │   │   │   ├── Additional 45 | 右侧组合沙发 [additional-444547-45-v1/additional-45-right-sectional-assembly]
    │   │   │   └── RK Sofa - 亚麻三人沙发 [roomkit-v1/sofa-linen-three-seat]
    │   │   └── stools
    │   │       └── RK Stool - 软包吧台凳 [roomkit-v1/stool-upholstered-counter]
    │   ├── storage
    │   │   ├── Additional 44 | 六抽屉桃花心木餐边柜 [additional-444547-44-v1/additional-44-six-drawer-mahogany-sideboard]
    │   │   ├── Additional 45 | 工作人员柜台块 [additional-444547-45-v1/additional-45-staff-counter-block]
    │   │   ├── Additional 47 | 六抽屉斗柜 [additional-444547-47-v1/additional-47-six-drawer-dresser]
    │   │   └── cabinets
    │   │       └── RK Cabinet - 混合储物柜 [cabinets-v1/cabinet-mixed-storage]
    │   └── tables
    │       ├── Additional 44 | 正式餐桌 [additional-444547-44-v1/additional-44-formal-dining-table]
    │       ├── Additional 45 | 圆形黄铜边桌 [additional-444547-45-v1/additional-45-round-brass-side-table]
    │       ├── Additional 45 | 方餐桌 [additional-444547-45-v1/additional-45-square-dining-table]
    │       ├── Additional 45 | 宽支撑方餐桌 [additional-444547-45-v1/additional-45-square-dining-table-wide-support]
    │       ├── Additional 47 | 床尾书桌 [additional-444547-47-v1/additional-47-foot-desk]
    │       └── Additional 47 | 胡桃木床头柜 [additional-444547-47-v1/additional-47-walnut-bedside-table]
    ├── lighting
    │   └── fixtures
    │       ├── Additional 44 | 双环吊灯 [additional-444547-44-v1/additional-44-double-ring-chandelier]
    │       ├── Additional 44 | 壁灯 [additional-444547-44-v1/additional-44-wall-sconce]
    │       └── Additional 47 | 黄铜亚麻台灯 [additional-444547-47-v1/additional-47-brass-linen-table-lamp]
    └── materials
        ├── ceramic
        │   ├── RK | 炭灰陶瓷碗 [roomkit-v1/charcoal-ceramic-bowl]
        │   └── RK | 釉面奶油色陶瓷 [roomkit-v1/glazed-cream-ceramic]
        ├── fabric
        │   ├── RK | 炭灰编织软包 [roomkit-v1/charcoal-woven-upholstery]
        │   ├── RK | 奶油色亚麻靠垫 [roomkit-v1/cream-linen-cushions]
        │   ├── RK | 象牙色亚麻沙发 [roomkit-v1/ivory-linen-sofa]
        │   ├── RK | 炭灰边象牙色编织地毯 [roomkit-v1/ivory-woven-rug-with-charcoal-border]
        │   ├── RK | 象牙色亚麻灯罩 [roomkit-v1/lampshade-ivory-linen]
        │   ├── RK | 橄榄棕装饰靠垫 [roomkit-v1/olive-brown-accent-cushions]
        │   ├── RK | 灰褐编织靠垫 [roomkit-v1/taupe-woven-cushions]
        │   └── RK | 暖灰窗帘 [roomkit-v1/warm-grey-drapery]
        ├── metal
        │   ├── RK | 仿旧黄铜把手 [roomkit-v1/aged-brass-handles]
        │   ├── RK | 仿旧青铜鼓形桌体 [roomkit-v1/aged-bronze-table-drums]
        │   ├── RK | 拉丝不锈钢 [roomkit-v1/brushed-stainless-steel]
        │   └── RK | 缎面发黑铁 [roomkit-v1/satin-blackened-iron]
        ├── other
        │   ├── RK | 书页与画作 [roomkit-v1/book-pages-and-artwork]
        │   ├── RK | 深色电视玻璃 [roomkit-v1/dark-television-glass]
        │   ├── RK | 深绿兰花叶 [roomkit-v1/deep-green-orchid-leaves]
        │   ├── RK | 青梨 [roomkit-v1/green-pears]
        │   ├── RK | 象牙色兰花瓣 [roomkit-v1/ivory-orchid-petals]
        │   └── RK | 暖色实景灯泡 [roomkit-v1/warm-practical-bulbs]
        ├── paint_and_plaster
        │   ├── RK | 暖象牙色石灰灰泥 [roomkit-v1/warm-ivory-lime-plaster]
        │   └── RK | 暖白漆木作 [roomkit-v1/warm-white-painted-joinery]
        ├── scene_palette_variants
        │   ├── RK | 仿旧黄铜 [additional-444547-45-v1/aged-brass]
        │   ├── RK | 仿旧黄铜 [additional-444547-47-v1/aged-brass]
        │   ├── RK | 画作颜料 0 [additional-444547-45-v1/artwork-pigment-0]
        │   ├── RK | 画作颜料 1 [additional-444547-45-v1/artwork-pigment-1]
        │   ├── RK | 画作颜料 2 [additional-444547-45-v1/artwork-pigment-2]
        │   ├── RK | 黄铜 [additional-444547-44-v1/brass]
        │   ├── RK | 棕色地板 [additional-444547-44-v1/brown-floor]
        │   ├── RK | 炭灰软包 [additional-444547-44-v1/charcoal-upholstery]
        │   ├── RK | 透明聚碳酸酯 [additional-444547-44-v1/clear-polycarbonate]
        │   ├── RK | 深色青铜 [additional-444547-45-v1/dark-bronze]
        │   ├── RK | 深色石材 [additional-444547-44-v1/dark-stone]
        │   ├── RK | 近似玻璃 [additional-444547-44-v1/glass-approximation]
        │   ├── RK | 磨光石灰石 [additional-444547-45-v1/honed-limestone]
        │   ├── RK | 象牙色亚麻 [additional-444547-47-v1/ivory-linen]
        │   ├── RK | 象牙色饰条 [additional-444547-47-v1/ivory-trim]
        │   ├── RK | 桃花心木餐边柜 [additional-444547-44-v1/mahogany-sideboard]
        │   ├── RK | 柔和风景画 [additional-444547-47-v1/muted-landscape-artwork]
        │   ├── RK | 海军蓝软包 [additional-444547-45-v1/navy-upholstery]
        │   ├── RK | 浅色羊毛地毯 [additional-444547-47-v1/pale-wool-carpet]
        │   ├── RK | 浅色编织亚麻 [additional-444547-45-v1/pale-woven-linen]
        │   ├── RK | 图像墨色 [additional-444547-44-v1/picture-ink]
        │   ├── RK | 瓷器 [additional-444547-45-v1/porcelain]
        │   ├── RK | 银色托盘 [additional-444547-44-v1/silver-platter]
        │   ├── RK | 柔蓝窗景 [additional-444547-47-v1/soft-blue-window-view]
        │   ├── RK | 胡桃木 [additional-444547-45-v1/walnut]
        │   ├── RK | 暖灰墙漆 [additional-444547-44-v1/warm-grey-wall-paint]
        │   ├── RK | 暖浅色混凝土 [additional-444547-45-v1/warm-pale-concrete]
        │   └── RK | 暖白 [additional-444547-44-v1/warm-white]
        ├── stone
        │   ├── RK | 磨光象牙色石台面 [roomkit-v1/honed-ivory-stone-countertop]
        │   ├── RK | 烟灰深色耐火砖 [roomkit-v1/soot-dark-refractory-brick]
        │   └── RK | 暖色石灰石 [roomkit-v1/warm-limestone]
        └── wood
            ├── RK | 仿旧橡木壁炉架 [roomkit-v1/aged-oak-mantel]
            ├── RK | 深咖染色岛台柜 [roomkit-v1/espresso-stained-island-cabinetry]
            ├── RK | 蜜色橡木梁 [roomkit-v1/honey-oak-beams]
            ├── RK | 自然橡木地板 [roomkit-v1/natural-oak-floorboards]
            ├── RK | 浅色劈柴 [roomkit-v1/pale-cut-firewood]
            └── RK | 胡桃木家具框架 [roomkit-v1/walnut-furniture-frames]
```

## 来源卡片

| ID | 描述 | 来源 |
| --- | --- | --- |
| `additional-444547-44-v1/additional-44-classical-vase-wall-panel` | 两个重复浅浮雕之一；画作是可编辑几何，不是源图。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/8](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/additional-44-clear-polycarbonate-dining-chair` | 源制作透射材质和六独立零件，便携支撑连接单独审查。源派生近似静态资产，无真实人物数据；见 provenance.json。便携副本延靠背下板与座重叠10mm，消除原17.5mm无支撑间隙，保顶部高/透射材质。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/1](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/additional-44-double-ring-chandelier` | 可编辑双环黄铜吊灯代理，六源外立杆，制作斜悬链/径向杆把两环接中心杆/顶盘。原点顶盘安装面中心。新增支撑是便携副本补全，不是源观察细节/结构认证，无光度灯源。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/7](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/additional-44-formal-dining-table` | 源特定桌面/四腿，无餐具。源派生静态近似，无真实人物数据；见 provenance.json。便携副本腿顶伸入桌底5mm，修原2.5mm支撑隙。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/3](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/additional-44-silver-serving-platter` | 用连续盛放面、凹槽、卷边和支脚替重叠厚圆盘/环。保外径308mm、总高18mm和银材质。源派生或制作近似，无物理认证。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/0](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/additional-44-six-drawer-mahogany-sideboard` | 静态六抽屉立面和把手，无可用抽屉/隐藏柜内。源派生静态近似，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/4](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/additional-44-stylized-stemmed-vessel` | 三个相交24边实体代理改连续128边器壳，制作开口杯、2.4mm直壁、封底、软边、连续柄底连接。源派生或制作近似，无物理认证。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/5](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/additional-44-upholstered-open-frame-chair` | 由 dining-chair-v1/chair-open-frame-dining 改静态软包开放餐椅。藤编/板条换为原支撑背框范围内炭灰垫，接触重叠2mm。仅便携副本替源未旋转浮空叠层，原场景不变。独立可编辑网格，源尺度未校准。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/2](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/additional-44-wall-sconce` | 实心灯罩替2mm上下开口矩形壳；加内部安装支撑、灯座、磨砂泡，保墙板、安装原点/外范围。 | [assets/additional-444547/v1/scene44/manifest.json/furniture/6](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/brass` | 可编辑程序化材质：RK \| 黄铜 | [assets/additional-444547/v1/scene44/manifest.json/materials/0](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/brown-floor` | 可编辑程序化材质：RK \| 棕色地板 | [assets/additional-444547/v1/scene44/manifest.json/materials/1](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/charcoal-upholstery` | 可编辑程序化材质：RK \| 炭灰软包 | [assets/additional-444547/v1/scene44/manifest.json/materials/2](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/clear-polycarbonate` | 可编辑程序化材质：RK \| 透明聚碳酸酯 | [assets/additional-444547/v1/scene44/manifest.json/materials/3](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/dark-stone` | 可编辑程序化材质：RK \| 深色石材 | [assets/additional-444547/v1/scene44/manifest.json/materials/4](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/glass-approximation` | 可编辑程序化材质：RK \| 近似玻璃 | [assets/additional-444547/v1/scene44/manifest.json/materials/5](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/mahogany-sideboard` | 可编辑程序化材质：RK \| 桃花心木餐边柜 | [assets/additional-444547/v1/scene44/manifest.json/materials/6](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/picture-ink` | 可编辑程序化材质：RK \| 图像墨色 | [assets/additional-444547/v1/scene44/manifest.json/materials/7](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/silver-platter` | 可编辑程序化材质：RK \| 银色托盘 | [assets/additional-444547/v1/scene44/manifest.json/materials/8](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/warm-grey-wall-paint` | 可编辑程序化材质：RK \| 暖灰墙漆 | [assets/additional-444547/v1/scene44/manifest.json/materials/9](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-44-v1/warm-white` | 可编辑程序化材质：RK \| 暖白 | [assets/additional-444547/v1/scene44/manifest.json/materials/10](../assets/additional-444547/v1/scene44/manifest.json) |
| `additional-444547-45-v1/additional-45-abstract-wall-panel` | 可编辑浅层几何颜料板，无参考图片纹理。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/12](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-central-island-sofa` | 独立可编辑底座、平台、软包和枕；源特定近似尺寸。源派生静态近似，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/3](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-folded-linen-napkin` | 厚盒替为四贴合亚麻层、卷边/细微起伏，保桌面占地/支撑。静态折布几何，无布求解器/模拟声明。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/11](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-lounge-rear-sofa` | 独立可编辑底座、平台、软包和枕；源特定近似尺寸。源派生静态近似，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/0](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-lounge-window-frame` | 源中独立开口饰框组件；不含玻璃、铰链、墙或室外景。安装原点在包围中心。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/15](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-main-right-return` | 独立可编辑底座、平台、软包和枕；源特定近似尺寸。源派生静态近似，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/2](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-main-right-sofa` | 独立可编辑底座、平台、软包和枕；源特定近似尺寸。源派生静态近似，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/1](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-occupied-walnut-lounge-chair` | 改 roomkit-v1/chair-walnut-lounge：均匀.62尺度上宽x1.15，垫+.012m，去腰枕，尺度烘焙可编辑网格。源派生近似静态，无真实人物数据；见 provenance.json。原范围内加两胡桃木后支撑板。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/8](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-right-sectional-assembly` | 用source45主/转角沙发制作可拆模块L对。保独立平台、底、座、背、枕、扶手，以外背/15mm连接净距替源角重叠。便携布局是制作适配，不是连续软包转角。源近似尺寸，无校准尺度声明。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/4](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-round-brass-side-table` | 五重复边桌之一，花瓶另导。源派生静态近似，无真实人物数据；见 provenance.json。便携副本柱顶伸入桌面5mm，修原2.5mm支撑隙。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/5](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-six-candle-group` | 用圆蜡体、凹蜡顶和六根棉芯替换实心蜡烛块。六底均置于组支撑面，保各高度和整体范围；材质改蜡/芯而非亚麻软包。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/13](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-small-porcelain-vase` | 带盖实心瓷柱重建为128径向分段的封闭空心器，保测得圆外轮廓/陶瓷，径向壁3mm、底7mm。源派生或制作近似，无物理认证。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/10](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-square-dining-table` | 默认方桌面，六重复未适配摆放之一。源派生静态近似，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/6](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-square-dining-table-wide-support` | 宽支撑变体用源最终腿偏移±0.46m。源派生静态近似，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/7](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-staff-counter-block` | 最小独立柜台块代理，无隐藏服务配件/可操作门。源派生静态近似，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/14](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/additional-45-tall-porcelain-vase` | 带盖实心瓷柱重建为128径向分段的封闭空心器，保测得圆外轮廓/陶瓷，径向壁4mm、底7mm。源派生或制作近似，无物理认证。 | [assets/additional-444547/v1/scene45/manifest.json/furniture/9](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/aged-brass` | 可编辑程序化材质：RK \| 仿旧黄铜 | [assets/additional-444547/v1/scene45/manifest.json/materials/0](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/artwork-pigment-0` | 可编辑程序化材质：RK \| 画作颜料 0 | [assets/additional-444547/v1/scene45/manifest.json/materials/1](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/artwork-pigment-1` | 可编辑程序化材质：RK \| 画作颜料 1 | [assets/additional-444547/v1/scene45/manifest.json/materials/2](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/artwork-pigment-2` | 可编辑程序化材质：RK \| 画作颜料 2 | [assets/additional-444547/v1/scene45/manifest.json/materials/3](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/dark-bronze` | 可编辑程序化材质：RK \| 深色青铜 | [assets/additional-444547/v1/scene45/manifest.json/materials/4](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/honed-limestone` | 可编辑程序化材质：RK \| 磨光石灰石 | [assets/additional-444547/v1/scene45/manifest.json/materials/5](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/navy-upholstery` | 可编辑程序化材质：RK \| 海军蓝软包 | [assets/additional-444547/v1/scene45/manifest.json/materials/6](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/pale-woven-linen` | 可编辑程序化材质：RK \| 浅色编织亚麻 | [assets/additional-444547/v1/scene45/manifest.json/materials/7](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/porcelain` | 可编辑程序化材质：RK \| 瓷器 | [assets/additional-444547/v1/scene45/manifest.json/materials/8](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/walnut` | 可编辑程序化材质：RK \| 胡桃木 | [assets/additional-444547/v1/scene45/manifest.json/materials/9](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-45-v1/warm-pale-concrete` | 可编辑程序化材质：RK \| 暖浅色混凝土 | [assets/additional-444547/v1/scene45/manifest.json/materials/10](../assets/additional-444547/v1/scene45/manifest.json) |
| `additional-444547-47-v1/additional-47-banded-linen-curtain-pair` | 用薄褶亚麻面与原生网格厚度替换两块 100 mm 实心板。每帘四灰褐条带作为布上材质区域，去独立条带盒。顶部布聚到杆接触，保安装原点、杆与下摆高度。静态制作褶皱，未验证布模拟。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/10](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-bedroom-window-casing` | 两个重复分格窗框之一，蓝色景观卡作为场景背景省略。原点归一到组件安装中心。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/9](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-brass-linen-table-lamp` | 灯罩重建1.6mm开口锥壳，可见内壁/边环；加三黄铜内支撑/磨砂泡，保灯高、底、杆/材质外观。无光度标定。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/5](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-foot-desk` | 源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/1](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-four-poster-bed` | 源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/0](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-framed-portrait-panel` | 源特定静态可编辑近似，尺寸为制作值非校准测量。源名 mirror 仅哑光框板，无反射玻璃。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/6](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-landscape-wall-panel` | 源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/8](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-low-back-chaise` | 源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/3](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-six-drawer-dresser` | 源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/2](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-small-gallery-panel` | 源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/7](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/additional-47-walnut-bedside-table` | 源特定静态可编辑近似，尺寸为制作值非校准测量。源派生近似静态资产，无真实人物数据；见 provenance.json。 | [assets/additional-444547/v1/scene47/manifest.json/furniture/4](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/aged-brass` | 可编辑程序化材质：RK \| 仿旧黄铜 | [assets/additional-444547/v1/scene47/manifest.json/materials/0](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/ivory-linen` | 可编辑程序化材质：RK \| 象牙色亚麻 | [assets/additional-444547/v1/scene47/manifest.json/materials/1](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/ivory-trim` | 可编辑程序化材质：RK \| 象牙色饰条 | [assets/additional-444547/v1/scene47/manifest.json/materials/2](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/muted-landscape-artwork` | 可编辑程序化材质：RK \| 柔和风景画 | [assets/additional-444547/v1/scene47/manifest.json/materials/3](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/pale-wool-carpet` | 可编辑程序化材质：RK \| 浅色羊毛地毯 | [assets/additional-444547/v1/scene47/manifest.json/materials/4](../assets/additional-444547/v1/scene47/manifest.json) |
| `additional-444547-47-v1/soft-blue-window-view` | 可编辑程序化材质：RK \| 柔蓝窗景 | [assets/additional-444547/v1/scene47/manifest.json/materials/5](../assets/additional-444547/v1/scene47/manifest.json) |
| `cabinets-v1/cabinet-mixed-storage` | 可编辑柜，独立原生门/抽屉控制。 | [assets/cabinets/v1/manifest.json/furniture/0](../assets/cabinets/v1/manifest.json) |
| `ceramic-vase-v1/vase-rounded-ceramic` | 平滑原外地标、不超半径，浅内颈延为全深腔。封缺底，圆唇/14mm底连接内外壳。源派生或制作近似，无物理认证。 | [assets/scene-extracted/v1/vase/manifest.json/furniture/0](../assets/scene-extracted/v1/vase/manifest.json) |
| `dining-chair-v1/chair-open-frame-dining` | 现有源特定扶手餐椅、简化板条背，已归一复用。 | [assets/scene-extracted/v1/chair/manifest.json/furniture/0](../assets/scene-extracted/v1/chair/manifest.json) |
| `faucet-simple-v1/faucet-simple-gooseneck` | 给原开放单面管加1.2mm向内壁和环形端边，出口/安装端保持开口。以拉丝不锈钢替提取灰模，保原中心线/安装原点。无阀、内部流动或管道模拟。 | [assets/fixtures/v1/simple_faucet/manifest.json/furniture/0](../assets/fixtures/v1/simple_faucet/manifest.json) |
| `generator/roomkit-box` | 盒体生成器：显式尺寸、材质、目标集合和边半径。 | [src/aha3d/blender/roomkit.py:18](../src/aha3d/blender/roomkit.py) |
| `generator/roomkit-cabinet` | 可操作柜生成器：显式布局支持加权列/段、可变抽屉数/高、单/双门、搁板/内分隔。省布局保原两门一抽屉接口。 | [src/aha3d/blender/roomkit.py:362](../src/aha3d/blender/roomkit.py) |
| `plants-v1/plant-broadleaf-ceramic` | 保叶、基质和盆位置，沿测量地标平滑原盆剖面。48边盆改128边封闭器，完整内腔、径向壁8mm/底16mm。源派生或制作近似，无物理认证。 | [assets/plants/v1/manifest.json/furniture/0](../assets/plants/v1/manifest.json) |
| `plants-v2/plant-peace-lily-natural` | 保叶、基质和盆位置，沿测量地标平滑原盆剖面。48边盆改128边封闭器，完整内腔、径向壁8mm/底16mm。源派生或制作近似，无物理认证。 | [assets/plants/v2/manifest.json/furniture/0](../assets/plants/v2/manifest.json) |
| `roomkit-v1/aged-brass-handles` | 可编辑程序化材质：RK \| 仿旧黄铜把手 | [assets/roomkit/v1/manifest.json/materials/16](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/aged-bronze-table-drums` | 可编辑程序化材质：RK \| 仿旧青铜鼓形桌体 | [assets/roomkit/v1/manifest.json/materials/14](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/aged-oak-mantel` | 可编辑程序化材质：RK \| 仿旧橡木壁炉架 | [assets/roomkit/v1/manifest.json/materials/5](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/book-pages-and-artwork` | 可编辑程序化材质：RK \| 书页与画作 | [assets/roomkit/v1/manifest.json/materials/30](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/brushed-stainless-steel` | 可编辑程序化材质：RK \| 拉丝不锈钢 | [assets/roomkit/v1/manifest.json/materials/17](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/chair-walnut-lounge` | 胡桃木软包座/背休闲椅，独立可编辑零件，正面局部-Y。原范围内加两后支板，腰枕/滚边降18mm使座支撑接触。修封闭网格 Lounge chair A lumbar pillow.001 内向法线，保顶点、UV、材质图。 | [assets/roomkit/v1/manifest.json/furniture/1](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/charcoal-ceramic-bowl` | 可编辑程序化材质：RK \| 炭灰陶瓷碗 | [assets/roomkit/v1/manifest.json/materials/21](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/charcoal-woven-upholstery` | 可编辑程序化材质：RK \| 炭灰编织软包 | [assets/roomkit/v1/manifest.json/materials/11](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/cream-linen-cushions` | 可编辑程序化材质：RK \| 奶油色亚麻靠垫 | [assets/roomkit/v1/manifest.json/materials/8](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/dark-television-glass` | 可编辑程序化材质：RK \| 深色电视玻璃 | [assets/roomkit/v1/manifest.json/materials/26](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/deep-green-orchid-leaves` | 可编辑程序化材质：RK \| 深绿兰花叶 | [assets/roomkit/v1/manifest.json/materials/22](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/espresso-stained-island-cabinetry` | 可编辑程序化材质：RK \| 深咖染色岛台柜 | [assets/roomkit/v1/manifest.json/materials/4](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/glazed-cream-ceramic` | 可编辑程序化材质：RK \| 釉面奶油色陶瓷 | [assets/roomkit/v1/manifest.json/materials/20](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/green-pears` | 可编辑程序化材质：RK \| 青梨 | [assets/roomkit/v1/manifest.json/materials/27](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/honed-ivory-stone-countertop` | 可编辑程序化材质：RK \| 磨光象牙色石台面 | [assets/roomkit/v1/manifest.json/materials/19](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/honey-oak-beams` | 可编辑程序化材质：RK \| 蜜色橡木梁 | [assets/roomkit/v1/manifest.json/materials/2](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/ivory-linen-sofa` | 可编辑程序化材质：RK \| 象牙色亚麻沙发 | [assets/roomkit/v1/manifest.json/materials/7](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/ivory-orchid-petals` | 可编辑程序化材质：RK \| 象牙色兰花瓣 | [assets/roomkit/v1/manifest.json/materials/23](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/ivory-woven-rug-with-charcoal-border` | 可编辑程序化材质：RK \| 炭灰边象牙色编织地毯 | [assets/roomkit/v1/manifest.json/materials/13](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/lampshade-ivory-linen` | 可编辑程序化材质：RK \| 象牙色亚麻灯罩 | [assets/roomkit/v1/manifest.json/materials/28](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/natural-oak-floorboards` | 可编辑程序化材质：RK \| 自然橡木地板 | [assets/roomkit/v1/manifest.json/materials/6](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/olive-brown-accent-cushions` | 可编辑程序化材质：RK \| 橄榄棕装饰靠垫 | [assets/roomkit/v1/manifest.json/materials/10](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/pale-cut-firewood` | 可编辑程序化材质：RK \| 浅色劈柴 | [assets/roomkit/v1/manifest.json/materials/25](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/satin-blackened-iron` | 可编辑程序化材质：RK \| 缎面发黑铁 | [assets/roomkit/v1/manifest.json/materials/15](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/sofa-linen-three-seat` | 三人亚麻沙发，独立座/背/装饰垫，地板中心摆放，朝向局部 -Y 轴。修正 Sofa A \| below tall windows loose pillow 0.001、1.001、2.001、3.001 封闭网格的内向法线，保留顶点、UV 和材质贴图。 | [assets/roomkit/v1/manifest.json/furniture/0](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/soot-dark-refractory-brick` | 可编辑程序化材质：RK \| 烟灰深色耐火砖 | [assets/roomkit/v1/manifest.json/materials/24](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/stool-upholstered-counter` | 胡桃木框/脚踏厨房软包吧台凳，中性静态姿态，前局部-Y。 | [assets/roomkit/v1/manifest.json/furniture/2](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/taupe-woven-cushions` | 可编辑程序化材质：RK \| 灰褐编织靠垫 | [assets/roomkit/v1/manifest.json/materials/9](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/walnut-furniture-frames` | 可编辑程序化材质：RK \| 胡桃木家具框架 | [assets/roomkit/v1/manifest.json/materials/3](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/warm-grey-drapery` | 可编辑程序化材质：RK \| 暖灰窗帘 | [assets/roomkit/v1/manifest.json/materials/12](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/warm-ivory-lime-plaster` | 可编辑程序化材质：RK \| 暖象牙色石灰灰泥 | [assets/roomkit/v1/manifest.json/materials/0](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/warm-limestone` | 可编辑程序化材质：RK \| 暖色石灰石 | [assets/roomkit/v1/manifest.json/materials/18](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/warm-practical-bulbs` | 可编辑程序化材质：RK \| 暖色实景灯泡 | [assets/roomkit/v1/manifest.json/materials/29](../assets/roomkit/v1/manifest.json) |
| `roomkit-v1/warm-white-painted-joinery` | 可编辑程序化材质：RK \| 暖白漆木作 | [assets/roomkit/v1/manifest.json/materials/1](../assets/roomkit/v1/manifest.json) |
| `seating-refined-v1/chair-accent-supported` | 原倒角背/座仅相切；保顶部/占地，增加重叠和连续内部后立柱。 | [assets/seating/refined_v1/manifest.json/furniture/1](../assets/seating/refined_v1/manifest.json) |
| `seating-refined-v1/chair-walnut-lounge-supported` | 原背有扶手支撑，加后横杆到垫直接支撑，闭合测得6.59132mm腰枕到座间隙。修 Lounge chair A lumbar pillow.001 内向法线，保顶点、UV、材质图。 | [assets/seating/refined_v1/manifest.json/furniture/0](../assets/seating/refined_v1/manifest.json) |
| `tabletop-plants-v1/flowers-pink-hydrangea-bowl` | 焊接容器/基质网格重复轴极点，关闭假边界环并恢复有效实体拓扑。保肋碗/盆形、全部叶、材质和几何位置。源派生或制作近似，无物理认证。 | [assets/plants/tabletop_v1/manifest.json/furniture/1](../assets/plants/tabletop_v1/manifest.json) |
| `tabletop-plants-v1/plant-compact-fern` | 焊接容器/基质网格重复轴极点，关闭假边界环并恢复有效实体拓扑。保肋碗/盆形、全部叶、材质和几何位置。源派生或制作近似，无物理认证。 | [assets/plants/tabletop_v1/manifest.json/furniture/0](../assets/plants/tabletop_v1/manifest.json) |
| `utility/roomkit-import-collection` | 追加命名集合，以位置、Z旋转、尺度摆实例。 | [src/aha3d/blender/roomkit.py:46](../src/aha3d/blender/roomkit.py) |
| `utility/roomkit-rig-parts` | 用 Open 属性驱动，围绕物理枢轴分组运动几何。 | [src/aha3d/blender/roomkit.py:133](../src/aha3d/blender/roomkit.py) |
