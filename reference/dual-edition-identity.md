# 双版本身份表 · 备份 · 回滚 · 日常维护

参考方案：https://github.com/ZenHG/workbuddy-dual-edition

## 一、两版身份（本机实例，2026-10-31 更新阻断修复后验证）

| 项目 | 国内版 | 国际版 |
|---|---|---|
| 安装目录 | `D:\WorkBuddy` | `D:\Programs\WorkBuddy` |
| 可执行文件 | `WorkBuddy.exe` | `WorkBuddyAI.exe` |
| 进程名 | `WorkBuddy` | `WorkBuddyAI` |
| 数据目录 | `~\.workbuddy` | `~\.workbuddy-ai` |
| 服务端点 | `workbuddy.cn` | 国际端点 |
| 卸载登记 | HKCU `BFD312E9-1019-4F57-9F44-F86246833B50` | HKLM `C02C88CB-5DAE-4330-AEC1-572CFD048A59` |
| 工作区根 | `C:\Users\<user>\WorkBuddy`（系统默认） | `D:\WorkBuddyProjects`（修复后） |
| 版本（修复后） | 5.9.3.42398134 | 各自独立升级 |

## 二、为什么两版更新互不覆盖

1. **就地升级**：更新系统判定安装目录用 `path.dirname(process.execPath)`，国内版只会装回 `D:\WorkBuddy`。
2. **NSIS 按登记回装**：安装器升级模式读取该版自己的卸载登记键（国内版 HKCU / 国际版 HKLM），物理上互不可达。
3. **数据目录隔离**：`~\.workbuddy` vs `~\.workbuddy-ai`，配置、数据库、projects 历史、skills 全部独立。
4. **暂存目录**：两版共用同名暂存目录，但同一次只会有一个版本的安装器在内，下载完即被消费。

> 结论：不需要为「防止互相覆盖」而封锁更新。封锁暂存目录（deny ACL）反而会让正常更新报 EPERM。

## 三、两大阻断根因与修复对照

| 根因 | 机理 | 修复 |
|---|---|---|
| A. install dir guard | 国际版 `defaultWorkspacePath` 指向国内版安装目录 → 每次启动重建 `Claw/` + 时间戳会话目录 → 国内版 guard 只看目录名即拦截 | `fix_workspace_root.py` 迁移工作区根 + `verify_guard.py --clean` 清残留 |
| B. staging ACL deny | 双版本方案的开机守卫（`WorkBuddy-Staging-Guard.cmd` → `block-update-staging.ps1`）给 `%LOCALAPPDATA%\@genieworkbuddy-desktop-updater` 和 `%TEMP%\workbuddy-update-x64` 下 `(DENY)(W,DC)` → 普通权限的 updater 写不进去，下载报 EPERM | `fix_staging_acl.ps1` 移除 deny 并禁用开机守卫 |

注意：以管理员身份运行的更新程序不受用户级 deny 约束——这就是「某版能更新某版不能」的原因，别被表象误导。

## 四、备份与回滚

`fix_workspace_root.py` 默认备份到 `<new-root>-fix-backup-<日期>\`：

| 文件 | 回滚方法 |
|---|---|
| `app-config.json.bak` | 停掉国际版 → 覆盖回 `~\.workbuddy-ai\app\app-config.json` |
| `workbuddy.db.bak` | 停掉国际版 → 覆盖回 `~\.workbuddy-ai\workbuddy.db` |
| `sidebar-list-snapshot.json.bak` / `skills-installed-store.json.bak` | 覆盖回原路径（报告里有原路径） |
| `fix-report.txt` | 含全部改动明细 + projects 目录新旧名对照 |
| projects 目录改名 | 按报告里的对照表改回旧名 |

## 五、日常维护注意

1. **升级后 `startupForceAutoUpdate` 可能回真**：安装器会重写该版 `resources\app.asar.unpacked\cli\product.json`（数据目录 `cache\acc-product-config-v3.json` 同理）。想保持手动更新就重新置 false。
2. **不要把任一版卸载/重装到对方目录**；安装器默认目录是 `%LOCALAPPDATA%\Programs\WorkBuddy`，安装时注意改回各自目录。
3. **改工作区路径必须同步 projects 目录名**（编码算法见 `workspace-path-encoding.md`），否则历史对不上。
4. **恢复暂存封锁**（仅当你刻意想冻结某版更新时）：把 Startup 里的 `WorkBuddy-Staging-Guard.cmd.disabled` 改回 `.cmd`，并重跑 `D:\Programs\WorkBuddy-dual-edition\block-update-staging.ps1`。
5. **体检优先于排查**：更新一出问题先跑 `scripts/diagnose.py`，PASS/FAIL 清单直接指向根因。
