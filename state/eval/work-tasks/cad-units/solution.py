import struct

# Reference solution: read the binary STL in centimetres and write it back in millimetres (x10).
data = open("plate.stl", "rb").read()
n = struct.unpack("<I", data[80:84])[0]
out = bytearray(data[:84])
for i in range(n):
    rec = data[84 + 50 * i:84 + 50 * (i + 1)]
    normal = rec[:12]
    verts = struct.unpack("<9f", rec[12:48])
    out += normal + struct.pack("<9f", *(v * 10 for v in verts)) + rec[48:50]
open("plate.stl", "wb").write(bytes(out))
