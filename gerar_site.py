#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera a vitrine Introspecta (docs/index.html) a partir da API do Mercado Livre.

Variaveis de ambiente (definidas em atualizar.bat, que NAO vai ao GitHub):
  ML_CLIENT_ID, ML_CLIENT_SECRET  -> app do Mercado Livre (client_credentials)
  ML_MATT_TOOL, ML_MATT_WORD      -> tags de afiliado
Uso:
  python gerar_site.py          -> coleta na API e gera o site
  python gerar_site.py --demo   -> gera previa com itens ficticios (nao usa API)
"""
import json, os, sys, time, unicodedata, urllib.parse, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
DOCS = BASE / "docs"
API = "https://api.mercadolibre.com"
LOG = []
AMOSTRA = []
ESTAT = {}


def conta(k):
    ESTAT[k] = ESTAT.get(k, 0) + 1


def log(msg):
    print(msg)
    LOG.append(msg)


def norm(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def tem_alguma(titulo, palavras):
    t = norm(titulo)
    return any(norm(p) in t for p in palavras)


# ---------------------------------------------------------------- API
def http_json(url, data=None, headers=None, tentativas=3):
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and i < tentativas - 1:
                time.sleep(2 * (i + 1))
                continue
            if e.code != 404:
                log(f"  HTTP {e.code} em {url.split('?')[0]}")
            return None
        except Exception as e:
            if i < tentativas - 1:
                time.sleep(2)
                continue
            log(f"  erro {e} em {url.split('?')[0]}")
            return None


def obter_token():
    cid, sec = os.environ.get("ML_CLIENT_ID"), os.environ.get("ML_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("Defina ML_CLIENT_ID e ML_CLIENT_SECRET (veja atualizar.bat).")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode()
    r = http_json(API + "/oauth/token", data=body, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    if not r or "access_token" not in r:
        sys.exit("Nao foi possivel obter o token do Mercado Livre.")
    return r["access_token"]


class ML:
    def __init__(self, token):
        self.h = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        self.cache_vend = {}

    def get(self, path, **params):
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        time.sleep(0.25)  # evita o limite de chamadas (HTTP 429)
        return http_json(url, headers=self.h)

    def vendedor(self, uid):
        if uid in self.cache_vend:
            return self.cache_vend[uid]
        u = self.get(f"/users/{uid}") or {}
        rep = u.get("seller_reputation") or {}
        tr = rep.get("transactions") or {}
        nivel = rep.get("level_id") or ""
        info = {
            "nome": u.get("nickname", ""),
            "power": rep.get("power_seller_status"),  # platinum / gold / silver / None
            "verde": str(nivel).endswith("green"),
            "vendas": tr.get("completed", 0) or 0,
            "positivas": round(100 * ((tr.get("ratings") or {}).get("positive") or 0)),
        }
        self.cache_vend[uid] = info
        return info


def nota_loja(oficial, v):
    """0 = nao aceita. Maior = melhor reputacao."""
    if oficial:
        return 4
    if v["power"] == "platinum":
        return 3
    if v["power"] == "gold":
        return 2
    if v["verde"] and v["vendas"] >= 100:
        return 1
    return 0


def link_afiliado(permalink):
    tool, word = os.environ.get("ML_MATT_TOOL"), os.environ.get("ML_MATT_WORD")
    if not tool or not word:
        return permalink
    sep = "&" if "?" in permalink else "?"
    return f"{permalink}{sep}matt_tool={tool}&matt_word={word}"


def melhor_oferta(ml, prod_id, cat):
    r = ml.get(f"/products/{prod_id}/items", limit=20) or {}
    ofertas = r.get("results", r) if isinstance(r, dict) else r
    if not ofertas:  # sem lista de ofertas: usa a oferta vencedora (buy box) do produto
        p = ml.get(f"/products/{prod_id}") or {}
        bb = p.get("buy_box_winner") or {}
        if bb:
            if not AMOSTRA:
                AMOSTRA.append(json.dumps(bb, ensure_ascii=False)[:900])
                log("  amostra buy_box_winner: " + AMOSTRA[0])
            link = bb.get("permalink") or p.get("permalink") or f"https://www.mercadolivre.com.br/p/{prod_id}"
            ofertas = [{**bb, "permalink": link}]
    melhor = None
    if not ofertas:
        conta("sem_ofertas_na_api")
    for o in ofertas or []:
        if o.get("condition", "new") != "new":
            conta("usado")
            continue
        preco = o.get("price")
        if not preco or preco < cat.get("preco_min", 0):
            conta("preco_abaixo_do_minimo")
            continue
        oficial = bool(o.get("official_store_id"))
        v = ml.vendedor(o.get("seller_id"))
        nota = nota_loja(oficial, v)
        if nota == 0:
            conta("loja_sem_reputacao")
            continue
        iid = str(o.get("item_id") or o.get("id") or "")
        link = o.get("permalink") or (f"https://produto.mercadolivre.com.br/MLB-{iid[3:]}" if iid.startswith("MLB") else "")
        if not link:
            conta("sem_link")
            continue
        orig = o.get("original_price")
        cand = {"preco": float(preco), "nota": nota, "oficial": oficial, "loja": v["nome"], "link": link, "item_id": iid,
                "original": float(orig) if orig else 0, "power": v["power"], "positivas": v["positivas"], "vendas": v["vendas"]}
        if not melhor or (cand["nota"], -cand["preco"]) > (melhor["nota"], -melhor["preco"]):
            melhor = cand
    return melhor


def desconto(preco, original):
    """% de desconto real; ignora descontos pequenos demais ou suspeitos (>70%)."""
    if not original or original <= preco:
        return 0
    d = round(100 * (1 - preco / original))
    return d if 8 <= d <= 70 else 0


def rotulo_loja(of):
    if of["oficial"]:
        return "Loja oficial"
    return {"platinum": "MercadoLíder Platinum", "gold": "MercadoLíder Gold"}.get(of["power"], "Boa reputação")


def montar_destaques(cfg, todos):
    """Promocoes e melhores lojas, escolhidas entre TODOS os itens coletados."""
    n = cfg.get("destaques_qtd", 8)
    itens = [i for lista in todos.values() for i in lista]
    # promocoes: maior desconto; so marcas conhecidas ou loja oficial
    promos = [i for i in itens if i.get("desconto", 0) and (i.get("marca") or i.get("oficial"))]
    promos.sort(key=lambda x: (-x["desconto"], -x["nota"], x["preco"]))
    # melhores lojas: oficial/Platinum, mais % de avaliacoes positivas e mais vendas; max 2 por loja
    boas = [i for i in itens if i.get("nota", 0) >= 3]
    boas.sort(key=lambda x: (-x.get("positivas", 0), -x.get("vendas", 0), -x["qualidade"], x["preco"]))
    lojas, por_loja = [], {}
    for i in boas:
        if por_loja.get(i["loja"], 0) < 2:
            lojas.append(i)
            por_loja[i["loja"]] = por_loja.get(i["loja"], 0) + 1
    vistos, p2 = set(), []
    for i in promos:
        if i["id"] not in vistos:
            vistos.add(i["id"]); p2.append(i)
    return {"promocoes": p2[:n], "lojas": lojas[:n]}


def coletar(cfg):
    ml = ML(obter_token())
    premium = cfg["marcas_premium"]
    resultado = {}
    for cat in cfg["categorias"]:
        log(f"[{cat['nome']}]")
        vistos, itens = set(), []
        ESTAT.clear()
        desc = {"titulo": 0, "sem_oferta": 0}
        for q in cat["queries"]:
            r = ml.get("/products/search", status="active", site_id="MLB", q=q, limit=20) or {}
            for p in r.get("results", []):
                pid = p.get("id")
                nome = p.get("name") or ""
                if pid in vistos:
                    continue
                vistos.add(pid)
                if (not tem_alguma(nome, cat["exigir_palavras"])
                        or tem_alguma(nome, cat["excluir"] + cfg["excluir_global"])):
                    desc["titulo"] += 1
                    continue
                of = melhor_oferta(ml, pid, cat)
                if not of or not of["link"]:
                    desc["sem_oferta"] += 1
                    continue
                pics = p.get("pictures") or []
                img = (pics[0].get("url") if pics else "") or ""
                marca = tem_alguma(nome, premium)
                itens.append({
                    "id": pid, "titulo": nome, "imagem": img.replace("http://", "https://"),
                    "preco": of["preco"], "loja": of["loja"], "oficial": of["oficial"],
                    "link": link_afiliado(of["link"]),
                    "qualidade": (2 if marca else 0) + (1 if of["oficial"] else 0),
                    "nota": of["nota"], "marca": marca, "categoria": cat["id"],
                    "original": of["original"], "desconto": desconto(of["preco"], of["original"]),
                    "reputacao": rotulo_loja(of), "positivas": of["positivas"], "vendas": of["vendas"],
                })
        # 1) qualidade  2) reputacao da loja  3) menor preco
        itens.sort(key=lambda x: (-x["qualidade"], -x["nota"], x["preco"]))
        log(f"  {len(itens)} aprovados | descartes: titulo={desc['titulo']} sem_oferta_valida={desc['sem_oferta']}")
        log("  motivos das ofertas: " + (", ".join(f"{k}={v}" for k, v in sorted(ESTAT.items())) or "-"))
        resultado[cat["id"]] = itens
    return resultado


# ---------------------------------------------------------------- demo
def demo(cfg):
    import random
    random.seed(7)
    nomes = ["Alfa", "Brisa", "Calma", "Duna", "Eco", "Folha", "Gota", "Horizonte", "Ilha", "Junco", "Lago", "Musgo", "Névoa", "Orvalho"]
    res = {}
    for cat in cfg["categorias"]:
        itens = []
        for i in range(14):
            n = f"{cat['nome']} {nomes[i]} (EXEMPLO)"
            itens.append({"id": f"{cat['id']}{i}", "titulo": n, "imagem": "", "preco": round(random.uniform(cat.get("preco_min", 50), cat.get("preco_min", 50) * 4), 2),
                          "loja": f"Loja Exemplo {i % 4}", "oficial": i % 3 == 0, "link": "#", "qualidade": 3 - i // 5, "nota": 4 - i % 3, "marca": i % 2 == 0,
                          "categoria": cat["id"], "original": 0, "desconto": (10 + i * 4) if i % 2 == 0 else 0, "reputacao": "Loja oficial" if i % 3 == 0 else "MercadoLíder Platinum",
                          "positivas": 99 - i % 5, "vendas": 5000 - i * 100})
        res[cat["id"]] = itens
    return res


# ---------------------------------------------------------------- rodizio
def aplicar_rodizio(cfg, todos, hist):
    n = cfg["itens_por_categoria"]
    saida = {}
    for cid, itens in todos.items():
        pool = itens[: n * 2]
        if cfg.get("rodizio", True):
            ordem = sorted(enumerate(pool), key=lambda t: (hist.get(t[1]["id"], 0), t[0]))
            escolhidos = [x for _, x in ordem[:n]]
            escolhidos.sort(key=lambda x: pool.index(x))
        else:
            escolhidos = pool[:n]
        for x in escolhidos:
            hist[x["id"]] = hist.get(x["id"], 0) + 1
        saida[cid] = escolhidos
    return saida


# ---------------------------------------------------------------- saida
def gerar_og(cfg):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), (245, 250, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([60, 60, 70, H - 60], fill=(31, 90, 150))

    def fonte(sz):
        for f in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
            try:
                return ImageFont.truetype(f, sz)
            except OSError:
                pass
        return ImageFont.load_default()
    d.text((110, 200), cfg["nome"], font=fonte(86), fill=(31, 90, 150))
    d.text((110, 330), cfg["slogan"], font=fonte(34), fill=(38, 48, 46))
    d.text((110, 520), "Ofertas do Mercado Livre", font=fonte(28), fill=(89, 100, 95))
    im.save(DOCS / "og.jpg", quality=88)


def escrever(cfg, por_cat, hist, rotulo_demo=False, destaques=None):
    DOCS.mkdir(exist_ok=True)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    ig = cfg.get("instagram", "").strip().lstrip("@")
    dados = {
        "nome": cfg["nome"], "atualizado": agora, "demo": rotulo_demo, "destaques": destaques or {"promocoes": [], "lojas": []},
        "categorias": [{"id": c["id"], "nome": c["nome"], "emoji": c["emoji"], "itens": por_cat.get(c["id"], [])} for c in cfg["categorias"]],
    }
    (DOCS / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    (DOCS / "historico.json").write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    (DOCS / "atualizado.txt").write_text(agora, encoding="utf-8")
    tpl = (BASE / "template.html").read_text(encoding="utf-8")
    subs = {
        "{{NOME}}": cfg["nome"], "{{SLOGAN}}": cfg["slogan"], "{{DESCRICAO}}": cfg["descricao"],
        "{{URL}}": cfg["url_site"], "{{INSTAGRAM}}": f"https://instagram.com/{ig}" if ig else "",
        "{{ATUALIZADO}}": agora,
        "{{DADOS}}": json.dumps(dados, ensure_ascii=False).replace("</", "<\\/"),
    }
    for k, v in subs.items():
        tpl = tpl.replace(k, v)
    (DOCS / "index.html").write_text(tpl, encoding="utf-8")
    import shutil
    if (BASE / "assets" / "logo.png").exists():
        shutil.copy(BASE / "assets" / "logo.png", DOCS / "logo.png")
    if (BASE / "assets" / "og.jpg").exists():
        shutil.copy(BASE / "assets" / "og.jpg", DOCS / "og.jpg")
    else:
        gerar_og(cfg)
    (DOCS / ".nojekyll").write_text("")


def diagnostico():
    """python gerar_site.py --diagnostico  -> grava diagnostico.txt (nao mostra chaves)."""
    ml = ML(obter_token())
    out = []

    def chama(path, **params):
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        try:
            req = urllib.request.Request(url, headers=ml.h)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "ignore")
        except Exception as e:
            return 0, str(e)

    consultas = ["abafador de ruido 3m peltor", "cobertor ponderado", "fidget cube", "quadro de rotina infantil"]
    for q in consultas:
        st, txt = chama("/products/search", status="active", site_id="MLB", q=q, limit=10)
        out.append(f"\n##### BUSCA '{q}' -> {st}")
        try:
            res = json.loads(txt).get("results", [])
        except Exception:
            out.append(txt[:300]); continue
        if res:
            out.append("1o resultado da busca (campos): " + json.dumps(res[0], ensure_ascii=False)[:700])
        ok = 0
        for p in res:
            pid = p.get("id")
            st2, t2 = chama(f"/products/{pid}/items")
            if st2 == 200:
                ok += 1
                if ok == 1:
                    out.append(f"  EXEMPLO COM OFERTA {pid} ({p.get('name')}):\n  " + t2[:1500])
            time.sleep(0.3)
        out.append(f"  -> {ok} de {len(res)} produtos com oferta em /items")
        time.sleep(1)

    # outras rotas, no primeiro produto popular
    st, txt = chama("/products/search", status="active", site_id="MLB", q="abafador de ruido 3m peltor", limit=1)
    try:
        pid = json.loads(txt)["results"][0]["id"]
    except Exception:
        pid = None
    if pid:
        out.append(f"\n##### rotas alternativas com {pid}")
        for path, params in ((f"/products/{pid}/items", {"site_id": "MLB"}),
                             ("/sites/MLB/search", {"product_id": pid}),
                             ("/sites/MLB/search", {"q": "abafador de ruido", "limit": 3}),
                             (f"/highlights/MLB/product/{pid}", {}),
                             ("/items", {"ids": "MLB3000000000"})):
            st, txt = chama(path, **params)
            out.append(f"-- {path} {params} -> {st}: {txt[:350]}")
            time.sleep(0.5)
    (BASE / "diagnostico.txt").write_text("\n".join(out), encoding="utf-8")
    print("Gravei diagnostico.txt - envie esse arquivo.")


def main():
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    hist_f = DOCS / "historico.json"
    hist = json.loads(hist_f.read_text(encoding="utf-8")) if hist_f.exists() else {}
    if "--diagnostico" in sys.argv:
        return diagnostico()
    modo_demo = "--demo" in sys.argv
    todos = demo(cfg) if modo_demo else coletar(cfg)
    destaques = montar_destaques(cfg, todos)
    por_cat = aplicar_rodizio(cfg, todos, hist)
    escrever(cfg, por_cat, hist, modo_demo, destaques)
    log(f"Promocoes: {len(destaques['promocoes'])} | Melhores lojas: {len(destaques['lojas'])}")
    if not modo_demo:
        (BASE / "log.txt").write_text("\n".join(LOG), encoding="utf-8")
    log("Site gerado em docs/index.html")


if __name__ == "__main__":
    main()
