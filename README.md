# workbuddy-dual-edition-fix

WorkBuddy 国内版 / 国际版同机共存时的**更新阻断修复工具包 修复不能共存后不能更新问题**（也可作为 AI Agent 的 Skill 使用）。

配套方案：[ZenHG/workbuddy-dual-edition](https://github.com/ZenHG/workbuddy-dual-edition)

## 解决什么问题

两版客户端同机共存后，国内版点「检查更新」弹窗：

> **无法安装必要的更新** —— 检测到应用安装目录下存在用户项目目录，更新会导致项目记录丢失。

日志里对应 `Update blocked by install dir guard`。排查确认是两个独立根因叠加：

| # | 根因 | 机理 |
|---|---|---|
| A | **工作区根指错** | 国际版 `defaultWorkspacePath` 指向了国内版安装目录，每次启动都在里面重建 `Claw/` 和时间戳会话目录，踩中国内版更新守卫（守卫只看一级目录名，空目录也拦） |
| B | **暂存目录被锁** | 双版本方案的开机守卫给两个更新暂存目录下了 `(DENY)(W,DC)` ACL，正常 updater 下载报 `EPERM` |

本仓库提供：体检 → 修复 → 验证 → 监控更新的完整脚本链，全部幂等可重跑，所有修改先备份。

## 快速开始

```bash
# 0. 体检（只读）：定位两版、复刻官方 guard 判定、查 ACL、查强装开关
python scripts/diagnose.py

# 1. 根因 A：迁移国际版工作区根（先退出国际版全部进程）
python scripts/fix_workspace_root.py --ai-dir "C:\Users\<user>\.workbuddy-ai" \
    --old-root "D:\WorkBuddy" --new-root "D:\WorkBuddyProjects"

# 2. 清掉安装目录里的残留空目录 + 复刻守卫验证
python scripts/verify_guard.py --install-dir "D:\WorkBuddy" --clean --yes

# 3. 根因 B：解除暂存目录封锁（PowerShell，普通用户身份）
powershell -ExecutionPolicy Bypass -File scripts\fix_staging_acl.ps1

# 4. 在国内版点「检查更新」，另开窗口实时监控
python scripts/watch_update.py --data-dir "C:\Users\<user>\.workbuddy" --seconds 180
```

## 目录结构

```
├── SKILL.md                          # Skill 入口（AI Agent 工作流）
├── scripts/
│   ├── diagnose.py                   # 一键体检（只读）
│   ├── fix_workspace_root.py         # 迁移工作区根（配置+数据库+快照+历史目录）
│   ├── fix_staging_acl.ps1           # 解除暂存目录 ACL 封锁
│   ├── verify_guard.py               # 复刻官方 install-dir guard + 清空残留目录
│   └── watch_update.py               # 更新过程实时监控
└── reference/
    ├── install-dir-guard.md          # 守卫白名单与判定逻辑（源码级）
    ├── workspace-path-encoding.md    # projects 历史目录名编码算法
    └── dual-edition-identity.md      # 两版身份表 · 备份 · 回滚 · 维护
```

## 关键结论（踩坑沉淀）

- **install dir guard 判据**：安装目录下有一级子目录且名字（小写）不在 `{bin, locales, resources, tools, log, logs, _, share-target, assets}`、不以 `$`/`nsis` 开头 → 拦截。空目录也拦，只看名字，不递归。
- **`Claw` 不是病毒目录**：是国内版「本地助理」的固定工作目录 = 默认工作区根/Claw。根目录指对地方它就不会出现在安装目录里；删了还会重建是正常的。
- **更新不会互相覆盖**：就地升级 + NSIS 按各自卸载登记（国内版 HKCU / 国际版 HKLM）装回各自目录，数据目录（`.workbuddy` / `.workbuddy-ai`）完全隔离。不需要为防覆盖而封锁更新。
- **管理员权限的更新程序不受用户级 deny ACL 约束**——「一版能更一版不能」多半是这个原因。
- **迁移工作区根必须三处同步**：`app-config.json` → `workbuddy.db`（sessions.cwd / workspaces.path）→ `projects/` 目录名（编码算法见 reference）。脚本已全部覆盖。

## 环境要求

Windows x64 · Python 3.10+（纯标准库）· PowerShell 5.1+

## 回滚

所有修改前自动备份到 `<new-root>-fix-backup-<日期>\`，含 `fix-report.txt` 完整改动明细。回滚 = 停掉对应版本 → `.bak` 覆盖回原文件 → projects 目录名按报告改回。详见 `reference/dual-edition-identity.md`。

## 许可

MIT
