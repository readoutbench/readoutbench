"""Apply card corrections (JSONL of nct_id plus the fields that change, and a fix_note) to the cards.

usage: python3 -I apply_fixes.py <cards.jsonl> <fixes.jsonl> <out cards.jsonl>
The fix note is appended to the card's notes."""
import json
import sys

cards_p, fixes_p, out_p = sys.argv[1:4]
fixes = {json.loads(l)["nct_id"]: json.loads(l) for l in open(fixes_p) if l.strip()}
n = 0
with open(out_p, "w") as fh:
    for line in open(cards_p):
        if not line.strip():
            continue
        c = json.loads(line)
        f = fixes.get(c["nct_id"])
        if f:
            note = f.get("fix_note")
            c.update({k: v for k, v in f.items() if k not in ("nct_id", "fix_note")})
            if note:
                c["notes"] = ((c.get("notes") or "") + " Fixed: " + note).strip()
            n += 1
        fh.write(json.dumps(c, ensure_ascii=False) + "\n")
print(n, "cards fixed of", len(fixes))
