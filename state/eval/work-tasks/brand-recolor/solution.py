import json,re
pal=json.load(open("palette.json"))["colors"]
m={"#000":pal[0],"#fff":pal[1],"#ff0000":pal[2]}
t=open("style.css").read()
for k,v in m.items(): t=t.replace(k,v)
open("style.css","w").write(t)
