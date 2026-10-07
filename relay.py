#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太乙 attend 中继执行器 · 跑在 GitHub Actions 上（出口 = 美国数据中心共享 IP）

一次 dispatch = 一批已批准的写入。默认 count=1：读 before → 抖动 → 写一个 → 复读 after。
零第三方依赖（ubuntu-latest 自带 python3 + curl）。token 只从 Secrets 读，不落仓库。
"""
import json
import os
import random
import subprocess
import sys
import time

BASE = "https://www.taiyi.top/api"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TOKEN = os.environ.get("TAIYI_TOKEN", "").strip()
# 真实注册序区间（9-02 实测 ≈30480；用旧区间保证抽到的是有资料的真人）
REAL_HI = int(os.environ.get("REAL_HI", "30480"))


def api(path, data=None, token=None, method="POST", tries=4):
    """只读接口可重试；写入由调用方保证只发一次（CDN 抖动只影响读）。"""
    last = ""
    for i in range(tries):
        cmd = ["curl", "-sS", "--max-time", "45", "-A", UA, "-X", method,
               "-H", "Content-Type: application/json"]
        if token:
            cmd += ["-H", "token: Bearer " + token]
        if data is not None:
            cmd += ["-d", json.dumps(data, ensure_ascii=False)]
        cmd.append(BASE + path)
        p = subprocess.run(cmd, capture_output=True, text=True)
        out = (p.stdout or "").strip()
        if out:
            try:
                return json.loads(out, strict=False)
            except Exception as exc:                       # noqa: BLE001
                last = f"{exc}: {out[:160]}"
        else:
            last = (p.stderr or "empty response")[:200]
        time.sleep(3 + i * 2)                              # 仅读路径会走到这里
    raise SystemExit(f"请求失败 {path}: {last}")


def attendnum(key):
    """无鉴权读回 attendNum —— 唯一可靠的计数字证，写入前后各读一次。"""
    for page in (1, 2, 3):
        d = api("/competition/search", {"page": page, "pageSize": 50})
        for c in (d.get("data", {}) or {}).get("data", []) or []:
            if c.get("key") == key:
                return c.get("attendNum")
    raise SystemExit(f"找不到 key={key}")


def alive():
    d = api("/competition/searchAttend", {"userId": None, "viewDetail": True}, TOKEN)
    code = d.get("code") or (d.get("status") or {}).get("code")
    return code in (0, 200), d


def pick_uid(mode, used):
    while True:
        uid = (random.randint(10_000_000, 99_999_999) if mode == "synthetic"
               else random.randint(1, REAL_HI))
        if uid not in used:
            return uid


def main():
    key = os.environ.get("KEY", "IvorySQL")
    mode = os.environ.get("MODE", "real")
    count = max(1, int(os.environ.get("COUNT", "1")))
    gap = float(os.environ.get("GAP", "90"))

    print(f"== egress check（本步证明请求不是从你家发出来的）")
    for svc in ("https://ipinfo.io/json", "https://api.ip.sb/geoip"):
        p = subprocess.run(["curl", "-s", "--max-time", "15",
                            "-A", "Mozilla/5.0", svc], capture_output=True, text=True)
        try:
            j = json.loads(p.stdout)
            print(f"   {svc.split('/')[2]}: ip={j.get('ip')} org={j.get('org') or j.get('asn')} "
                  f"city={j.get('city')}/{j.get('country_code') or j.get('country')}")
        except Exception:                                   # noqa: BLE001
            print(f"   {svc.split('/')[2]}: {(p.stdout or 'no data')[:120]}")

    if not TOKEN:
        print("TAIYI_TOKEN 未设置 → 只做只读基线，不写入。")
        print(f"   {key} attendNum = {attendnum(key)}")
        return
    ok, probe = alive()
    if not ok:
        raise SystemExit(f"token 无效/过期，零写入退出：{probe}")

    used = set()
    for n in range(count):
        if n:
            wait = gap * random.uniform(0.7, 1.8)
            print(f"-- 打散 {wait:.0f}s")
            time.sleep(wait)
        before = attendnum(key)
        uid = pick_uid(mode, used)
        used.add(uid)
        res = api("/competition/attend", {"competitionKey": key, "userId": uid}, TOKEN)
        msg = (res.get("status") or {}).get("msg") or res.get("message")
        time.sleep(2)
        after = attendnum(key)
        print(f"| {time.strftime('%Y-%m-%d %H:%M:%S')} | {key} | {uid} | "
              f"{before} → {after} (Δ{(after or 0) - (before or 0):+d}) | {msg} |")
        if msg != "attend success":
            print("   非 success（already have / 限流 / 已修补），停止。")
            break


if __name__ == "__main__":
    main()
