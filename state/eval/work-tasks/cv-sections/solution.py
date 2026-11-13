import re
t=open("cv.md").read()
for s in ("Experience","Education","Skills"):
    if not re.search(rf"^## {s}", t, re.M): t += f"\n## {s}\n"
open("cv.md","w").write(t)
