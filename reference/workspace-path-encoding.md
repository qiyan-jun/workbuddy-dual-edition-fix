# 工作区路径编码 —— projects 历史目录命名算法

国际版（`.workbuddy-ai`）的会话历史按工作区路径编码存放在：

```
<data-dir>\projects\<encoded-path>\<session-id>.jsonl
```

编码函数（app.asar 中 `compressWorkspacePathName`，端口实现）：

```js
e.replace(/[/\\:]/g, '-')     // 1. 三种分隔符统一替换为连字符
 .replace(/-+/g, '-')         // 2. 折叠连续连字符
 .replace(/^-+|-+$/g, '')     // 3. 去首尾连字符
// 4. 首字母小写（盘符小写）
```

Python 等价（`fix_workspace_root.py` 中 `encode_workspace_path`）：

```python
def encode_workspace_path(path):
    e = re.sub(r"-+", "-", re.sub(r"^-+|-+$", "", re.sub(r"[/\\:]", "-", path)))
    return e[0].lower() + e[1:] if e else e
```

## 示例

| 工作区路径 | projects 目录名 |
|---|---|
| `D:\WorkBuddyProjects\2026-10-20-11-06-16` | `d-WorkBuddyProjects-2026-10-20-11-06-16` |
| `D:\WorkBuddyProjects\Claw` | `d-WorkBuddyProjects-Claw` |
| `D:\WorkBuddy`（根本身） | `d-WorkBuddy` |
| `C:\Users\七颜\WorkBuddy\2026-10-30-09-00-32` | `c-Users-七颜-WorkBuddy-2026-10-30-09-00-32` |

## 为什么迁移工作区根必须同步改这里

- 数据库（`workbuddy.db` 的 `sessions.cwd` / `workspaces.path`）决定会话属于哪个工作区；
- 历史文件按**编码后的路径**分目录存放；
- 只改数据库不改目录名 → 旧会话历史全部对不上（侧边栏显示空会话）；
- 只改目录名不改数据库 → 新路径找不到目录，会话丢失。

`fix_workspace_root.py` 第 6 步按「旧编码前缀 + 时间戳后缀」整体改名，第 7 步逐一验证每个会话 cwd 都能映射到存在的 projects 目录，两条链路同时保证。

## 国内版（`.workbuddy`）同样机制

国内版 projects 目录在同名路径下（`~\.workbuddy\projects\`），编码算法一致。本方案只迁移国际版时国内版无需任何改动。
