#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太乙 contribution 登记执行器 · 跑在 GitHub Actions 上
PR_JSON 非空=登记模式; FIND_ID=1=找映射到Repo的 projectId (GET /project/check?url=)"""
import base64,json,os,functools,time
import urllib.request
print = functools.partial(print, flush=True)
BASE="https://www.taiyi.top/api"
TOKEN=os.environ.get("TAIYI_TOKEN","").strip()
PROJECT_ID=os.environ.get("PROJECT_ID","5196")
LIMIT=int(os.environ.get("LIMIT","10"))
FIND_ID=os.environ.get("FIND_ID","")
REPO=os.environ.get("REPO","agentuniverse-ai/agentUniverse")
PR_JSON=os.environ.get("PR_JSON","")
def http(p,auth=True,method="GET",body=None,tries=3):
    last=""
    for a in range(tries):
        try:
            h={"content-type":"application/json"}
            if auth: h["token"]="Bearer "+TOKEN
            data=json.dumps(body).encode() if body is not None else None
            req=urllib.request.Request(BASE+p,data=data,headers=h,method=method)
            return json.load(urllib.request.urlopen(req,timeout=30))
        except Exception as e:
            last=str(e)[:60]; time.sleep(2*(a+1))
    return {"code":1,"err":last}
def main():
    print(f"== contrib: FIND_ID={FIND_ID} 指纹 len={len(TOKEN)}")
    if not TOKEN: raise SystemExit("TAIYI_TOKEN 空")
    if FIND_ID:
        hit=[]
        for pid in range(5150,5260):
            r=http("/user/center/project/check?url=https://github.com/"+REPO,auth=True)
            d=r.get("data")
            if r.get("code")==200 and d:
                hit.append((pid,d)); print(f"  {pid} → {d}"); break
            time.sleep(0.6)
        print("FIND_ID 结果:",hit); return
    if not PR_JSON: raise SystemExit("PR_JSON 空")
    items=json.loads(base64.b64decode(PR_JSON).decode())
    ok=0;other=0
    for i,(ma,num,title,sha) in enumerate(items[:LIMIT]):
        url=f"https://github.com/{REPO}/commit/{sha}"
        pref=(title or "demo").split(" ")[0].split(":")[0].lower()
        ptype={"fix":"fix","feat":"feat"}.get(pref,"demo")
        r=http("/user/center/contribution/add",auth=True,method="POST",
               body={"contributionUrl":url,"type":ptype,"projectId":int(PROJECT_ID)})
        code=r.get("code") or ((r.get("status") or {}).get("code"))
        msg=r.get("message") or (r.get("status") or {}).get("msg") or json.dumps(r,ensure_ascii=False)[:60]
        print(f"| {i+1} | #{num} | [{ptype}] | code={code} | {str(msg)[:44]} |")
        if code==200: ok+=1
        else: other+=1
        time.sleep(6)
    print(f"登记成功 {ok} 其他 {other} / {min(LIMIT,len(items))}")
if __name__=="__main__": main()
