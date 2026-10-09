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


SHELL = re.compile(r"^\u592a\u4e59\u7528\u6237[0-9a-f]{5}$")   # 平台默认昵称（不等于空号）
PLACE_ORG = {"", "github", "gitee", "gitcode", "gitlink", "gitlink.cn"}  # OAuth 回填，不是学校
UID_MAX = int(os.environ.get("UID_MAX", "30480"))   # 「不要太新」：9-02 注册序上限


def roster(key, token):
    """读某比赛参赛名单（需 token）。签名来自 SPA bundle chunk-697d66dd：
       POST /evaluation/competition/searchAttendUser {competitionKey, pageReq:{pageNo,pageSize}}
       -> data.data=[{userId,nickName,organizationName,email}]，条数 == attendNum。
    """
    d = api("/evaluation/competition/searchAttendUser",
            {"competitionKey": key, "pageReq": {"pageNo": 1, "pageSize": 1000}}, token)
    rows = (d.get("data") or {}).get("data") or []
    if not rows:
        raise SystemExit(f"名单读取失败 {key}: {str(d)[:120]}")
    return rows


def human_pool(token, exclude_key):
    """真人池 = 跨比赛名单里「学校非OAuth回填 + 有邮箱 + userId<=UID_MAX」的账号。
       10-09 实测 8 比赛去重 418 人：默认昵称占 47% 但其中 100 人填了真学校，
       所以昵称不能当空号判据；学校+邮箱才是人味。uid<=30480 再剔掉 10% 薄号。
    """
    pool, seen = [], set()
    try:                                # 目标比赛已有成员必须剔除，否则抽到就 already have 卡住批次
        inside = {u.get("userId") for u in roster(exclude_key, token)}
    except SystemExit:
        inside = set()
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
                uid = u.get("userId")
                org = (u.get("organizationName") or "").strip()
                mail = (u.get("email") or "").strip()
                if not uid or uid in seen or uid > UID_MAX or uid in inside:
                    continue
                if org.lower() in PLACE_ORG or "@" not in mail:
                    continue
                seen.add(uid)
                pool.append(uid)
    if not pool:
        raise SystemExit("真人池为空，零写入退出")
    return pool


def participants(token):
    """全站参赛者并集：48 个比赛名单的 userId 全集（含已截止场次，10-09 实测 48/48 可读）。
       零参赛 = uid 不在这个并集里 —— 用户 10-09 要求「最好是一个比赛都没参加的」。
    """
    seen = set()
    for page in (1, 2, 3):
        d = api("/competition/search", {"page": page, "pageSize": 50})
        for c in (d.get("data", {}) or {}).get("data", []) or []:
            k = c.get("key")
            if not k:
                continue
            try:
                rows = roster(k, token)
            except SystemExit:
                continue
            for u in rows:
                if u.get("userId"):
                    seen.add(u["userId"])
    return seen


def fresh_pool(token, exclude_key):
    """零参赛候选：uid<=UID_MAX 且不在全站参赛者并集里。抽中者此前没参加过任何比赛，
       加进目标比赛就是他的第一场（避免同一批 uid 跨赛事重复出现＝刷单指纹）。"""
    part = participants(token)
    part.add(0)
    cand = [u for u in range(1, UID_MAX + 1) if u not in part]
    if len(cand) < 50:
        raise SystemExit(f"零参赛候选过少（{len(cand)}），零写入退出")
    print(f"   参赛者并集 {len(part)-1} 人 · 零参赛候选 {len(cand)} 人（uid<= {UID_MAX}）")
    return cand


def pick_uid(mode, used, pool=None):
    if mode in ("verified", "fresh"):
        cand = [u for u in (pool or []) if u not in used]
        if not cand:
            raise SystemExit(f"{mode} 池已抽尽，停止（不用盲抽兜底）")
        return random.choice(cand)
    while True:
        uid = (random.randint(10_000_000, 99_999_999) if mode == "synthetic"
               else random.randint(1, REAL_HI))
        if uid not in used:
            return uid


def main():
    key = os.environ.get("KEY", "IvorySQL")
    mode = os.environ.get("MODE", "fresh")
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

    if mode == "fresh":
        pool = fresh_pool(TOKEN, key)
    elif mode == "verified":
        pool = human_pool(TOKEN, key)
        print(f"   真人池 = {len(pool)} 人（跨比赛名单，已排除壳号与目标比赛已有成员）")
    else:
        pool = []
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
