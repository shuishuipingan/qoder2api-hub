"""企业 VPC 的解析 / 环境默认 / 实例隔离套件。

判据：
  1. 解析规则与 v1.9.6 的加固保持一致（实例名 / 三种官方域名；拒绝路径、端口、
     凭据、query、空端口、空 query 标记；实例名最长 55 字符）；
  2. QD_CN_VPC_ENDPOINT 是**默认值**：账号缺省继承，显式实例覆盖，显式空串
     走公网；非法环境变量不会启动退出，但继承账号 fail-closed；
  3. SSRF 白名单只登记账号实际实例，未登记域名照旧按公网规则校验；
  4. 重定向只允许源请求所属实例的三个主机，模型发现走同一隔离 opener；
  5. CLI 凭据目录优先实例目录。

    python tests/_test_vpc_endpoint.py
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _suite_head import ROOT, bootstrap, check, declare_suite, finish  # noqa: E402

os.environ.pop("QD_CN_VPC_ENDPOINT", None)
P, A = bootstrap()
declare_suite(__file__, ["qoder_accounts.py", "qoder_proxy.py"])


def run_py(code, env_extra):
    env = dict(os.environ)
    env.pop("QD_CN_OPENAPI", None)
    env.pop("QD_CN_VPC_ENDPOINT", None)
    env["PYTHONPATH"] = os.pathsep.join(
        [ROOT] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env.update(env_extra)
    out = subprocess.check_output([sys.executable, "-c", code],
                                  cwd=ROOT, env=env, text=True,
                                  stderr=subprocess.STDOUT, timeout=60)
    return out.strip().splitlines()[-1]


print("\n[vpc] 1) 解析：实例名与三种官方域名")
CASES = {
    "acme": ("acme", "https://acme.vpc.qoder.com.cn",
             "https://acme-openapi.vpc.qoder.com.cn",
             "https://acme-gateway.vpc.qoder.com.cn"),
    "ACME.VPC.QODER.COM.CN": ("acme", "https://acme.vpc.qoder.com.cn",
                              "https://acme-openapi.vpc.qoder.com.cn",
                              "https://acme-gateway.vpc.qoder.com.cn"),
    "https://acme-openapi.vpc.qoder.com.cn/": (
        "acme", "https://acme.vpc.qoder.com.cn",
        "https://acme-openapi.vpc.qoder.com.cn",
        "https://acme-gateway.vpc.qoder.com.cn"),
    "acme-gateway.vpc.qoder.com.cn": (
        "acme", "https://acme.vpc.qoder.com.cn",
        "https://acme-openapi.vpc.qoder.com.cn",
        "https://acme-gateway.vpc.qoder.com.cn"),
}
for value, expected in CASES.items():
    got = A.parse_vpc_endpoint(value)
    actual = ((got or {}).get("instance"), (got or {}).get("website"),
              (got or {}).get("openapi"), (got or {}).get("gateway"))
    check("解析 %r" % value, actual == expected, actual)

check("空值 = 未配置（返回 None）", A.parse_vpc_endpoint("") is None)

print("\n[vpc] 2) 解析：拒绝部分重定向输入（含 v1.9.6 的边界加固）")
BAD = (
    "  acme", "acme  ", "acme\n", "acme:8443",
    "acme/path", "acme?x=1", "acme#frag",
    "other.example.com", "acme.vpc.qoder.com.cn.evil.test",
    "ftp://acme", "u:p@acme.vpc.qoder.com.cn",
    "acme..vpc.qoder.com.cn", "-acme", "acme-",
    "a" * 56, "a" * 63, "acme:", "acme?", "acme.vpc.qoder.com.cn:",
)
for value in BAD:
    try:
        A.parse_vpc_endpoint(value)
        ok = False
    except ValueError:
        ok = True
    check("拒绝 %r" % value, ok)

longest = A.parse_vpc_endpoint("a" * 55)
check("55 字符实例的 gateway label 恰为 63 字符",
      len(longest["gateway"].split("//", 1)[1].split(".")[0]) == 63)

print("\n[vpc] 3) 未配置账号：CN 行为就是公网")
check("CN openapi 是公网",
      A.get_realm_config("cn")["openapi"] == "https://openapi.qoder.com.cn")
check("CN gateway 是单一官方主机",
      A.gateway_candidates("cn") == ["https://gateway.qoder.com.cn"])
check("CN openapi 候选不含 VPC 域",
      not any("vpc.qoder.com.cn" in c for c in A.openapi_candidates("cn")))
check("未登记时 is_configured_vpc_host 为 False",
      not A.is_configured_vpc_host("acme-openapi.vpc.qoder.com.cn"))

print("\n[vpc] 4) 子进程：环境变量是默认值，不是停用")
CODE = r'''
import json
import qoder_accounts as A
out = {"configured": A.VPC_ENV_CONFIGURED, "error": A.VPC_ENV_ERROR,
       "base_openapi": A.get_realm_config("cn")["openapi"],
       "base_gateway": A.get_realm_config("cn")["gateway"]}
try:
    default = A.realm_config_for("cn")
    out["default_openapi"] = default["openapi"]
    out["default_gateway"] = default["gateway"]
    out["default_candidates"] = A.gateway_candidates("cn")
except Exception as exc:
    out["default_error"] = str(exc)
inherit = A.Account({"uid": "inherit", "realm": "cn", "accessToken": "x"})
out["inherit"] = {"vpc": inherit.vpc_endpoint, "source": inherit.vpc_source,
                  "saved": "vpcEndpoint" in inherit.to_dict()}
try:
    out["inherit"]["gateway"] = inherit.realm_config()["gateway"]
except Exception as exc:
    out["inherit"]["error"] = str(exc)
try:
    public = A.Account({"uid": "public", "realm": "cn", "accessToken": "x",
                        "vpcEndpoint": ""})
    out["public"] = {"vpc": public.vpc_endpoint, "source": public.vpc_source,
                     "gateway": public.realm_config()["gateway"]}
except Exception as exc:
    out["public_error"] = str(exc)
try:
    explicit = A.Account({"uid": "explicit", "realm": "cn", "accessToken": "x",
                          "vpcEndpoint": "other"})
    out["explicit"] = {"vpc": explicit.vpc_endpoint,
                       "gateway": explicit.realm_config()["gateway"]}
except Exception as exc:
    out["explicit_error"] = str(exc)
try:
    import tempfile
    pool = A.AccountPool(tempfile.mkdtemp(prefix="qd-vpc-env-login-"))
    out["login_url"] = pool.start_login(realm="cn")["authUrl"]
    A.http_json = lambda url, **kw: (
        {"token": "dt-pat", "expires_in": 3600000}
        if "jobToken" in url else {"id": "pat-user", "name": "PAT"})
    pat = pool.import_pat("pt-fixture", realm="cn")
    out["pat"] = {"vpc": pat.vpc_endpoint,
                  "gateway": pat.realm_config()["gateway"]}
except Exception as exc:
    out["login_error"] = str(exc)
print(json.dumps(out, ensure_ascii=False))
'''
data = json.loads(run_py(CODE, {"QD_CN_VPC_ENDPOINT": "acme"}))
check("检测到环境变量", data["configured"] is True, data["configured"])
check("默认实例覆盖 realm_config_for",
      data.get("default_gateway") == "https://acme-gateway.vpc.qoder.com.cn",
      data.get("default_gateway"))
check("候选默认也走实例域",
      data.get("default_candidates") == ["https://acme-gateway.vpc.qoder.com.cn"],
      data.get("default_candidates"))
check("get_realm_config 仍是公网基线",
      data["base_gateway"] == "https://gateway.qoder.com.cn", data["base_gateway"])
check("缺省账号继承 env 实例",
      data["inherit"]["vpc"] == "acme"
      and data["inherit"]["source"] == "env"
      and data["inherit"]["gateway"] == "https://acme-gateway.vpc.qoder.com.cn",
      data.get("inherit"))
check("继承账号保存不写 vpcEndpoint",
      data["inherit"]["saved"] is False, data["inherit"])
check("显式空串覆盖 env 走公网",
      data["public"]["vpc"] == ""
      and data["public"]["source"] == "public"
      and data["public"]["gateway"] == "https://gateway.qoder.com.cn",
      data.get("public"))
check("显式实例覆盖 env",
      data["explicit"]["gateway"] == "https://other-gateway.vpc.qoder.com.cn",
      data.get("explicit"))
check("新增 OAuth 默认走 env 实例",
      data.get("login_url", "").startswith(
          "https://acme.vpc.qoder.com.cn/device/selectAccounts"),
      data.get("login_url"))
check("新增 PAT 默认走 env 实例",
      data.get("pat", {}).get("gateway")
      == "https://acme-gateway.vpc.qoder.com.cn", data.get("pat"))

plain = json.loads(run_py(CODE, {"QD_CN_VPC_ENDPOINT": ""}))
check("未设置变量时没有默认",
      plain["configured"] is False and plain["inherit"]["gateway"]
      == "https://gateway.qoder.com.cn", plain.get("inherit"))
check("未设置变量时新增 OAuth 走公网",
      plain.get("login_url", "").startswith(
          "https://qoder.com.cn/device/selectAccounts"),
      plain.get("login_url"))
check("未设置变量时新增 PAT 走公网",
      plain.get("pat", {}).get("gateway")
      == "https://gateway.qoder.com.cn", plain.get("pat"))

bad_env = json.loads(run_py(CODE, {"QD_CN_VPC_ENDPOINT": "bad host"}))
check("非法旧值不会让进程起不来", bad_env["configured"] is True
      and bad_env["error"], (bad_env["configured"], bad_env["error"]))
check("非法 env：默认解析抛错",
      "default_error" in bad_env, bad_env.get("default_error"))
check("非法 env：继承账号 fail-closed",
      bad_env["inherit"].get("source") == "error"
      and bad_env["inherit"].get("vpc") == "", bad_env.get("inherit"))
check("非法 env：显式实例仍可用",
      bad_env["explicit"]["gateway"] == "https://other-gateway.vpc.qoder.com.cn",
      bad_env.get("explicit"))
check("非法 env：显式公网仍可用",
      bad_env["public"]["gateway"] == "https://gateway.qoder.com.cn",
      bad_env.get("public"))
check("非法 env：新增 OAuth 明确报错，不静默回公网",
      "login_error" in bad_env, bad_env.get("login_url"))

print("\n[vpc] 5) 从账号 domain 反推实例（老账号升级路径）")
DERIVE = {
    "acme.vpc.qoder.com.cn": "acme",
    "acme-gateway.vpc.qoder.com.cn": "acme",
    "acme-openapi.vpc.qoder.com.cn": "acme",
    "ACME.VPC.QODER.COM.CN": "acme",
    "qoder.com.cn": "",
    "": "",
    "-acme.vpc.qoder.com.cn": "",
    "acme.vpc.qoder.com.cn.evil.test": "",
    ("a" * 60) + ".vpc.qoder.com.cn": "",
}
for domain, want in DERIVE.items():
    got = A._vpc_instance_from_domain(domain)
    check("domain %r -> %r" % (domain, want), got == want, got)

print("\n[vpc] 6) SSRF：内网解析时只放行账号登记的专属域")
CODE_SSRF = r'''
import json
import socket

_orig = socket.getaddrinfo


def fake(host, port, *args, **kwargs):
    if str(host).lower().endswith(".vpc.qoder.com.cn"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                 ("10.20.30.40", port or 443))]
    return _orig(host, port, *args, **kwargs)


socket.getaddrinfo = fake
import qoder_accounts as A
import qoder_proxy as P

A.Account({"uid": "vpc-fixture", "realm": "cn", "accessToken": "t",
           "vpcEndpoint": "acme"})
res = {}
for name, fn in (("accounts", A.validate_public_http_url),
                 ("proxy", P.validate_public_http_url)):
    def probe(url):
        try:
            fn(url)
            return "ok"
        except Exception as exc:
            return "blocked:%s" % exc
    res[name + "_vpc"] = probe(
        "https://acme-openapi.vpc.qoder.com.cn/api/v1/userinfo")
    res[name + "_other"] = probe("https://other.vpc.qoder.com.cn/api/v1/userinfo")
print(json.dumps(res, ensure_ascii=False))
'''
ssrf = json.loads(run_py(CODE_SSRF, {}))
check("qoder_accounts 放行账号登记的专属域（即使解析到内网）",
      ssrf.get("accounts_vpc") == "ok", ssrf.get("accounts_vpc"))
check("qoder_proxy 放行账号登记的专属域",
      ssrf.get("proxy_vpc") == "ok", ssrf.get("proxy_vpc"))
check("未登记的 vpc 域名仍按内网目标拒绝",
      str(ssrf.get("accounts_other", "")).startswith("blocked:"),
      ssrf.get("accounts_other"))
check("qoder_proxy 同样拒绝未登记的同后缀域名",
      str(ssrf.get("proxy_other", "")).startswith("blocked:"),
      ssrf.get("proxy_other"))

print("\n[vpc] 7) fake-IP / IPv6 映射判定不变")
CODE_FAKE = r'''
import json, socket
import qoder_accounts as A
import qoder_proxy as P
results = {}
for label, ips in (
    ("fake", ["198.18.0.45", "::ffff:0:c612:2d", "::ffff:198.18.0.45"]),
    ("private", ["198.18.0.45", "10.20.30.40"]),
    ("mapped_private", ["::ffff:0:a00:1"]),
):
    socket.getaddrinfo = lambda host, port, **kw: [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
        for ip in ips]
    for name, mod in (("accounts", A), ("proxy", P)):
        try:
            mod.validate_public_http_url("https://fixture.invalid/path")
            results[name + "_" + label] = True
        except ValueError:
            results[name + "_" + label] = False
print(json.dumps(results))
'''
fake = json.loads(run_py(CODE_FAKE, {}))
for name in ("accounts", "proxy"):
    check(name + " 接受 IPv4/mapped/translated fake-IP", fake[name + "_fake"])
    check(name + " 拒绝 fake-IP 混入私网", not fake[name + "_private"])
    check(name + " 拒绝 translated 私网地址", not fake[name + "_mapped_private"])

print("\n[vpc] 8) 账号级隔离：重定向 / 模型发现 / 额度缓存 / CLI 目录")
CODE_ISOLATION = r'''
import json, tempfile, urllib.error, urllib.request
from unittest import mock
import qoder_accounts as A

account = A.Account({"uid": "fixture", "realm": "cn", "accessToken": "fixture-token",
                     "vpcEndpoint": "acme"})
other = A.Account({"uid": "other", "realm": "cn", "accessToken": "other-token",
                   "vpcEndpoint": "other"})
seen = []
def fake_http(url, **kwargs):
    seen.append(url)
    return {}
with tempfile.TemporaryDirectory() as root:
    A.save_credits_source(root, "cn", "https://openapi.qoder.com.cn",
                          "/api/v2/quota/usage")
    with mock.patch.object(A, "http_json", side_effect=fake_http):
        stale = account._fetch_credits_via_source(
            root, {"host": "https://openapi.qoder.com.cn",
                   "path": "/api/v2/quota/usage"})
        account.probe_credits_endpoints(root, limit=2)
        instance_seen = list(seen)
        before = len(seen)
        hint = account._other_realm_quota_hint()
        no_cross = len(seen) == before
        plain = A.Account({"uid": "plain", "realm": "intl", "accessToken": "t"})
        plain._other_realm_quota_hint()
        non_vpc_probes = len(seen) > before
handler = A._VpcRedirectHandler()
req = urllib.request.Request("https://acme-openapi.vpc.qoder.com.cn/start",
                             headers={"Authorization": "Bearer fixture-token"})
redirects = {}
for label, url in (
    ("own", "https://acme.vpc.qoder.com.cn/next"),
    ("other", "https://other.vpc.qoder.com.cn/next"),
    ("public", "https://openapi.qoder.com.cn/next"),
    ("http", "http://acme.vpc.qoder.com.cn/next"),
    ("port", "https://acme.vpc.qoder.com.cn:8443/next"),
):
    try:
        handler.redirect_request(req, None, 302, "Found", {}, url)
        redirects[label] = True
    except urllib.error.HTTPError:
        redirects[label] = False
print(json.dumps({"seen": instance_seen, "stale": stale, "no_cross": no_cross,
                  "hint": hint, "non_vpc_probes": non_vpc_probes,
                  "redirects": redirects,
                  "dirs": A.cli_auth_dirs("cn", "acme"),
                  "openapi": A.openapi_candidates("cn", account.realm_config()),
                  "intl": A.get_realm_config("intl")["gateway"]}))
'''
iso = json.loads(run_py(CODE_ISOLATION, {"QD_CN_OPENAPI": "https://openapi.qoder.com.cn"}))
check("旧公网额度来源缓存不再出站",
      iso["stale"] is None and iso["seen"]
      and all(url.startswith("https://acme-openapi.vpc.qoder.com.cn/")
              for url in iso["seen"]), iso.get("seen"))
check("VPC 账号关闭跨区域令牌探测",
      iso["no_cross"] and iso["hint"] == "", (iso.get("no_cross"), iso.get("hint")))
check("非 VPC 账号的跨区诊断不受影响", iso.get("non_vpc_probes") is True,
      iso.get("non_vpc_probes"))
for label, allowed in iso["redirects"].items():
    check("redirect " + label, allowed == (label == "own"), allowed)
check("CLI 凭据目录优先实例目录且保留旧目录",
      len(iso["dirs"]) == 2
      and "/.vpc/acme/.auth" in iso["dirs"][0].replace("\\", "/")
      and iso["dirs"][1].replace("\\", "/").endswith("/.qoder-cn/.auth"),
      iso.get("dirs"))
check("账号级 VPC 优先于旧 QD_CN_OPENAPI 覆盖",
      iso["openapi"] == ["https://acme-openapi.vpc.qoder.com.cn"],
      iso.get("openapi"))
check("INTL 默认网关保持公网", "vpc.qoder.com.cn" not in iso["intl"], iso["intl"])
with open(os.path.join(ROOT, "qoder_proxy.py"), encoding="utf-8") as fh:
    inference_source = fh.read()
check("VPC 推理同样使用隔离重定向 opener",
      "resp = qoder_accounts._opener_for_request().open(req, timeout=600)"
      in inference_source)
check("模型发现使用隔离 opener",
      "qoder_accounts._opener_for_request().open(req, timeout=15)"
      in inference_source)
check("模型发现不再使用裸 urlopen",
      "with urllib.request.urlopen(req, timeout=15) as resp:" not in inference_source)

print("\n[vpc] 9) 跨实例重定向 A -> B 必须拒绝")
A.Account({"uid": "a", "realm": "cn", "accessToken": "t", "vpcEndpoint": "fixture-a"})
A.Account({"uid": "b", "realm": "cn", "accessToken": "t", "vpcEndpoint": "fixture-b"})
handler = A._VpcRedirectHandler()
req = urllib.request.Request(
    "https://fixture-a-openapi.vpc.qoder.com.cn/x",
    headers={"Authorization": "Bearer SECRET-A"})
try:
    new = handler.redirect_request(
        req, None, 302, "Found", {},
        "https://fixture-b-openapi.vpc.qoder.com.cn/y")
    blocked = False
except urllib.error.HTTPError:
    blocked = True
    new = None
check("A -> B 被拒绝", blocked)
check("A -> A 官网允许",
      handler.redirect_request(req, None, 302, "Found", {},
                               "https://fixture-a.vpc.qoder.com.cn/ok") is not None)
explicit_handler = A._VpcRedirectHandler(
    ["fixture-b.vpc.qoder.com.cn", "fixture-b-openapi.vpc.qoder.com.cn",
     "fixture-b-gateway.vpc.qoder.com.cn"])
try:
    explicit_handler.redirect_request(
        req, None, 302, "Found", {},
        "https://fixture-b.vpc.qoder.com.cn/x")
    explicit_blocked = False
except urllib.error.HTTPError:
    explicit_blocked = True
check("显式 allowlist 与源实例不匹配时 fail closed", explicit_blocked)

finish()
