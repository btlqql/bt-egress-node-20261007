#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太乙 contribution 登记执行器 · 跑在 GitHub Actions 上

一次 dispatch = 一批登记（每条一次写入，可撤回有 delete 接口）。
输入: PR_JSON (b64 的 [[merged_at,number,title,head_sha],...]), PROJECT_ID, LIMIT
归属: Secret 里那枚太乙号 token 自己名下的贡献才归属成功——调用侧按号分好组。
"""
import base64,json,os,functools,time
import urllib.request
print = functools.partial(print, flush=True)
BASE="https://www.taiyi.top/api"
TOKEN=os.environ.get("TAIYI_TOKEN","").strip()
PROJECT_ID=int(os.environ.get("PROJECT_ID","5196"))
LIMIT=int(os.environ.get("LIMIT","10"))
def post(path,body,tries=3):
    last=""
    for a in range(tries):
        try:
            req=urllib.request.Request(BASE+path,data=json.dumps(body).encode(),
                headers={"content-type":"application/json","token":"Bearer "+TOKEN})
            return json.load(urllib.request.urlopen(req,timeout=30))
        except Exception as e:
            last=str(e)[:60]; time.sleep(2*(a+1))
    return {"code":1,"err":last}
def main():
    print(f"== contrib 登记: projectId={PROJECT_ID} limit={LIMIT} 指纹 len={len(TOKEN)}")
    if not TOKEN: raise SystemExit("TAIYI_TOKEN 空，零登记退出")
    items=json.loads(base64.b64decode(os.environ.get("PR_JSON","")).decode())
    print(f"   待登记 {len(items)} 条 → 取前 {LIMIT}")
    ok=0;other=0
    for i,it in enumerate(items[:LIMIT]):
        ma,num,title,sha=it
        url=f"https://github.com/agentuniverse-ai/agentUniverse/commit/{sha}"
        pref=(title or "demo").split(" ")[0].split(":")[0].lower()
        ptype={"fix":"fix","feat":"feat"}.get(pref,"demo")
        r=post("/user/center/contribution/add",{"contributionUrl":url,"type":ptype,"projectId":PROJECT_ID})
        code=r.get("code") or ((r.get("status") or {}).get("code"))
        msg=r.get("message") or (r.get("status") or {}).get("msg") or json.dumps(r,ensure_ascii=False)[:60]
        print(f"| {i+1} | #{num} | [{ptype}] | code={code} | {str(msg)[:40]} |")
        if code==200: ok+=1
        else: other+=1
        time.sleep(5)
    print(f"登记成功 {ok} 其他 {other} / {min(LIMIT,len(items))}")
if __name__=="__main__": main()
