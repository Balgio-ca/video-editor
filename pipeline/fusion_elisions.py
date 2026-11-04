"""Refusionne les élisions séparées par Whisper (« l » + « 'ingénierie » -> « l'ingénierie ») dans
words.json d'un sujet, et recale les index d'edit.json. Usage : fusion_elisions.py <projet> <sujet>"""
import json, sys
W = f"work/{sys.argv[1]}/{sys.argv[2]}"
words = json.load(open(f"{W}/words.json"))["words"]
ELIS = {"c", "d", "j", "l", "m", "n", "s", "t", "qu", "jusqu", "lorsqu", "puisqu", "quelqu"}
new, m = [], {}
i = 0
while i < len(words):
    w = words[i]
    if w["text"].lower() in ELIS and i + 1 < len(words) and words[i + 1]["text"].startswith("'"):
        nxt = words[i + 1]
        new.append({"i": len(new), "text": w["text"] + nxt["text"], "start": w["start"], "end": nxt["end"]})
        m[i] = m[i + 1] = len(new) - 1; i += 2
    else:
        new.append({"i": len(new), "text": w["text"], "start": w["start"], "end": w["end"]})
        m[i] = len(new) - 1; i += 1
if len(new) == len(words):
    print("aucune élision à fusionner"); sys.exit(0)
e = json.load(open(f"{W}/edit.json"))
e["corrections"] = {str(m[int(k)]): v for k, v in e.get("corrections", {}).items()}
pages = []
for p in e["pages"]:
    mots = sorted(set(m[i] for i in p["mots"]))
    if pages and set(mots) & set(pages[-1]["mots"]):
        pages[-1]["mots"] = sorted(set(pages[-1]["mots"]) | set(mots))
    else:
        pages.append({"mots": mots, "style": p.get("style", "normal")})
e["pages"] = pages
for b in e.get("broll", []): b["debut_mot"], b["fin_mot"] = m[b["debut_mot"]], m[b["fin_mot"]]
for x in e.get("impacts", []): x["mot"] = m[x["mot"]]
for x in e.get("stickers", []): x["mot"] = m[x["mot"]]
for c in e.get("coupes", []): c["debut_mot"], c["fin_mot"] = m[c["debut_mot"]], m[c["fin_mot"]]
if "accroche" in e: e["accroche"]["fin_mot"] = m[e["accroche"]["fin_mot"]]
json.dump({"words": new}, open(f"{W}/words.json", "w"), ensure_ascii=False, indent=1)
json.dump(e, open(f"{W}/edit.json", "w"), ensure_ascii=False, indent=1)
print(f"{len(words)} -> {len(new)} mots, montage recalé")
