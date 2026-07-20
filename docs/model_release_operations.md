# 模型发布、校验与回滚

## 适用范围

本文用于学校管理员发布班级校准候选、下载离线签名模型包、校验历史版本和回滚。模型只生成教师可见建议，不自动修改学生层级，学生端不接收内部层级、置信度、原因或排名。

## 状态流程

```text
夜间生成候选
  -> 基础比较通过
  -> 无阻塞问题
  -> 模型文件 SHA-256 一致
  -> 学校管理员发布
  -> Ed25519 签名包生成并自校验
  -> 当前版本切换
```

- `candidate`：可以检查和发布，但教师尚不可见对应建议。
- `active`：本学校、本学科、同一测试数据范围内当前使用版本。
- `superseded`：被新版本替换，可校验、下载和回滚。
- `rolled_back`：曾使用但已被回滚操作替换的版本。
- 正式数据和测试数据分别维护版本号与当前版本，不能互相覆盖。

## 首次部署

正式服务器关闭自动生成密钥：

```env
MODEL_SIGNING_AUTO_CREATE=false
MODEL_ARTIFACT_ROOT=storage/models
MODEL_PACKAGE_ROOT=storage/model_packages
MODEL_SIGNING_PRIVATE_KEY_PATH=storage/keys/model_signing_private.pem
MODEL_SIGNING_PUBLIC_KEY_PATH=storage/keys/model_signing_public.pem
```

由部署管理员生成密钥：

```powershell
.\.venv\Scripts\python.exe manage.py setup_model_signing_keys
```

私钥只保存在学校服务器，纳入加密备份，不进入跨校数据包或 Git。公钥需要另存一份受控副本，用于离线验签；更换密钥时保留旧公钥，否则旧模型包无法独立验证。

## 发布操作

学校管理员进入：

```text
/app/school-admin/models
```

1. 核对数据版本、学科、算法、教师候选数量和阻塞提示。
2. 对测试数据候选确认页面显示“测试版本”。
3. 点击“发布候选”。
4. 发布成功后立即点击“校验模型包”。
5. 下载 ZIP，并与数据库备份一起保存。

发布在数据库事务中完成。签名、文件摘要或候选检查任一失败时，不会停用当前版本；失败原因写入不可修改的发布审计记录。

## 离线包结构

```text
manifest.json
signature.ed25519
public_key.pem
model/<模型文件>
```

清单固定学校、学科、数据版本、比较运行、校准运行、算法、模型文件摘要和三条运行规则：教师确认、学生层级隐藏、禁止自动改层。

离线校验：

```powershell
.\.venv\Scripts\python.exe manage.py verify_model_package `
  "D:\backup\model-v2-<package-id>.zip" `
  --public-key "D:\trusted\model_signing_public.pem"
```

必须使用预先保存的可信公钥，不能只信任 ZIP 内自带的公钥。

## 回滚

1. 在发布历史中选择非当前版本。
2. 点击“回滚”。
3. 系统先校验 ZIP 摘要、签名和内部模型文件。
4. 校验通过后才切换当前版本。
5. 回滚后再次执行“校验模型包”，并确认教师页面只显示当前已发布版本的建议。

回滚不重新训练模型，也不删除任何历史版本。模型包丢失、摘要不一致、签名无效或学校/学科不一致时必须停止回滚。

## 故障处理

| 情况 | 处理 |
| --- | --- |
| 候选有阻塞问题 | 保留当前版本，修复数据或重新训练 |
| 模型文件摘要错误 | 禁止发布，检查模型目录和任务日志 |
| 密钥缺失或不匹配 | 禁止发布，不得临时绕过签名 |
| 新版本发布失败 | 核对当前版本仍为 `active`，查看发布审计 |
| ZIP 被修改 | 拒绝导入、发布或回滚，恢复可信备份 |
| 私钥疑似泄露 | 停止发布，轮换密钥并记录受影响版本；旧包用旧公钥单独审计 |

当前模型包用于本校留档、验签和受控迁移。跨学校导入模型不是现有功能，不得把某校模型包直接设为另一学校的当前版本。
