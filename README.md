# trae-switch

在 macOS 上快速切换 Trae CN 登录账号的小工具。

它只做一件事：把 Trae 自己写入本机的登录态字段保存成档案，需要时再换回去。不修改 Trae 应用本体，不绕过登录，也不伪造 token。

## 功能

- `save`：把当前账号的登录态保存为档案
- `use`：退出 Trae，恢复指定档案，再重新启动
- `list`：列出所有档案，并标记当前账号
- `current`：显示当前账号的名字、个人/团队类型、企业名和权益
- `refresh`：为旧档案补齐账号名/类型

## 原理

Trae CN 的账号信息集中在：

```text
~/Library/Application Support/Trae CN/User/globalStorage/storage.json
```

其中与账号相关的字段是：

| 字段 | 内容 |
| --- | --- |
| `iCubeAuthInfo://icube.cloudide` | 加密后的用户信息与 token |
| `iCubeServerData://icube.cloudide` | 权益/配额缓存 |
| `iCubeHostInfo` | 账号对应的服务端域名 |

工具切换时只替换这三个字段，不碰 `machineid`、Cookies、Keychain、聊天数据库等文件。

展示账号名和类型时，会解开本地登录信息里的非敏感字段（用户名、个人/团队、企业名、邮箱）；token 不会输出，也不会写进档案。

## 安装

要求：macOS、Python 3、系统自带 `openssl`。

### 自动安装（一条命令）

```bash
curl -fsSL https://raw.githubusercontent.com/dubiao/trae-switch/main/install.sh | bash
```

脚本会下载最新源码并安装到 `~/.local/bin/trae-switch`。

### 手动安装

```bash
git clone git@github.com:dubiao/trae-switch.git
cd trae-switch
./install.sh
```

只想复制源码也可以：

```bash
mkdir -p ~/.local/bin
install -m 755 src/trae_switch.py ~/.local/bin/trae-switch
```

确认 `~/.local/bin` 在 `PATH` 中，然后运行：

```bash
trae-switch current
```

## 使用

保存当前账号：

```bash
trae-switch save work
```

登录另一个账号后，再保存一个档案：

```bash
trae-switch save personal
```

查看档案：

```bash
trae-switch list
```

切换账号：

```bash
trae-switch use personal -y
```

`use` 会退出 Trae、写入目标档案并重新启动 Trae。请从 macOS 自带的「终端」App 运行，不要在 Trae 内置终端里运行，否则退出 Trae 时脚本会被一起终止。

常用参数：

```text
-y, --yes        不再询问
--no-quit        要求 Trae 已手动退出
--no-launch      切换后不自动启动 Trae
--i-know         允许在 Trae 内置终端执行
```

## 档案与隐私

档案默认保存在：

```text
~/.trae-cn/account-switch/profiles/
```

权限为 `600`。档案里含有加密后的登录态和账号展示信息，**不要提交到 Git，也不要发给别人**。

可以用环境变量改存放位置：

```bash
export TRAE_SWITCH_HOME="$HOME/.config/trae-switch"
```

本仓库只包含程序源码，不包含任何账号档案、token 或个人配置。

## 注意事项

- `use` 会直接覆盖当前登录态，不再自动备份。切换前请先确认当前账号已经 `save` 过，否则需要重新登录。
- token 会随时间刷新，指纹会变化，这是正常的；档案匹配使用稳定的账号 ID。
- 如果在 Trae 里点击“退出登录”，旧 token 可能被服务端作废。此时重新登录该账号，执行 `trae-switch save <名字> --force` 覆盖档案即可；之后尽量用文件切换，不要再用退出登录。
- 账号档案长期不用后 token 可能过期，重新登录并覆盖档案即可。
- 仅用于管理你本人合法拥有的账号，请遵守 Trae 的服务条款。

## 卸载

```bash
rm -f ~/.local/bin/trae-switch
rm -rf ~/.trae-cn/account-switch
```
