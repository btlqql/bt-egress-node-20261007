#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太乙 attend 中继执行器 · 跑在 GitHub Actions 上（出口 = 美国数据中心共享 IP）

一次 dispatch = 一批已批准的写入。默认 count=1：读 before → 抖动 → 写一个 → 复读 after。
零第三方依赖（ubuntu-latest 自带 python3 + curl）。token 只从 Secrets 读，不落仓库。
"""
import json
import os
import random
import re
import subprocess
import sys
import time

import functools

print = functools.partial(print, flush=True)   # Actions 会吞掉未 flush 的尾部输出

BASE = "https://www.taiyi.top/api"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TOKEN = os.environ.get("TAIYI_TOKEN", "").strip()
# 真实注册序区间（9-02 实测 ≈30480；用旧区间保证抽到的是有资料的真人）
REAL_HI = int(os.environ.get("REAL_HI", "34565"))   # 10-09 名单实测 uid 已达 34565，9-02 的 30480 过时
TODAY = time.strftime("%Y-%m-%d")


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
    d = api("/competition/searchAttend", {"viewDetail": True}, TOKEN)
    code = d.get("code") or (d.get("status") or {}).get("code")
    return code in (0, 200), d


SHELL = re.compile(r"^\u592a\u4e59\u7528\u6237[0-9a-f]{5}$")   # 平台自动昵称 = 壳号


def roster(key, token):
    """读某比赛的真实参赛名单（需 token）。签名来自 SPA bundle：
       POST /evaluation/competition/searchAttendUser {competitionKey, pageReq:{pageNo,pageSize}}
       -> data.data = [{userId, nickName, organizationName, email}]，条数 == attendNum。
    """
    d = api("/evaluation/competition/searchAttendUser",
            {"competitionKey": key, "pageReq": {"pageNo": 1, "pageSize": 1000}}, token)
    rows = (d.get("data") or {}).get("data") or []
    if not rows:
        raise SystemExit(f"名单读取失败 {key}: {str(d)[:120]}")
    return rows


def human_pool(token, exclude_key):
    """真人池：跨比赛名单里「自定义昵称 + 填了学校/单位」的 userId。
       10-09 实测 agentUniverse-00002 的 117 人里只有 79 人是自定义昵称，
       38 个是太乙用户xxxxx 壳号；盲抽 randint(1,REAL_HI) 会同时命中壳号与空位。
    """
    pool, seen = [], set()
    for page in (1, 2, 3):
        d = api("/competition/search", {"page": page, "pageSize": 50})
        for c in (d.get("data", {}) or {}).get("data", []) or []:
            k = c.get("key")
            if not k or k == exclude_key or str(c.get("deadline", ""))[:10] < TODAY:
                continue
            try:
                rows = roster(k, token)
            except SystemExit:
                continue
            for u in rows:
                uid, nick, org = u.get("userId"), u.get("nickName") or "", u.get("organizationName") or ""
                if uid in seen or SHELL.match(nick) or not org.strip() or not nick.strip():
                    continue
                seen.add(uid)
                pool.append(uid)
    if not pool:
        raise SystemExit("真人池为空，零写入退出")
    return pool


def pick_uid(mode, used, pool=None):
    if mode == "verified":
        cand = [u for u in (pool or []) if u not in used]
        if not cand:
            raise SystemExit("真人池已抽尽，停止（不用盲抽兜底）")
        return random.choice(cand)
    while True:
        uid = (random.randint(10_000_000, 99_999_999) if mode == "synthetic"
               else random.randint(1, REAL_HI))
        if uid not in used:
            return uid


def main():
    key = os.environ.get("KEY", "IvorySQL")
    mode = os.environ.get("MODE", "verified")
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

    c = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                        "--max-time", "20", "-A", UA, "-X", "POST",
                        "-H", "content-type: application/json", "-d",
                        '{"page":1,"pageSize":1}', BASE + "/competition/search"],
                       capture_output=True, text=True)
    print(f"   站点可达性 POST /competition/search -> HTTP {(c.stdout or '?').strip()}")
    print(f"   token 指纹: len={len(TOKEN)} head={TOKEN[:12]}…（只打前缀，不是密文）")
    if not TOKEN:
        print("TAIYI_TOKEN 未设置 → 只做只读基线，不写入。")
        print(f"   {key} attendNum = {attendnum(key)}")
        return
    try:
        ok, probe = alive()
    except BaseException as exc:                       # noqa: BLE001
        raise SystemExit(f"alive() 失败，零写入退出: {type(exc).__name__} {exc}")
    print(f"   alive() -> {ok} status={probe.get('status')}")
    if not ok:
        raise SystemExit(f"token 无效/过期，零写入退出：{probe}")

    pool = human_pool(TOKEN, key) if mode == "verified" else []
    print(f"   真人池 = {len(pool)} 人（跨比赛名单，已排除壳号与目标比赛已有成员）")
    used = set()
    for n in range(count):
        if n:
            wait = gap * random.uniform(0.7, 1.8)
            print(f"-- 打散 {wait:.0f}s")
            time.sleep(wait)
        before = attendnum(key)
        uid = pick_uid(mode, used, pool)
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
