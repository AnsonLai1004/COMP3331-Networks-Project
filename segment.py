# types
DATA = 0
ACK = 1
SYN = 2
FIN = 3
RESET = 4

# create segment by adding type and seqno header to data 
def pack_segment(type, seqno, data):
    type = type.to_bytes(2, 'big')
    seqno = seqno.to_bytes(2, 'big')
    if data == None:
        return type + seqno
    return type + seqno + data

# extract information from a packed segment, return type, seqno, data 
def unpack_segment(data):
    type = data[:2]
    seqno = data[2:4]
    data = data[4:]
    type = int.from_bytes(type, 'big')
    seqno = int.from_bytes(seqno, 'big')
    return type, seqno, data
