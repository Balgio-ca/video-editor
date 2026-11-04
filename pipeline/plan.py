"""Affiche le plan d'édito d'un sujet : transcription indexée, texte gardé, fenêtres, coupes, styles.
Usage : plan.py <projet> <sujet>"""
import json, sys
W = f"work/{sys.argv[1]}/{sys.argv[2]}"
w = json.load(open(f"{W}/words.json"))["words"]
e = json.load(open(f"{W}/edit.json"))
cut = set()
for c in e.get("coupes", []): cut.update(range(c["debut_mot"], c["fin_mot"] + 1))
corr = e.get("corrections", {})
print("TRANSCRIPTION :", " ".join(f"{x['i']}:{x['text']}" for x in w))
print("\nGARDÉ :", " ".join(corr.get(str(x["i"]), x["text"]) for x in w if x["i"] not in cut and corr.get(str(x["i"]), x["text"])))
for k in ("titre_slug", "accroche", "broll", "impacts", "coupes", "note"):
    print(f"\n{k}:", json.dumps(e.get(k), ensure_ascii=False))
print("\nstyles:", [(p["style"], [w[i]["text"] for i in p["mots"]]) for p in e["pages"] if p.get("style", "normal") != "normal"])
print("parole gardée :", round(sum(x["end"] - x["start"] for x in w if x["i"] not in cut), 1), "s ; total", w[-1]["end"])
