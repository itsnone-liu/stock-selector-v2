#!/usr/bin/env python3
"""百度网盘开放平台归档工具（官方 API：设备码授权 + 预上传/分片/创建）。

用法：
  auth                 设备码授权（用户手机确认）→ token 存 /root/.config/bdpan/
  whoami               验证 token，显示账号与剩余容量
  upload <file>        上传单个文件到 /apps/<APP_NAME>/<file名>（4MB 分片，断点续传）
  verify <file>        核对远端文件存在且大小一致

凭据：/root/.config/bdpan/app.json {"app_key":..., "secret_key":..., "app_name":...}
说明：分片 MD5 在协议层强制校验（block_list），故远端内容完整性由上传协议本身保证；
      verify 再核对 size 与 fs_id。控制面调用节流：预上传/创建各 1 次，遇 20012 等待重试。
"""
import argparse, hashlib, json, os, sys, time
from pathlib import Path

import requests

UA = {"User-Agent": "pan.baidu.com"}
CFG = Path("/root/.config/bdpan")
SLICE = 4 * 1024 * 1024  # 4MB，分片≤1024 → 单文件≤4G，通吃会员/非会员
PAN = "https://pan.baidu.com"
OAUTH = "https://openapi.baidu.com"


def load_app():
    p = CFG / "app.json"
    if not p.exists():
        sys.exit("缺少 %s —— 请先放入 app_key/secret_key/app_name" % p)
    return json.loads(p.read_text())


def save_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1))


def get_token(app, allow_refresh=True):
    tf = CFG / "token.json"
    if tf.exists():
        t = json.loads(tf.read_text())
        if t.get("expires_at", 0) > time.time() + 600:
            return t["access_token"]
        if allow_refresh and t.get("refresh_token"):
            r = requests.get(f"{OAUTH}/oauth/2.0/token", params={
                "grant_type": "refresh_token", "refresh_token": t["refresh_token"],
                "client_id": app["app_key"], "client_secret": app["secret_key"]}, headers=UA, timeout=30).json()
            if "access_token" in r:
                r["expires_at"] = time.time() + r.get("expires_in", 2592000)
                save_json(tf, r)
                return r["access_token"]
            print("refresh 失败(%s)，需重新授权" % r.get("error", r))
    sys.exit("无有效 token，请先运行: bdpan_archive.py auth")


def api(method, url, params=None, data=None, files=None, timeout=60):
    for attempt in range(6):
        r = requests.request(method, url, params=params, data=data, files=files, headers=UA, timeout=timeout)
        try:
            j = r.json()
        except Exception:
            j = {"errno": -1, "raw": r.text[:200]}
        errno = j.get("errno", j.get("error_code", -1))
        if errno == 0 or "access_token" in j or "fs_id" in j or "guid_info" in j:
            return j
        if errno == 20012:  # 频控：测试态 10次/小时
            wait = 1860 if attempt == 0 else 3720
            print(f"[rate-limit 20012] 等待 {wait//60} 分钟后重试（attempt {attempt+1}/6）", flush=True)
            time.sleep(wait)
            continue
        if errno in (-6, 111):  # 授权失效
            sys.exit("token 失效(errno=%s)，请重新 auth" % errno)
        print(f"[warn] errno={errno} msg={j.get('errmsg') or j.get('error_msg')} attempt={attempt+1}", flush=True)
        time.sleep(min(60 * (attempt + 1), 300))
    sys.exit(f"API 重试耗尽: {url} {j}")


def cmd_auth(app):
    r = requests.get(f"{OAUTH}/oauth/2.0/device/code", params={
        "response_type": "device_code", "client_id": app["app_key"],
        "scope": "basic,netdisk"}, headers=UA, timeout=30).json()
    if "device_code" not in r:
        sys.exit(f"获取设备码失败: {r}")
    print("=" * 52)
    print("请在手机/电脑打开:", r["verification_url"])
    print("输入用户码:", r["user_code"])
    print("(或扫码)", r.get("qrcode_url"))
    print("有效期 %s 秒，确认授权后本程序自动继续" % r.get("expires_in", 300))
    print("=" * 52, flush=True)
    deadline = time.time() + r.get("expires_in", 300)
    while time.time() < deadline:
        time.sleep(max(r.get("interval", 5), 5))
        t = requests.get(f"{OAUTH}/oauth/2.0/token", params={
            "grant_type": "device_token", "code": r["device_code"],
            "client_id": app["app_key"], "client_secret": app["secret_key"]}, headers=UA, timeout=30).json()
        if "access_token" in t:
            t["expires_at"] = time.time() + t.get("expires_in", 2592000)
            save_json(CFG / "token.json", t)
            print("授权成功，token 已保存（30 天有效，refresh_token 10 年）")
            return
        if t.get("error") not in ("authorization_pending", "expired_token"):
            print("[poll]", t.get("error"), flush=True)
    sys.exit("设备码过期未确认授权，重新运行 auth")


def cmd_whoami(app):
    tok = get_token(app)
    u = requests.get(f"{PAN}/rest/2.0/xpan/nas", params={
        "method": "uinfo", "access_token": tok}, headers=UA, timeout=30).json()
    q = requests.get(f"{PAN}/api/quota", params={
        "access_token": tok, "checkfree": 1, "checkexpire": 1}, headers=UA, timeout=30).json()
    gb = 1 << 30
    print(f"账号: {u.get('baidu_name')} / 网盘: {u.get('netdisk_name')}  vip_type={u.get('vip_type')}")
    print(f"容量: 已用 {q['used']/gb:.1f}G / 总 {q['total']/gb:.1f}G")


def file_md5s(path):
    """整体 md5 + 4MB 分片 md5 列表（单遍流式）。"""
    m, slices, buf_acc = hashlib.md5(), [], b""
    with open(path, "rb") as f:
        while True:
            buf = f.read(1024 * 1024)
            if not buf:
                break
            m.update(buf)
            buf_acc += buf
            while len(buf_acc) >= SLICE:
                slices.append(hashlib.md5(buf_acc[:SLICE]).hexdigest())
                buf_acc = buf_acc[SLICE:]
    if buf_acc:
        slices.append(hashlib.md5(buf_acc).hexdigest())
    if not slices:  # 空文件
        slices = [hashlib.md5(b"").hexdigest()]
    return m.hexdigest(), slices


def upload_host(tok, path, uploadid):
    j = api("GET", f"https://d.pcs.baidu.com/rest/2.0/pcs/file", params={
        "method": "locateupload", "appid": 250528, "access_token": tok,
        "path": path, "uploadid": uploadid, "upload_version": "2.0"})
    host = (j.get("servers") or [{}])[0].get("server") or j.get("host") or "d.pcs.baidu.com"
    return host if "." in host else "d.pcs.baidu.com"


def cmd_upload(app, local):
    local = Path(local).resolve()
    tok = get_token(app)
    remote = f"/apps/{app['app_name']}/{local.name}"
    size = local.stat().st_size
    md5, slices = file_md5s(local)
    print(f"本地: {local.name} {size/1e9:.2f}GB 分片数 {len(slices)} 整体md5 {md5}")
    if len(slices) > 1024:
        sys.exit("分片>1024，需拆分文件")

    common = {"access_token": tok, "path": remote}
    pre = api("POST", f"{PAN}/rest/2.0/xpan/file", params={"method": "precreate", **common},
              data={"size": size, "isdir": 0, "autoinit": 1, "rtype": 3,
                    "block_list": json.dumps(slices), "content-md5": md5})
    if pre.get("return_type") == 2:  # 秒传
        print("✓ 秒传成功（服务器已有相同文件）", json.dumps(pre, ensure_ascii=False))
        return pre
    uploadid = pre["uploadid"]
    need = set(pre.get("block_list") or range(len(slices)))
    print(f"uploadid={uploadid} 待传分片 {len(need)}/{len(slices)}")

    host = upload_host(tok, remote, uploadid)
    print("上传主机:", host, flush=True)
    t0, done_bytes = time.time(), 0
    with open(local, "rb") as f:
        for seq in sorted(need):
            f.seek(seq * SLICE)
            part = f.read(SLICE)
            for attempt in range(5):
                try:
                    rr = requests.post(f"https://{host}/rest/2.0/pcs/superfile2",
                                       params={"method": "upload", "type": "tmpfile",
                                               "access_token": tok, "path": remote,
                                               "uploadid": uploadid, "partseq": seq},
                                       files={"file": (f"part-{seq}", part)}, headers=UA, timeout=600)
                    j = rr.json()
                    if j.get("md5") == hashlib.md5(part).hexdigest():
                        break
                    print(f"[slice {seq}] md5 不匹配应答: {rr.text[:120]}")
                except Exception as e:
                    print(f"[slice {seq}] {type(e).__name__} {e}")
                time.sleep(15 * (attempt + 1))
            else:
                sys.exit(f"分片 {seq} 反复失败，稍后重跑本命令自动续传")
            done_bytes += len(part)
            if seq % 10 == 0 or seq == max(need):
                dt = time.time() - t0
                print(f"分片 {seq+1}/{len(need)}  {done_bytes/1e6:.0f}MB  "
                      f"{done_bytes/max(dt,1)/1e6:.2f}MB/s  预计剩余 "
                      f"{(size-done_bytes)/max(done_bytes/max(dt,1),1)/60:.0f}分", flush=True)

    cre = api("POST", f"{PAN}/rest/2.0/xpan/file", params={"method": "create", **common},
              data={"size": size, "isdir": 0, "rtype": 3, "block_list": json.dumps(slices)})
    print("✓ 上传完成:", json.dumps({k: cre.get(k) for k in ("fs_id", "size", "path")}, ensure_ascii=False))
    save_json(CFG / f"upload-{local.name}.json",
              {"local": str(local), "local_sha256": hashlib.sha256(open(local, 'rb').read()).hexdigest()
                  if size < 500_000_000 else "(>500M 略)", "remote": remote,
               "size": size, "md5": md5, "slices": len(slices), "fs_id": cre.get("fs_id"),
               "uploaded_at": time.strftime("%F %T")})
    return cre


def cmd_verify(app, local):
    tok = get_token(app)
    local = Path(local).resolve()
    remote_dir = f"/apps/{app['app_name']}"
    lst = api("GET", f"{PAN}/rest/2.0/xpan/file", params={
        "method": "list", "access_token": tok, "dir": remote_dir, "web": 1})
    hit = [x for x in lst.get("list", []) if x.get("server_filename") == local.name]
    if not hit:
        sys.exit(f"远端未找到 {local.name}（目录 {remote_dir} 共 {len(lst.get('list', []))} 个文件）")
    f0 = hit[0]
    same = f0.get("size") == local.stat().st_size
    print(f"远端: {f0['server_filename']} size={f0.get('size')} 本地 size={local.stat().st_size} "
          f"{'一致 ✓' if same else '不一致 ✗'}  fs_id={f0.get('fs_id')} md5(远端)={f0.get('md5','-')}")
    if not same:
        sys.exit(1)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("cmd", choices=["auth", "whoami", "upload", "verify"])
    a.add_argument("file", nargs="?")
    args = a.parse_args()
    app = load_app()
    {"auth": lambda: cmd_auth(app),
     "whoami": lambda: cmd_whoami(app),
     "upload": lambda: cmd_upload(app, args.file),
     "verify": lambda: cmd_verify(app, args.file)}[args.cmd]()


if __name__ == "__main__":
    main()
