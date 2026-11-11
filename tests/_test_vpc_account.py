"""账号级企业 VPC（vpcEndpoint）套件。

判据：
  1. 显式 vpcEndpoint 的 CN 账号，openapi / gateway / website / domain 全部
     走实例专属域，且**不回退**到公网 api1/api2/api3；
  2. 三态：缺键继承 env、空串显式公网、实例名显式覆盖；非法值 fail-closed；
  3. 落盘往返：显式值写入，继承值不写字段；
  4. 国际版不认这个字段；
  5. SSRF 白名单只放行账号实例的三个主机，且删除账号后会重建；
  6. 设备授权 / PAT 导入按同一实例绑定；
  7. 导入/预览/导出保留 vpcEndpoint，冲突数据拒绝；
  8. CLI 扫描实例目录并在导入时保留来源实例。

    python tests/_test_vpc_account.py
"""
import http.server
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _suite_head import ROOT, bootstrap, check, declare_suite, finish  # noqa: E402

os.environ.pop("QD_CN_VPC_ENDPOINT", None)
P, A = bootstrap()
declare_suite(__file__, ["qoder_accounts.py", "qoder_proxy.py", "dashboard.html"])

BASE_CN = A.get_realm_config("cn")


def cn_account(**extra):
    data = {"uid": "vpc-uid-1", "realm": "cn", "accessToken": "dt-x",
            "nickname": "vpc-test"}
    data.update(extra)
    return A.Account(data)


print("\n[vpc-account] 1) 账号级 VPC 覆盖端点")
acc = cn_account(vpcEndpoint="acme")
cfg = acc.realm_config()
check("gateway 走实例专属域",
      cfg["gateway"] == "https://acme-gateway.vpc.qoder.com.cn", cfg["gateway"])
check("openapi 走实例专属域",
      cfg["openapi"] == "https://acme-openapi.vpc.qoder.com.cn", cfg["openapi"])
check("website 走实例专属域",
      cfg["website"] == "https://acme.vpc.qoder.com.cn", cfg["website"])
check("domain 变成实例域",
      cfg["domain"] == "acme.vpc.qoder.com.cn", cfg["domain"])
check("vpc_instance 被标记", cfg.get("vpc_instance") == "acme",
      cfg.get("vpc_instance"))
check("不回退公网（gateway_fallbacks 为空）",
      not cfg.get("gateway_fallbacks"), cfg.get("gateway_fallbacks"))
check("推理候选只有一个主机",
      A.gateway_candidates("cn", cfg) == ["https://acme-gateway.vpc.qoder.com.cn"],
      A.gateway_candidates("cn", cfg))
check("来源标记为 account", acc.vpc_source == "account", acc.vpc_source)

print("\n[vpc-account] 2) 接受三种写法 / 非法值 fail-closed")
for raw, want in (("acme", "acme"),
                  ("acme.vpc.qoder.com.cn", "acme"),
                  ("https://acme-gateway.vpc.qoder.com.cn/", "acme")):
    got = A.realm_config_for("cn", raw)["vpc_instance"]
    check("写法 %r -> 实例 %r" % (raw, want), got == want, got)
for bad in ("bad value", "acme/../evil", "1.2.3.4", "a" * 70):
    try:
        A.realm_config_for("cn", bad)
        raised = False
    except A.VpcConfigError:
        raised = True
    check("非法值 %r 抛 VpcConfigError" % (bad,), raised)
for blank in ("", "  "):
    check("空值 %r = 显式公网" % (blank,),
          A.realm_config_for("cn", blank)["gateway"] == BASE_CN["gateway"])
bad_acct = cn_account(vpcEndpoint="bad value")
check("非法 vpcEndpoint 的账号不抛构造异常", bool(bad_acct.vpc_error),
      bad_acct.vpc_error)
check("非法账号 ready() 被挡住", not bad_acct.ready())
check("非法账号 inference_eligible() 为假", not bad_acct.inference_eligible())
check("非法账号 checkin_eligible() 为假", not bad_acct.checkin_eligible())
try:
    bad_acct.realm_config()
    raised = False
except A.VpcConfigError:
    raised = True
check("非法账号 realm_config() 抛错，不回退公网", raised)
bad_dir = tempfile.mkdtemp(prefix="qd-vpc-bad-")
with open(os.path.join(bad_dir, "bad.json"), "w", encoding="utf-8") as fh:
    json.dump({"uid": "bad-loaded", "realm": "cn", "accessToken": "dt-x",
               "vpcEndpoint": "bad value"}, fh)
bad_pool = A.AccountPool(bad_dir)
loaded = bad_pool.load()
check("坏账号加载后仍保留（面板可修）",
      [a.uid for a in loaded] == ["bad-loaded"], [a.uid for a in loaded])
check("坏账号加载后带 vpcError", bool(loaded[0].vpc_error), loaded[0].vpc_error)
check("坏账号不会被 representative 选中",
      bad_pool.representative() is None,
      bad_pool.representative())

print("\n[vpc-account] 3) 落盘往返：显式写入 / 继承不写字段")
tmp = tempfile.mkdtemp(prefix="qd-vpc-acct-")
saved = cn_account(vpcEndpoint="acme")
path = saved.save(tmp)
on_disk = json.loads(open(path, encoding="utf-8").read())
check("JSON 里有 vpcEndpoint 字段", on_disk.get("vpcEndpoint") == "acme",
      on_disk.get("vpcEndpoint"))
reloaded = A.Account(json.loads(open(path, encoding="utf-8").read()), path=path)
check("重新加载后端点仍是实例域",
      reloaded.realm_config()["gateway"] == "https://acme-gateway.vpc.qoder.com.cn",
      reloaded.realm_config()["gateway"])
check("public() 暴露 vpcEndpoint（面板靠它画 VPC 徽标）",
      reloaded.public().get("vpcEndpoint") == "acme",
      reloaded.public().get("vpcEndpoint"))
check("保存后 domain 已写成实例域", reloaded.domain == "acme.vpc.qoder.com.cn",
      reloaded.domain)
inherit = cn_account()
inherit_path = inherit.save(tmp)
inherit_disk = json.loads(open(inherit_path, encoding="utf-8").read())
check("继承账号不写 vpcEndpoint 字段", "vpcEndpoint" not in inherit_disk,
      inherit_disk.get("vpcEndpoint", "<present>"))
explicit_public = cn_account(vpcEndpoint="")
public_path = explicit_public.save(tmp)
public_disk = json.loads(open(public_path, encoding="utf-8").read())
check("显式公网写空字符串", public_disk.get("vpcEndpoint") == "",
      public_disk.get("vpcEndpoint"))

print("\n[vpc-account] 3b) 老账号从 domain 反推实例 / 非法 domain")
legacy = A.Account({"uid": "vpc-legacy", "realm": "cn", "accessToken": "x",
                    "domain": "acme.vpc.qoder.com.cn"})
check("从 domain 推出实例名", legacy.vpc_endpoint == "acme", legacy.vpc_endpoint)
check("来源标记为 domain", legacy.vpc_source == "domain", legacy.vpc_source)
check("推理走实例 gateway",
      legacy.realm_config()["gateway"] == "https://acme-gateway.vpc.qoder.com.cn",
      legacy.realm_config()["gateway"])
public_dom = A.Account({"uid": "vpc-pub", "realm": "cn", "accessToken": "x",
                        "domain": "qoder.com.cn"})
check("公网 domain 不产生 VPC", public_dom.vpc_endpoint == "",
      public_dom.vpc_endpoint)
check("公网 domain 仍是公网 gateway",
      public_dom.realm_config()["gateway"] == BASE_CN["gateway"],
      public_dom.realm_config()["gateway"])
odd_dom = A.Account({"uid": "vpc-odd", "realm": "cn", "accessToken": "x",
                     "domain": "-bad.vpc.qoder.com.cn"})
check("非法实例域标记 vpcError", bool(odd_dom.vpc_error), odd_dom.vpc_error)
check("非法实例域不回退公网", not odd_dom.ready())
conflict = A.Account({"uid": "vpc-conflict", "realm": "cn", "accessToken": "x",
                      "domain": "fixture-a.vpc.qoder.com.cn",
                      "vpcEndpoint": "fixture-b"})
check("显式 vpc 与 domain 冲突时标记错误",
      bool(conflict.vpc_error) and "conflicts" in conflict.vpc_error,
      conflict.vpc_error)

print("\n[vpc-account] 4) 国际版不认 VPC")
intl = A.Account({"uid": "vpc-intl", "realm": "intl", "accessToken": "x",
                  "vpcEndpoint": "acme"})
check("intl 账号的 vpcEndpoint 被清空", intl.vpc_endpoint == "", intl.vpc_endpoint)
check("intl 端点不变", intl.realm_config()["gateway"] == "https://api3.qoder.sh",
      intl.realm_config()["gateway"])
check("intl 仍保留故障回退候选",
      len(A.gateway_candidates("intl", intl.realm_config())) == 3,
      A.gateway_candidates("intl", intl.realm_config()))

print("\n[vpc-account] 5) 不配 VPC 时行为不变")
plain = cn_account()
check("gateway 仍是公网", plain.realm_config()["gateway"] == BASE_CN["gateway"],
      plain.realm_config()["gateway"])
check("candidates 仍是单主机公网",
      A.gateway_candidates("cn", plain.realm_config()) == [BASE_CN["gateway"]],
      A.gateway_candidates("cn", plain.realm_config()))
check("to_dict 不写继承字段",
      "vpcEndpoint" not in plain.to_dict(), plain.to_dict().get("vpcEndpoint"))

print("\n[vpc-account] 6) SSRF 白名单 / 重建")
check("实例三域名被登记",
      all(A.is_configured_vpc_host(h) for h in (
          "acme.vpc.qoder.com.cn", "acme-openapi.vpc.qoder.com.cn",
          "acme-gateway.vpc.qoder.com.cn")))
check("别的实例域名没有自动放行",
      not A.is_configured_vpc_host("other-openapi.vpc.qoder.com.cn"))
check("账号的 VPC openapi 能过 URL 校验",
      A.validate_public_http_url("https://acme-openapi.vpc.qoder.com.cn/api/v2")
      .startswith("https://acme-openapi"))
try:
    A.validate_public_http_url("http://127.0.0.1:9/x")
    blocked = False
except ValueError:
    blocked = True
check("通用规则照旧拦本机地址", blocked)
other = cn_account(uid="vpc-other", vpcEndpoint="fixture-b")
A.rebuild_vpc_hosts([acc, other])
check("重建后 A/B 都登记",
      A.is_configured_vpc_host("acme.vpc.qoder.com.cn")
      and A.is_configured_vpc_host("fixture-b.vpc.qoder.com.cn"))
A.rebuild_vpc_hosts([acc])
check("账号移除后旧实例主机不再放行",
      not A.is_configured_vpc_host("fixture-b.vpc.qoder.com.cn"))

print("\n[vpc-account] 7) AccountPool.set_vpc 校验")
pool_dir = tempfile.mkdtemp(prefix="qd-vpc-pool-")
pool = A.AccountPool(pool_dir)
pool.accounts = [cn_account(vpcEndpoint=""), A.Account(
    {"uid": "vpc-intl-2", "realm": "intl", "accessToken": "x", "nickname": "i"})]
pool.accounts[0].save(pool_dir)
pool.accounts[1].save(pool_dir)
set_ok = pool.set_vpc("vpc-uid-1", "acme")
check("set_vpc 生效", (set_ok or {}).get("vpcEndpoint") == "acme", set_ok)
try:
    pool.set_vpc("vpc-uid-1", "bad value")
    raised = False
except ValueError:
    raised = True
check("非法值抛 ValueError（不静默写坏）", raised)
try:
    pool.set_vpc("vpc-intl-2", "acme")
    raised2 = False
except ValueError:
    raised2 = True
check("国际版账号拒绝设置 VPC", raised2)
check("set_vpc 未知 uid 返回 None", pool.set_vpc("nope", "acme") is None)
check("set_vpc 空串显式公网",
      (pool.set_vpc("vpc-uid-1", "") or {}).get("vpcEndpoint") == "")
pool.set_vpc("vpc-uid-1", "acme")
re_added = A.Account({"uid": "vpc-uid-1", "realm": "cn",
                      "accessToken": "dt-relogin"})
pool.add(re_added)
check("重新登录不带 vpcEndpoint 时保留已有实例",
      pool.get("vpc-uid-1").vpc_endpoint == "acme",
      pool.get("vpc-uid-1").vpc_endpoint)

print("\n[vpc-account] 8) 设备授权用实例域名 / 非法值拒绝")
login_pool = A.AccountPool(tempfile.mkdtemp(prefix="qd-vpc-login-"))
started = login_pool.start_login(realm="cn", vpc="acme")
check("authUrl 指向实例 website",
      started["authUrl"].startswith("https://acme.vpc.qoder.com.cn/device/selectAccounts"),
      started["authUrl"])
check("login 记录保留 vpc（poll 必须用同一实例）",
      login_pool.logins[started["state"]].get("vpc") == "acme",
      login_pool.logins[started["state"]].get("vpc"))
plain_login = login_pool.start_login(realm="cn")
check("不带 vpc 时仍走公网 website",
      plain_login["authUrl"].startswith("https://qoder.com.cn/"), plain_login["authUrl"])
try:
    login_pool.start_login(realm="cn", vpc="bad value")
    raised = False
except ValueError:
    raised = True
check("start_login 非法 vpc 抛错", raised)
try:
    login_pool.start_login(realm="intl", vpc="acme")
    raised = False
except ValueError:
    raised = True
check("start_login intl+vpc 拒绝", raised)

print("\n[vpc-account] 9) PAT 导入绑定实例 / 非法值不出站")
seen = []


def fake_http(url, **kwargs):
    seen.append(url)
    if "jobToken" in url:
        return {"token": "dt-pat", "expires_in": 3600000}
    return {"id": "pat-user", "name": "PAT"}


orig_http = A.http_json
A.http_json = fake_http
try:
    pat_account = login_pool.import_pat("pt-fixture", realm="cn", vpc="acme")
    check("PAT 交换走实例 openapi",
          seen and seen[0].startswith("https://acme-openapi.vpc.qoder.com.cn/"),
          seen[:1])
    check("PAT 账号绑定实例", pat_account.vpc_endpoint == "acme",
          pat_account.vpc_endpoint)
    before = len(seen)
    try:
        login_pool.import_pat("pt-fixture", realm="cn", vpc="bad value")
        raised = False
    except A.VpcConfigError:
        raised = True
    check("PAT 非法 vpc 抛错且不出站", raised and len(seen) == before, len(seen) - before)
    try:
        login_pool.import_pat("pt-fixture", realm="intl", vpc="acme")
        raised = False
    except ValueError:
        raised = True
    check("PAT intl+vpc 拒绝", raised)
finally:
    A.http_json = orig_http

print("\n[vpc-account] 10) 导入/预览/导出保留 vpcEndpoint")
row = {"uid": "imp-vpc", "realm": "cn", "accessToken": "dt-x",
       "vpcEndpoint": "fixture-a"}
kw = A.normalise_import_row(row)
check("导入 kwargs 保留 vpcEndpoint", kw.get("vpcEndpoint") == "fixture-a", kw)
check("导入 domain 同步到实例域",
      kw.get("domain") == "fixture-a.vpc.qoder.com.cn", kw.get("domain"))
imp = A.Account(kw)
check("导入账号走实例 gateway",
      imp.realm_config()["gateway"] == "https://fixture-a-gateway.vpc.qoder.com.cn",
      imp.realm_config()["gateway"])
conflict_row = {"uid": "imp-conflict", "realm": "cn", "accessToken": "dt-x",
                "domain": "fixture-a.vpc.qoder.com.cn",
                "vpcEndpoint": "fixture-b"}
try:
    A.normalise_import_row(conflict_row)
    raised = False
except ValueError:
    raised = True
check("导入 domain/vpc 冲突被拒绝", raised)
preview = A.AccountPool(tempfile.mkdtemp(prefix="qd-vpc-import-")).preview_import_rows([row])
check("预览识别为可新增", preview["added"] == ["imp-vpc"], preview)
import_pool = A.AccountPool(tempfile.mkdtemp(prefix="qd-vpc-import2-"))
report = import_pool.import_rows([row])
check("实际入库成功", report["added"] == ["imp-vpc"], report)
check("入库账号仍绑定实例",
      import_pool.get("imp-vpc").realm_config()["gateway"]
      == "https://fixture-a-gateway.vpc.qoder.com.cn")
export_doc = A.build_export_document(import_pool.accounts)
check("导出包含 vpcEndpoint",
      export_doc["accounts"][0].get("vpcEndpoint") == "fixture-a",
      export_doc["accounts"][0].get("vpcEndpoint"))
roundtrip = A.normalise_import_row(export_doc["accounts"][0])
check("导出再导入端点一致",
      roundtrip.get("vpcEndpoint") == "fixture-a"
      and roundtrip.get("domain") == "fixture-a.vpc.qoder.com.cn", roundtrip)

print("\n[vpc-account] 11) 扫描实例 CLI 目录并保留来源实例")
home = tempfile.mkdtemp(prefix="qd-vpc-home-")
old_home = os.environ.get("HOME")
os.environ["HOME"] = home
try:
    public_dir = os.path.join(home, ".qoder-cn", ".auth")
    acme_dir = os.path.join(home, ".qoder-cn", ".vpc", "acme", ".auth")
    os.makedirs(public_dir)
    os.makedirs(acme_dir)
    with open(os.path.join(public_dir, "user"), "w", encoding="utf-8") as fh:
        json.dump({"access_token": "jt-public", "uid": "scan-public",
                   "name": "public"}, fh)
    with open(os.path.join(acme_dir, "user"), "w", encoding="utf-8") as fh:
        json.dump({"access_token": "jt-acme", "uid": "scan-acme",
                   "name": "acme"}, fh)
    detected = A.scan_desktop_credentials(vpc="acme")
    cli = [d for d in detected if d.get("kind") == "cli" and d.get("realm") == "cn"]
    check("扫描到公网 .auth", any(d.get("uid") == "scan-public" for d in cli),
          [(d.get("uid"), d.get("vpcEndpoint")) for d in cli])
    check("扫描到实例 .vpc/acme/.auth", any(d.get("uid") == "scan-acme" for d in cli),
          [(d.get("uid"), d.get("vpcEndpoint")) for d in cli])
    acme_item = next(d for d in cli if d.get("uid") == "scan-acme")
    check("实例扫描项带来源实例", acme_item.get("vpcEndpoint") == "acme",
          acme_item.get("vpcEndpoint"))
    scan_pool = A.AccountPool(tempfile.mkdtemp(prefix="qd-vpc-scan-"))
    imported = A.import_desktop_credential(
        path=acme_item["path"], realm="cn", vpc="acme")
    check("导入实例凭证绑定来源实例",
          scan_pool.get(imported.uid).vpc_endpoint == "acme"
          if scan_pool.get(imported.uid) else False,
          scan_pool.get(imported.uid).vpc_endpoint if scan_pool.get(imported.uid) else None)
finally:
    if old_home is None:
        os.environ.pop("HOME", None)
    else:
        os.environ["HOME"] = old_home

print("\n[vpc-account] 12) 面板接口：非法 / intl+vpc 返回 400")
pool.accounts = [cn_account(vpcEndpoint="")]
P.POOL = pool


class _PanelAlwaysOK(object):
    def valid(self, token):
        return True


P.PANEL = _PanelAlwaysOK()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), P.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


def post(path, payload):
    req = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (PORT, path),
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Panel-Token": "t"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode() or "{}")
        except Exception:
            body = {}
        return exc.code, body


try:
    code, body = post("/accounts/login/start", {"realm": "cn", "vpc": "acme"})
    check("cn + vpc -> 200", code == 200, code)
    check("返回的 authUrl 是实例域",
          str(body.get("authUrl", "")).startswith(
              "https://acme.vpc.qoder.com.cn/"), body.get("authUrl"))
    code2, body2 = post("/accounts/login/start", {"realm": "cn"})
    check("cn 不带 vpc -> 公网域名（env 未设）",
          code2 == 200 and str(body2.get("authUrl", "")).startswith(
              "https://qoder.com.cn/"), body2.get("authUrl"))
    code3, _ = post("/accounts/login/start", {"realm": "intl", "vpc": "acme"})
    check("intl + vpc -> 400（国际版没有实例域）", code3 == 400, code3)
    code4, _ = post("/accounts/login/start", {"realm": "cn", "vpc": "bad value"})
    check("cn + 非法 vpc -> 400", code4 == 400, code4)
    code5, _ = post("/accounts/set", {"uid": "vpc-uid-1", "vpcEndpoint": "bad value"})
    check("/accounts/set 非法 vpc -> 400", code5 == 400, code5)
    code6, _ = post("/accounts/import/pat", {"pat": "pt-x", "realm": "intl",
                                             "vpc": "acme"})
    check("/accounts/import/pat intl+vpc -> 400", code6 == 400, code6)
    code7, _ = post("/accounts/import/desktop", {"vpc": "bad value"})
    check("/accounts/import/desktop 非法 vpc -> 400", code7 == 400, code7)
finally:
    srv.shutdown()
    srv.server_close()

finish()
