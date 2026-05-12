训练好的 LoRA 放这里。

- 权重文件（`.safetensors` / `.bin` / `.pt` / `.ckpt`）被 gitignore（单个几十-几百 MB，太大）
- 同名 `.json` / `.yaml` 配置文件**会**进 git，方便记录训练参数 / 数据来源

约定命名：`<风格名>-v1.safetensors` + `<风格名>-v1.json`

`.json` 里写：
- 数据集（哪些歌、多少首）
- 训练步数、学习率
- 主要风格 tag
- 用法说明（推荐叠加的 prompt）
