---
name: workbuddy-dual-edition-fix
version: 1.0.0
description: 修复 WorkBuddy 国内版与国际版同机共存时的更新阻断问题。当用户安装了国内版（WorkBuddy.exe）和国际版（WorkBuddyAI.exe）两个版本、国内版点击「检查更新」弹窗「无法安装必要的更新 / 检测到应用安装目录下存在用户项目目录」、或更新下载报 EPERM 时使用。覆盖两大根因：① install dir guard（国际版工作区根目录指向国内版安装目录，启动时重建 Claw/时间戳目录踩中守卫）；② 更新暂存目录被 deny ACL 封锁（EPERM）。提供 diagnose → fix → verify → update 全流程脚本。
---

# WorkBuddy 双版本共存更新修复

修复 ZenHG/workbuddy-dual-edition 方案下国内版更新被阻断的问题。两大根因、四步流程、全部脚本可重复执行、所有修改可回滚。

## 适用症状（命中任一即用本 skill）

| 症状 | 根因 | 修复脚本 |
|---|---|---|
| 国内版点「检查更新」弹窗「无法安装必要的更新：检测到应用安装目录下存在用户项目目录」，日志有 `Update blocked by install dir guard` | 安装目录下有一级子目录不在白名单 | `fix_workspace_root.py` + 删阻断目录 |
| 国际版每次启动都在国内版安装目录里重建 `Claw` / 时间戳会话目录 | 国际版 `defaultWorkspacePath` 指向了国内版安装目录 | `fix_workspace_root.py` |
| 更新检查通过但下载报 `EPERM: operation not permitted, open '...\Temp\workbuddy-update-x64\...tmp'` | 暂存目录被 deny ACL 封锁 | `fix_staging_acl.ps1` |
| 两版互相覆盖 / 快捷方式指向混乱 / 启动即静默强装 | 初装冲突，`startupForceAutoUpdate` 未关 | 见 `reference/dual-edition-identity.md` |

## 第一步：体检（只读，不改任何文件）

```bash
python scripts/diagnose.py
```

自动完成：定位两版安装目录与数据目录、复刻官方 install-dir guard 判定安装目录是否违规、检查国际版 `defaultWorkspacePath` 是否落在国内版安装目录内、检查两个暂存目录 ACL 是否有 deny、检查 `startupForceAutoUpdate` 状态。输出 PASS/FAIL 清单。

## 第二步：按体检结果修复

### 根因 A：工作区根目录指错（最常见）

**先退出国际版全部进程**（`tasklist | findstr WorkBuddyAI` 应为空），否则数据库被占用：

```bash
# --ai-dir 国际版数据目录 --old-root 当前（错误）工作区根 --new-root 目标工作区根
python scripts/fix_workspace_root.py --ai-dir "C:\Users\<user>\.workbuddy-ai" \
    --old-root "D:\WorkBuddy" --new-root "D:\WorkBuddyProjects"
```

脚本自动完成（每步先备份到 `--backup-dir`，默认 `<new-root>-fix-backup-<日期>`）：

1. `app-config.json` 的 `defaultWorkspacePath` 改写
2. `workbuddy.db` 中 `sessions.cwd` / `workspaces.path` 全量路径重写（扫所有表所有字符串列）
3. `sidebar-list-snapshot.json` 侧边栏快照重写
4. `skills-installed-store.json` 技能安装记录重写
5. `projects/` 下历史会话目录按官方编码算法改名（旧根 → 新根），保证旧会话历史不丢失
6. 验证：每个会话 cwd 都能映射到存在的 projects 目录

幂等：已修过再跑会跳过，不会二次破坏。

### 根因 B：暂存目录 ACL 封锁

**以当前用户身份**运行（PowerShell）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\fix_staging_acl.ps1
```

移除 `%LOCALAPPDATA%\@genieworkbuddy-desktop-updater` 和 `%TEMP%\workbuddy-update-x64` 下当前用户的 `(DENY)(W,DC)` ACL，并禁用开机守卫（重命名为 `.cmd.disabled`，不删除，可随时改回恢复防护）。

> 何时需要恢复防护：只想让某版永远不自动更新时。日常双版本各更各的，不需要封锁——两版安装目录、数据目录、卸载登记完全隔离，更新互不影响（见下）。

## 第三步：删除阻断目录 + 复刻守卫验证

```bash
python scripts/verify_guard.py --install-dir "D:\WorkBuddy" --clean
```

`--clean` 只删除**空目录**（非空会拒绝并退出），随后复刻官方 `hasUserContentInInstallDir()` 逻辑逐项判定，输出 GUARD RESULT: PASS 才继续。

## 第四步：验证更新

1. 启动国内版 → 点「检查更新」
2. 实时盯日志（用户点击后监控，弹窗/报错一目了然）：

```bash
python scripts/watch_update.py --data-dir "C:\Users\<user>\.workbuddy" --seconds 180
```

监控项：`Update blocked by install dir guard` 出现次数、`State changed` 状态机流转、下载进度、暂存目录文件大小、安装目录是否被写入非白名单目录。

3. 升级完成后确认：`last-launch.json` / `AppStartup.log` 里的 `appVersion` 为新版本；国际版 exe 文件时间戳未变（未被覆盖）。

## 更新会不会覆盖另一版？——不会

应用内更新是就地升级，装回 `path.dirname(process.execPath)`，NSIS 安装器按该版自己的卸载登记（国内版在 HKCU，国际版在 HKLM）装回各自目录。国内版安装器物理上够不到国际版目录。唯一注意事项：升级后安装器会重写该版 `resources\app.asar.unpacked\cli\product.json`，`startupForceAutoUpdate` 可能回真——如需要按 `reference/dual-edition-identity.md` 重新置 false（数据目录 `cache\acc-product-config-v3.json` 同理）。

## 关键机制速查

- **install dir guard 判据**：安装目录下存在任何一级子目录且名字（转小写）不在白名单 `{bin, locales, resources, tools, log, logs, _, share-target, assets}` 内、也不以 `$`/`nsis` 开头 → 拦截。空目录也拦，只看名字不看内容，不递归。
- **Claw 目录**：国内版「本地助理」固定工作目录 = 默认工作区根/Claw，根目录由 `defaultWorkspacePath` 决定（系统默认 `~/WorkBuddy`）。根目录指对地方，它就不会出现在安装目录里。
- **projects 历史目录名编码**：`replace(/[/\\:]/g,'-')` → 折叠连续连字符 → 去首尾连字符 → 首字母小写。例：`D:\WorkBuddyProjects\2026-10-20-11-06-16` → `d-WorkBuddyProjects-2026-10-20-11-06-16`。改工作区根必须同步改这里，否则历史会话对不上。

详见 `reference/` 下三份文档：`install-dir-guard.md`（守卫源码级逻辑）、`workspace-path-encoding.md`（编码算法）、`dual-edition-identity.md`（两版身份表 + 备份 + 回滚）。

## 回滚

所有修改前自动备份到 `--backup-dir`：`app-config.json.bak`、`workbuddy.db.bak`、`sidebar-list-snapshot.json.bak`、`skills-installed-store.json.bak`、`fix-report.txt`。回滚 = 停掉对应版本 → 把 `.bak` 覆盖回原文件 → 把 projects 目录名改回旧编码（脚本报告里有完整新旧名对照）。

## 环境要求

- Windows x64、Python 3.10+（仅标准库 + sqlite3）
- PowerShell 5.1+（ACL 脚本）
- 操作国际版配置前必须先退出国际版全部进程；操作国内版更新时两版可同时运行
