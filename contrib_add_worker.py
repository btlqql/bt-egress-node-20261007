#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""太乙 contribution 登记执行器 · 跑在 GitHub Actions 上
PR_JSON 非空=登记模式; FIND_ID=1=找映射到Repo的 projectId (GET /project/check?url=)"""
import base64,binascii,json,os,functools,time
import urllib.request
print = functools.partial(print, flush=True)
BASE="https://www.taiyi.top/api"
TOKEN=os.environ.get("TAIYI_TOKEN","").strip()
PROJECT_ID=os.environ.get("PROJECT_ID","5196")
LIMIT=int(os.environ.get("LIMIT","10"))
FIND_ID=os.environ.get("FIND_ID","")
REPO=os.environ.get("REPO","agentuniverse-ai/agentUniverse")
PR_JSON=os.environ.get("PR_JSON","")

def parse_pr_json(value):
    value=value.strip()
    try:
        raw=base64.b64decode(value,validate=True)
        items=json.loads(raw.decode("utf-8"))
    except (ValueError,binascii.Error,UnicodeError,json.JSONDecodeError) as exc:
        raise SystemExit(
            "pr_json 格式错误：只填写 Base64 编码的 JSON 数组，"
            "不要包含统计文字、说明或换行。"
        ) from exc
    if not isinstance(items,list) or not items:
        raise SystemExit("pr_json 必须是非空 JSON 数组")
    for i,item in enumerate(items,1):
        if (not isinstance(item,list) or len(item)!=4
                or not isinstance(item[1],int) or isinstance(item[1],bool)
                or not isinstance(item[2],str) or not isinstance(item[3],str)
                or len(item[3])!=40
                or any(c not in "0123456789abcdefABCDEF" for c in item[3])):
            raise SystemExit(f"pr_json 第 {i} 项格式错误：需要 [merged_at, PR号, 标题, 40位SHA]")
    return items
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
    items=parse_pr_json(PR_JSON)
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
        else:
            other+=1
            print(f"  未登记的提交链接: {url}")
        time.sleep(6)
    print(f"登记成功 {ok} 其他 {other} / {min(LIMIT,len(items))}")
    if other:
        raise SystemExit(f"{other} 条登记未成功；请核对提交链接是否可访问，以及提交者的 GitHub 账号是否已在太乙绑定")
if __name__=="__main__": main()
