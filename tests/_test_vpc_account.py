"""账号级企业 VPC（vpcEndpoint）套件。

判据：VPC 从「全局环境变量」下沉到「账号配置文件」之后，
  1. 带 vpcEndpoint 的 CN 账号，openapi / gateway / website / domain 全部
     走实例专属域，且**不回退**到公网 api1/api2/api3；
  2. 该值随账号 JSON 落盘，重新加载后仍生效（save/load 往返）；
  3. 国际版不认这个字段（脏配置被清空，端点不变）；
  4. 账号的 VPC 主机只对自己的三个域名放宽 SSRF 校验，别的 vpc 域名照旧拒绝；
  5. 没有 vpcEndpoint 的账号，行为与加这个功能之前**逐字节一致**；
  6. 面板接口：/accounts/login/start 接受 vpc，但 intl+vpc 直接 400。

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

print("\n[vpc-account] 2) 接受三种写法 / 非法值安全回退")
for raw, want in (("acme", "acme"),
                  ("acme.vpc.qoder.com.cn", "acme"),
                  ("https://acme-gateway.vpc.qoder.com.cn/", "acme")):
    got = A.realm_config_for("cn", raw)["vpc_instance"]
    check("写法 %r -> 实例 %r" % (raw, want), got == want, got)
for bad in ("", "  ", "bad value", "acme/../evil", "1.2.3.4", "a" * 70):
    resolved = A.realm_config_for("cn", bad)
    check("非法值 %r 回退公网" % (bad,),
          resolved["gateway"] == BASE_CN["gateway"], resolved["gateway"])
check("非法 vpcEndpoint 的账号不抛异常",
      cn_account(vpcEndpoint="bad value").realm_config()["gateway"]
      == BASE_CN["gateway"])

print("\n[vpc-account] 3) 落盘往返")
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

print("\n[vpc-account] 3b) 老账号从 domain 反推实例（无 vpcEndpoint 字段）")
legacy = A.Account({"uid": "vpc-legacy", "realm": "cn", "accessToken": "x",
                    "domain": "acme.vpc.qoder.com.cn"})
check("从 domain 推出实例名", legacy.vpc_endpoint == "acme", legacy.vpc_endpoint)
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
check("非法实例域不产生 VPC", odd_dom.vpc_endpoint == "", odd_dom.vpc_endpoint)

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
check("to_dict 写出空字符串而不是缺字段",
      plain.to_dict().get("vpcEndpoint") == "", plain.to_dict().get("vpcEndpoint"))

print("\n[vpc-account] 6) SSRF 白名单只放行该账号的三个主机")
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

print("\n[vpc-account] 8) 设备授权用实例域名")
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


print("\n[vpc-account] 9) /accounts/login/start 接口")
pool.accounts = [cn_account(vpcEndpoint="")]
P.POOL = pool


class _PanelAlwaysOK(object):
    def valid(self, token):
        return True


P.PANEL = _PanelAlwaysOK()
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), P.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


def post(payload):
    req = urllib.request.Request(
        "http://127.0.0.1:%d/accounts/login/start" % PORT,
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
    code, body = post({"realm": "cn", "vpc": "acme"})
    check("cn + vpc -> 200", code == 200, code)
    check("返回的 authUrl 是实例域",
          str(body.get("authUrl", "")).startswith(
              "https://acme.vpc.qoder.com.cn/"), body.get("authUrl"))
    code2, body2 = post({"realm": "cn"})
    check("cn 不带 vpc -> 公网域名",
          code2 == 200 and str(body2.get("authUrl", "")).startswith(
              "https://qoder.com.cn/"), body2.get("authUrl"))
    code3, _ = post({"realm": "intl", "vpc": "acme"})
    check("intl + vpc -> 400（国际版没有实例域）", code3 == 400, code3)
finally:
    srv.shutdown()
    srv.server_close()

finish()
