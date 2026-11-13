import struct
def box(path, x, y, z):
    V=[(0,0,0),(x,0,0),(x,y,0),(0,y,0),(0,0,z),(x,0,z),(x,y,z),(0,y,z)]
    F=[(0,1,2),(0,2,3),(4,6,5),(4,7,6),(0,5,1),(0,4,5),(1,6,2),(1,5,6),(2,7,3),(2,6,7),(3,4,0),(3,7,4)]
    b=bytearray(80)+struct.pack("<I",len(F))
    for f in F: b+=struct.pack("<3f",0,0,0)+b"".join(struct.pack("<3f",*V[i]) for i in f)+b"\0\0"
    open(path,"wb").write(bytes(b))
box("bracket.stl",40,20,5)
