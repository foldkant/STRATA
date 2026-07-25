# 霞鹜文楷 Lite 字体来源

- 官方仓库：https://github.com/lxgw/LxgwWenKai-Lite
- 上游项目：https://github.com/lxgw/LxgwWenKai
- 版本：v1.522
- 发布页：https://github.com/lxgw/LxgwWenKai-Lite/releases/tag/v1.522
- 许可证：SIL Open Font License 1.1，详见同目录 `OFL.txt`

本目录中的网页字体由官方发布的 TTF 文件完整转换为 WOFF2，未裁减字符。

`admin-subset/` 中的文件仅用于超级管理员和学校管理员界面。它们根据
`frontend/src` 中实际使用的界面字符生成，并按照 SIL OFL 1.1 的要求将
字体内部名称改为 `STRATA WenKai UI`。动态输入的学校名、姓名等若包含
子集外字符，将回退到系统楷体。可使用
`scripts/build_admin_font_subset.py` 从官方 TTF 重新生成。

| 文件 | 用途 | SHA-256 |
| --- | --- | --- |
| `LXGWWenKaiLite-Regular.woff2` | 常规正文 | `8BCACE4FDF611525F2841D7602A7B2C65F30626FB6CDA116CF12E90C013063B1` |
| `LXGWWenKaiLite-Medium.woff2` | 标题和强调文字 | `C407315F99BCC5BF4736745C5728FA7F8911BB2C559A723AA8BFD9255C00F637` |
| `admin-subset/STRATAWenKaiUI-Regular.woff2` | 管理端常规界面文字 | `D2B8773A354ECB73D543461CADCEC2F6E801F8C9C1BA871AB2C381E70D26249B` |
| `admin-subset/STRATAWenKaiUI-Medium.woff2` | 管理端标题和强调文字 | `B2853A507666EC57B04B3C442716A0B784E10FF3A4290E7B502B8B3D6AB19B86` |

上游 TTF 校验值：

- Regular：`140C99BA4E28E817CEC49BF82A0C5FCDC4FE633FB9DFDA16D0EE8D59A8545F15`
- Medium：`02EB0F8DEED11B00481393F5720630AE1A44424F37F4157EA160A69A1C72A0B6`
