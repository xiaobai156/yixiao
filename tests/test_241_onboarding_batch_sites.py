import json
from pathlib import Path


ROOT = Path(__file__).parents[1]

# name, url, direction, section, parser, source policy, baseline period, zodiac
BATCH = (
    ("艳绝千秋", "https://xxn08n.ehdj5-6w22v-nnwolc.cyou/topic/227231.html", "top", "已有站点", "family.strict_article", "http_documents", 241, "鸡"),
    ("临机制变", "https://ceiignp.pq2rb-obbkj-pccbdc.work:17455/topic/219976.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "羊"),
    ("峯回路转", "https://ceiignp.pq2rb-obbkj-pccbdc.work:17455/topic/254645.html", "bottom", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "羊"),
    ("众星攒月", "https://ceiignp.pq2rb-obbkj-pccbdc.work:17455/topic/225594.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "马"),
    ("傲慢少礼", "https://qygfz.3xaty-edprc-irhpzi.work/topic/216488.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 241, "虎"),
    ("猪猪宝贝", "https://pnyldyj.f5fm8-8nbq9-turdho.work:17455/topic/805230.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "兔"),
    ("小诸葛一", "https://vuqjgqn.gf1wh-uzjor-nptihu.cyou:17466/topic/233324.html", "top", "已有站点", "family.strict_article", "http_documents", 240, "兔"),
    ("小诸葛二", "https://vuqjgqn.gf1wh-uzjor-nptihu.cyou:17466/topic/233335.html", "top", "已有站点", "family.strict_article", "http_documents", 240, "虎"),
    ("名声狼藉", "https://myvvqq.dfzhr-czkkg-sixbte.cyou/topic/216335.html", "bottom", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "兔"),
    ("山海经", "https://dszduwm.mut9x-02add-ssrnio.cyou:17455/", "top", "已有站点", "family.anchored_section", "http_documents", 240, "虎"),
    ("荒诞不经", "https://4m6dz.c4jxe-b7ncl-nuqgsn.work/topic/211084.html", "top", "已有站点", "family.strict_article", "http_documents", 240, "兔"),
    ("东门盛自", "https://anvorcr.k1019-6t9jk-uywhen.cyou:17455/topic/206558.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "羊"),
    ("漳州怪哥", "https://acpfuzf.sunhs-vgjs2-rdeqxz.work:17455/topic/798454.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 241, "龙"),
    ("绿叶成阴", "https://acpfuzf.sunhs-vgjs2-rdeqxz.work:17455/topic/797847.html", "top", "已有站点", "family.anchored_section", "http_documents", 240, "羊"),
    ("丰衣足食", "https://acpfuzf.sunhs-vgjs2-rdeqxz.work:17455/topic/798106.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 241, "羊"),
    ("跟者必赚", "https://acpfuzf.sunhs-vgjs2-rdeqxz.work:17455/topic/796860.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "兔"),
    ("白云孤飞", "https://anvorcr.k1019-6t9jk-uywhen.cyou:17455/topic/206532.html", "bottom", "已有站点", "regex.86a7042b2c5a", "http_documents", 241, "鸡"),
    ("龙腾虎跃", "https://wmdhoki.6su07-7lpw6-gudkzl.xyz:16677/topic/727462.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "马"),
    ("任我发", "https://nndjqfa.j49dw-jxhod-olhmlv.work:17477/", "top", "已有站点", "regex.4190f98ab361", "http_documents", 241, "虎"),
    ("轩辕虚兴", "https://iviqwad.ynx3h-t6kyp-uepxwf.work:17455/topic/222101.html", "top", "已有站点", "family.strict_article", "http_documents", 240, "猴"),
    ("状元红", "https://zexytkv.y0zsf-hpscd-qblttr.work:17466/topic/451772.html", "bottom", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "兔"),
    ("卢九", "https://xclpqth.4zsn8-rzqg9-ulwfyu.work:17477/", "top", "已有站点", "family.anchored_section", "http_consensus", 241, "虎"),
    ("财富快车", "https://pegpvuw.e92s8-981z5-icstds.work:17488/", "top", "已有站点", "family.anchored_section", "http_documents", 240, "蛇"),
    ("学无止境", "https://uifesgo.1szw5-owiw3-hyunhb.work:17466/topic/766003.html", "top", "已有站点", "family.strict_article", "http_documents", 240, "狗"),
    ("推心置腹", "https://uifesgo.1szw5-owiw3-hyunhb.work:17466/topic/766010.html", "bottom", "已有站点", "family.strict_article", "http_documents", 240, "鼠"),
    ("金瓯无缺", "https://uifesgo.1szw5-owiw3-hyunhb.work:17466/topic/765972.html", "top", "已有站点", "family.strict_article", "http_documents", 240, "猪"),
    ("一呼百应", "https://omapney.yo5a5-q1ozu-olnlsr.work:17466/topic/728263.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "马"),
    ("百依百顺", "https://omapney.yo5a5-q1ozu-olnlsr.work:17466/topic/728293.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "鸡"),
    ("附录吸血", "https://jtrmhar.cwdc3-r5vqn-qzqasa.work:17455/topic/741214.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "猪"),
    ("兰烬缀梦", "https://jtrmhar.cwdc3-r5vqn-qzqasa.work:17455/topic/741211.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 240, "狗"),
    ("算法吟游", "https://jtrmhar.cwdc3-r5vqn-qzqasa.work:17455/topic/741192.html", "top", "已有站点", "regex.86a7042b2c5a", "http_documents", 241, "羊"),
    ("关心则乱", "https://jtrmhar.cwdc3-r5vqn-qzqasa.work:17455/topic/741187.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 240, "鸡"),
    ("九鹭非香", "https://jtrmhar.cwdc3-r5vqn-qzqasa.work:17455/topic/741087.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 240, "兔"),
    ("电子宠物", "https://jtrmhar.cwdc3-r5vqn-qzqasa.work:17455/topic/737721.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 240, "虎"),
    ("放虎归山", "https://fkwtjva.d7i0f-wgmak-ivbywl.work:17477/topic/727008.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 240, "兔"),
    ("四面楚歌", "https://oyshibi.f9qir-hee65-evlhav.work:17466/topic/549701.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 241, "龙"),
    ("横财富", "https://coezwpn.whizu-p4tnf-jznfdk.work:17455/", "top", "新增的站点", "family.anchored_section", "http_documents", 240, "牛"),
    ("八面玲珑", "https://coezwpn.whizu-p4tnf-jznfdk.work:17455/topic/732823.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 241, "猴"),
    ("外强中干", "https://yowwqvn.m2le0-0deh3-mriunz.work:17488/topic/732313.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 241, "虎"),
    ("顾名思义", "https://lzzmpmt.jc4do-1jsas-usenqe.work:17455/topic/546456.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 240, "兔"),
    ("旧岛听风", "https://ygaazoi.80f2d-qi0ig-gkygze.work:17488/topic/251186.html", "bottom", "新增的站点", "regex.86a7042b2c5a", "http_documents", 241, "虎"),
    ("情癌晚期", "https://ygaazoi.80f2d-qi0ig-gkygze.work:17488/topic/251166.html", "top", "新增的站点", "regex.86a7042b2c5a", "http_documents", 241, "牛"),
)


def test_authorized_241_batch_config_and_cache() -> None:
    configured = {row["name"]: row for row in json.loads((ROOT / "sites.json").read_text(encoding="utf-8"))}
    cached = {row["name"]: row for row in json.loads((ROOT / "recent_10_cache.json").read_text(encoding="utf-8"))["sites"]}

    assert len(BATCH) == 42
    assert sum(row[3] == "已有站点" for row in BATCH) == 31
    assert sum(row[3] == "新增的站点" for row in BATCH) == 11
    for name, url, direction, section, parser, policy, period, zodiac in BATCH:
        assert configured[name] == {
            "name": name,
            "pick": direction,
            "url": url,
            "section": section,
            "parser_id": parser,
            "source_policy": policy,
        }
        assert cached[name]["pick"] == direction
        assert cached[name]["section"] == section
        assert cached[name]["records"][0] == {"period": period, "zodiac": zodiac}

