# install dir guard —— 守卫逻辑（源码级）

来源：`resources/app.asar` 中 `UpdateServiceWin32` 反混淆代码。国内版与国际版同源。

## 判定函数

```js
// 硬编码白名单（全部小写）
var i = new Set([
  `bin`, `locales`, `resources`, `tools`, `log`, `logs`,
  `_`, `share-target`, `assets`
]);

function isKnownAppDirectory(e) {
  let t = e.toLowerCase();
  return !!(i.has(t) || t.startsWith(`$`) || t.startsWith(`nsis`));
}

function getInstallDir() {
  if (process.platform === `win32`)
    try { return path.dirname(process.execPath); } catch { return; }
}

function hasUserContentInInstallDir() {
  let e = getInstallDir();
  if (!e) return false;
  try {
    // 只读一级子目录，只看名字，不看内容
    return fs.readdirSync(e, { withFileTypes: true })
      .some(dirent => dirent.isDirectory() && !isKnownAppDirectory(dirent.name));
  } catch { return false; }
}
```

## 调用链

```js
async checkForUpdates(e = false) {
  if (this.checkInProgress) { return; }
  this.checkInProgress = true;
  try {
    this.setLastExplicit(e);
    if (await this.checkInstallDirGuard(e)) return;   // ← 命中即 return，不下载不安装
    ...
  }
}

async checkInstallDirGuard(e) {
  return process.platform !== `win32` || !hasUserContentInInstallDir()
    ? false
    : (/* 弹窗 + 写日志 */, true);
}
```

## 关键结论

**判据 = 安装目录下存在任何「一级子目录」，且其名字（转小写）不在白名单内。**

| 特性 | 行为 |
|---|---|
| 目录内容 | 无关，**空目录同样触发** |
| 是否真是项目 | 无关，只看名字 |
| 扫描深度 | 只扫一级，不递归 |
| 大小写 | 名字转小写后精确匹配 |
| 额外放行 | 任何以 `$` 开头的目录、任何以 `nsis` 开头的目录 |

白名单：`bin`、`locales`、`resources`、`tools`、`log`、`logs`、`_`、`share-target`、`assets`

## 命中时的表现

- 弹窗：「无法安装必要的更新 —— 检测到应用安装目录下存在用户项目目录，更新会导致项目记录丢失。请先将项目迁移到其他目录（非安装目录）后再重试更新。」
- 日志（`<data-dir>\logs\update\update-YYYYMMDD.log`）：
  ```
  [WARN ] [win32] Update blocked by install dir guard
  [WARN ] Software update check timed out without terminal state
  ```
- 不进入下载阶段，`checkForUpdates` 直接 return。

## 谁会在安装目录里制造违规目录

1. **`Claw`** —— 国内版「本地助理」固定工作目录 = `默认工作区根/Claw`。根目录由 `defaultWorkspacePath` 决定（系统默认 `~/WorkBuddy`）。若根目录被配置成安装目录，启动即重建 `Claw`。
2. **时间戳会话目录**（`YYYY-MM-DD-HH-mm-ss`）—— 新建会话的工作区，同样落在默认工作区根下。
3. **任何用户手动放进安装目录的目录。**

## 复现（最小实验）

```bash
mkdir "D:\WorkBuddy\test-dir"     # 空目录即可
# 启动国内版 → 检查更新 → 必弹窗；删除后重试即恢复
```

## 修复原则

不要改 asar 白名单（破坏完整性、升级被覆盖）。正路是把**默认工作区根迁出安装目录**（`scripts/fix_workspace_root.py`），让 Claw 和会话目录落到 `D:\WorkBuddyProjects` 之类的独立位置，再清掉安装目录里的残留（`scripts/verify_guard.py --clean`）。
