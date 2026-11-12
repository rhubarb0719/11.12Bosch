# 博世全嵌十字门冰箱 · 小红书笔记封面

用 `qwen-image-3.0-pro` 生成笔记封面：**家居嵌入实景 + 标题卖点贴纸**。当前阶段只做图片调优。

## 最终封面规则（甲方确认）

| 规则 | 说明 |
|---|---|
| 不另加品牌 logo | 封面上不放 BOSCH 标志等额外品牌图形 |
| 保留产品自身细节 | 冰箱门上原有的铭牌、标识、把手、显示面板与实物一致 |
| 家庭场景 | 冰箱以全嵌入方式出现在家庭厨房里 |
| 硬参数不变形 | 尺寸比例（892×1925mm，宽高比约 1:2.16）、颜色、纹理不能出错 |
| 颜色由产品图决定 | 工作流每次选一个型号的产品图作为图1；prompt 不写颜色词，模型不改颜色 |

## 目录

```
styles/cover-home/      封面版式（玻璃门款）：prompt、随机项、样图记录
content/产品规格.json    8 款型号规格；调优测试款：润玉白 AA21C、岩雾灰 AA31C、星纱硬 AA28C、橱柜门 AR89C
content/examples/       内容示例（标题、副标题、卖点）
assets/                 产品图与家居实景图（不入库，见 assets/README.md）
src/poster/             出图代码（仅 Python 标准库）
docs/开发对接说明.md     工作流接入说明
```

## 用法

```bash
export CR_API_KEY=你的完整密钥 PYTHONPATH=src
```

```bash
python3 -m poster prompt --style cover-home --content content/examples/润玉白_AA21C.json
```

```bash
python3 -m poster generate --style cover-home --content content/examples/润玉白_AA21C.json --count 2 --image assets/products/<正面图> assets/scenes/<家居图>
```

`prompt` 只看拼好的 prompt（不扣费）；`generate` 出图，记录在 `output/<时间>/result.json`。
