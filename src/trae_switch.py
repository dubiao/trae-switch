#!/usr/bin/env python3
"""Trae CN 本机账号快速切换工具。

只读写 Trae CN 自己的登录态字段，不修改应用本体、不绕过登录。
所有账号数据都来自用户本人在 Trae 内的正常登录。

常用命令：
    trae-switch current          查看当前账号（名字/类型/权益）
    trae-switch save <名字>      把当前登录态保存为一个档案
    trae-switch use <名字>       退出 Trae、恢复目标档案并重新启动
    trae-switch list             列出所有档案
    trae-switch refresh          为旧档案补齐账号名/类型
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

APP_SUPPORT = Path.home() / "Library/Application Support/Trae CN"
STORAGE = APP_SUPPORT / "User/globalStorage/storage.json"
JWT_FILE = Path.home() / ".trae-cn/trae-jwt-token"
ROOT = Path(os.environ.get("TRAE_SWITCH_HOME", str(Path.home() / ".trae-cn/account-switch")))
PROFILES = ROOT / "profiles"

# Trae 本地登录信息是自加密格式（AES-128-CBC + 固定混淆表），
# 仅用于解出账号名/类型用于展示，token 不读取、不输出。
_AUE = [82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
        124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
        84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
        8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37]
_DUE = [31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
        96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
        160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
        23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125]
_XOR = bytes(a ^ b for a, b in zip(_AUE, _DUE))

# 登录态相关字段（值均为 Trae 自己写入 storage.json 的内容）
# - iCubeAuthInfo://icube.cloudide : 加密后的用户信息 + token
# - iCubeServerData://icube.cloudide : 该账号的权益/配额缓存
# - iCubeHostInfo : 该账号所属服务端域名（企业版/个人版可能不同）
AUTH_KEYS = [
    "iCubeAuthInfo://icube.cloudide",
    "iCubeServerData://icube.cloudide",
    "iCubeHostInfo",
]
# usertag 是 userId -> 显示名 的映射，保留不换，避免丢失其他账号的显示名
PRIMARY_KEY = AUTH_KEYS[0]

NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def die(msg: str, code: int = 1):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_storage() -> dict:
    if not STORAGE.exists():
        die(f"找不到 Trae 配置：{STORAGE}")
    try:
        return json.loads(STORAGE.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"读取 storage.json 失败：{e}")


def atomic_write_json(path: Path, data: dict, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def fingerprint(storage: dict) -> str:
    value = storage.get(PRIMARY_KEY)
    if not value:
        return "-"
    if not isinstance(value, str):
        value = json.dumps(value, sort_keys=True)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _decrypt_user_info(blob: str) -> dict:
    """解开 Trae 本地登录信息，只用于读取展示字段；token 不返回、不落盘。"""
    if not isinstance(blob, str) or not blob:
        return {}
    try:
        raw = base64.b64decode(blob)
        if raw[:6] != b"\x74\x63\x05\x10\x00\x00":
            return {}
        seed = raw[6:38]
        kdf = hashlib.sha512(hashlib.sha512(seed).digest() + _XOR).digest()
        key, iv = kdf[:16], kdf[16:32]
        openssl = shutil.which("openssl") or "/usr/bin/openssl"
        proc = subprocess.run(
            [openssl, "enc", "-aes-128-cbc", "-d", "-K", key.hex(), "-iv", iv.hex()],
            input=raw[38:], capture_output=True,
        )
        plain = proc.stdout
        if proc.returncode != 0 or len(plain) < 64:
            return {}
        if hashlib.sha512(plain[64:]).digest() != plain[:64]:
            return {}
        return json.loads(plain[64:].decode("utf-8"))
    except Exception:
        return {}


def account_meta(blob: str) -> dict:
    data = _decrypt_user_info(blob)
    if not data:
        return {}
    acc = data.get("account") or {}
    tenant = acc.get("tenant_name") or acc.get("organization") or ""
    scope = acc.get("scope") or ""
    return {
        "userId": data.get("userId") or "",
        "displayName": acc.get("username") or "",
        "kind": "团队" if (tenant or scope == "saas") else "个人",
        "tenant": tenant,
        "email": acc.get("email") or "",
        "scope": scope,
    }


def plan_text(server_data) -> str:
    try:
        data = json.loads(server_data) if isinstance(server_data, str) else (server_data or {})
    except Exception:
        return ""
    saas = data.get("saasEntitlementInfo") or {}
    if saas:
        product_type = saas.get("productType")
        return f"企业版 · productType={product_type}" if product_type is not None else "企业版"
    ent = data.get("entitlementInfo") or {}
    return ent.get("identityStr") or ""


def account_label(meta: dict, fallback: str = "") -> str:
    name = meta.get("displayName") or fallback or "未知账号"
    kind = meta.get("kind") or ""
    tenant = meta.get("tenant") or ""
    suffix = f"{kind} · {tenant}" if tenant else kind
    return f"{name}（{suffix}）" if suffix else name


def app_running() -> bool:
    r = subprocess.run(
        ["pgrep", "-f", "/Applications/Trae CN.app/Contents/MacOS/"],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and bool(r.stdout.strip())


def quit_app(timeout: int = 25) -> bool:
    """优雅退出 Trae，等它把内存里的状态写回磁盘。绝不强杀。"""
    subprocess.run(
        ["osascript", "-e", 'tell application id "cn.trae.app" to quit'],
        capture_output=True, text=True,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not app_running():
            return True
        time.sleep(0.5)
    return not app_running()


def launch_app():
    subprocess.run(["open", "-a", "Trae CN"], capture_output=True, text=True)


def ensure_outside_trae_terminal(allow: bool):
    """在 Trae 内置终端里执行 use 会把自己退出掉，脚本会中途被杀。"""
    if allow:
        return
    markers = [os.environ.get("TERM_PROGRAM", ""), os.environ.get("VSCODE_PID", "")]
    if any("vscode" in m.lower() or "trae" in m.lower() for m in markers):
        die("检测到在 Trae 内置终端中运行。切换账号会退出 Trae 并中断本脚本，\n"
            "      请改用 macOS 的『终端』App 运行；确认无误可加 --i-know 强制执行。")


def profile_meta(profile: dict) -> dict:
    """优先用档案里缓存的展示信息，旧档案则现场解密。"""
    keys = ("userId", "displayName", "kind", "tenant", "email")
    if profile.get("userId") and profile.get("displayName"):
        return {k: profile.get(k) or "" for k in keys}
    return account_meta((profile.get("auth") or {}).get(PRIMARY_KEY))


def cmd_current(_args):
    storage = read_storage()
    fp = fingerprint(storage)
    meta = account_meta(storage.get(PRIMARY_KEY))
    user_id = meta.get("userId")
    active = None
    for p in sorted(PROFILES.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        pm = profile_meta(d)
        if user_id and pm.get("userId") == user_id:
            active = p.stem
            break
        if not user_id and d.get("fingerprint") == fp:
            active = p.stem
            break

    print(f"账号           : {meta.get('displayName') or '(未登录或解密失败)'}")
    kind = meta.get("kind") or ""
    if meta.get("tenant"):
        kind = f"{kind} · {meta['tenant']}"
    print(f"类型           : {kind or '(未知)'}")
    if meta.get("email"):
        print(f"邮箱           : {meta['email']}")
    print(f"权益           : {plan_text(storage.get('iCubeServerData://icube.cloudide')) or '(无缓存)'}")
    print(f"匹配的档案     : {active or '(尚未保存)'}")
    print(f"登录态指纹     : {fp}（会随 token 刷新变化）")


def cmd_list(_args):
    profiles = sorted(PROFILES.glob("*.json"))
    if not profiles:
        print("还没有保存任何档案。先运行：trae-switch save <名字>")
        return
    current = account_meta(read_storage().get(PRIMARY_KEY))
    current_id = current.get("userId")
    print(f"{'名字':<14}{'账号':<14}{'类型':<28}{'保存时间':<21}{'当前'}")
    print("-" * 88)
    for p in profiles:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = profile_meta(d)
        kind = m.get("kind") or ""
        if m.get("tenant"):
            kind = f"{kind} · {m['tenant']}"
        mark = "*" if current_id and m.get("userId") == current_id else ""
        print(f"{p.stem:<14}{str(m.get('displayName') or '-'):<14}{str(kind or '-'):<28}"
              f"{str(d.get('savedAt') or '-'):<21}{mark}")


def cmd_save(args):
    name = args.name
    if not NAME_RE.match(name):
        die("档案名只能包含字母、数字、点、下划线、短横线")
    storage = read_storage()
    missing = [k for k in AUTH_KEYS if not storage.get(k)]
    if PRIMARY_KEY in missing:
        die("当前 Trae 似乎未登录（找不到登录态字段），请先在 Trae 内登录后再保存")

    dest = PROFILES / f"{name}.json"
    if dest.exists() and not args.force:
        die(f"档案 {name} 已存在；需要覆盖请加 --force")
    PROFILES.mkdir(parents=True, exist_ok=True)

    meta = account_meta(storage.get(PRIMARY_KEY))
    if dest.exists():
        # 覆盖同一个账号时沿用原有展示信息，避免刷新后名字/邮箱丢失
        try:
            old = json.loads(dest.read_text(encoding="utf-8"))
            if old.get("userId") and old.get("userId") == meta.get("userId"):
                for key in ("displayName", "kind", "tenant", "email"):
                    if not meta.get(key):
                        meta[key] = old.get(key) or ""
        except Exception:
            pass
    if args.label:
        meta["displayName"] = args.label

    data = {
        "version": 2,
        "name": name,
        "savedAt": now(),
        "fingerprint": fingerprint(storage),
        **{k: meta.get(k, "") for k in ("userId", "displayName", "kind", "tenant", "email")},
        "entitlement": plan_text(storage.get("iCubeServerData://icube.cloudide")),
        "auth": {k: storage[k] for k in AUTH_KEYS if k in storage},
    }
    atomic_write_json(dest, data, 0o600)
    print(f"已保存档案 {name} -> {dest}")
    print(f"  账号   : {account_label(meta)}")
    if meta.get("email"):
        print(f"  邮箱   : {meta['email']}")
    print(f"  权益   : {data['entitlement'] or '(无缓存)'}")
    print(f"  指纹   : {data['fingerprint']}")


def cmd_refresh(_args):
    """为旧档案补齐账号名/类型（只读解密后写回展示字段）。"""
    profiles = sorted(PROFILES.glob("*.json"))
    if not profiles:
        print("还没有档案")
        return
    for p in profiles:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            print(f"{p.stem}: 读取失败，跳过")
            continue
        meta = account_meta((d.get("auth") or {}).get(PRIMARY_KEY))
        if not meta.get("userId"):
            print(f"{p.stem}: 无法解密，跳过")
            continue
        if not meta.get("displayName"):
            meta["displayName"] = d.get("displayName") or ""
            meta["kind"] = d.get("kind") or meta.get("kind") or ""
            meta["tenant"] = d.get("tenant") or ""
            meta["email"] = d.get("email") or ""
        d["version"] = 2
        d.update({k: meta.get(k, "") for k in ("userId", "displayName", "kind", "tenant", "email")})
        d["entitlement"] = plan_text((d.get("auth") or {}).get("iCubeServerData://icube.cloudide"))
        atomic_write_json(p, d, 0o600)
        print(f"{p.stem}: {account_label(meta)}")


def cmd_use(args):
    ensure_outside_trae_terminal(getattr(args, "i_know", False))
    src = PROFILES / f"{args.name}.json"
    if not src.exists():
        die(f"档案 {args.name} 不存在，先运行 trae-switch list 查看")
    profile = json.loads(src.read_text(encoding="utf-8"))
    auth = profile.get("auth") or {}
    if not auth.get(PRIMARY_KEY):
        die(f"档案 {args.name} 缺少登录态，无法切换")
    label = account_label(profile_meta(profile), profile.get("email") or "")

    if app_running():
        if args.no_quit:
            die("Trae 正在运行。请先手动完全退出 Trae，或去掉 --no-quit 让脚本代劳")
        if not args.yes:
            print(f"即将退出 Trae CN，并把账号切换为：{args.name}（{label}）")
            print("提示：请确认没有未保存的内容。")
            ans = input("继续？[y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                print("已取消")
                return
        print("正在退出 Trae CN ...")
        if not quit_app():
            die("Trae 未能退出（可能有未保存的对话框）。请手动退出后重试；脚本不会强杀进程")
    elif args.no_quit:
        pass

    # 退出后再读一次，拿到 Trae 最终写回磁盘的登录态
    current = read_storage()

    changed = []
    for key in AUTH_KEYS:
        if key in auth and current.get(key) != auth[key]:
            current[key] = auth[key]
            changed.append(key)
    if not changed:
        print("目标档案与当前登录态一致，无需修改")
    else:
        mode = STORAGE.stat().st_mode & 0o777
        atomic_write_json(STORAGE, current, mode)
        print("已恢复登录态字段：")
        for key in changed:
            print(f"  - {key}")

    if JWT_FILE.exists():
        try:
            JWT_FILE.unlink()
            print("已清理旧账号的临时 JWT（启动后会自动重新生成）")
        except OSError as e:
            print(f"警告：临时 JWT 清理失败：{e}")

    print(f"当前档案：{args.name}（{label}）")

    if not args.no_launch:
        print("正在启动 Trae CN ...")
        launch_app()
    else:
        print("未自动启动 Trae，请手动打开")


def main():
    parser = argparse.ArgumentParser(
        prog="trae-switch",
        description="Trae CN 本机账号快速切换（保存/恢复 Trae 自身登录态，不修改应用）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("current", help="查看当前账号状态")
    p.set_defaults(func=cmd_current)

    p = sub.add_parser("list", help="列出档案")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("save", help="保存当前登录态为档案")
    p.add_argument("name")
    p.add_argument("--label", help="手动指定账号显示名")
    p.add_argument("--force", action="store_true", help="覆盖同名档案")
    p.set_defaults(func=cmd_save)

    p = sub.add_parser("refresh", help="为旧档案补齐账号名/类型")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("use", help="切换到指定档案")
    p.add_argument("name")
    p.add_argument("--yes", "-y", action="store_true", help="不再询问")
    p.add_argument("--no-quit", action="store_true", help="要求 Trae 已手动退出")
    p.add_argument("--no-launch", action="store_true", help="切换后不自动启动 Trae")
    p.add_argument("--i-know", action="store_true", help="允许在 Trae 内置终端执行")
    p.set_defaults(func=cmd_use)

    args = parser.parse_args()
    if not STORAGE.exists():
        die(f"找不到 Trae 配置：{STORAGE}")
    args.func(args)


if __name__ == "__main__":
    main()
