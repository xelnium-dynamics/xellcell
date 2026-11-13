import sys
def pdf(lines):
    content = "BT /F1 11 Tf 50 780 Td " + " ".join(f"({l}) Tj 0 -14 Td" for l in lines) + " ET"
    objs = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>",
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            f"<</Length {len(content)}>>stream\n{content}\nendstream", "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offs = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj{o}endobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offs)
    return out + f"trailer<</Size {len(objs)+1}/Root 1 0 R>>\nstartxref\n{x}\n%%EOF\n"
lines = [l.strip("# ").strip() for l in open("cv.md", encoding="utf-8") if l.strip()][:40]
open("cv.pdf", "w", encoding="latin-1").write(pdf(lines))
