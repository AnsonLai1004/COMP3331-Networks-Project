"""
    Sample code for Receiver
    Python 3
    Usage: python3 receiver.py receiver_port sender_port FileReceived.txt flp rlp
    coding: utf-8

    Notes:
        Try to run the server first with the command:
            python3 receiver.py 9000 10000 FileReceived.txt 1 1
            python3 receiver.py 9000 10000 FileReceived.txt 0 0
            python3 receiver.py 9000 10000 FileReceived.txt 0.5 0
            python3 receiver.py 9000 10000 FileReceived.txt 0 0.5
            python3 receiver.py 9000 10000 FileReceived.txt 0.5 0.5
            python3 receiver.py 56007 59606 FileToReceive.txt 0 0
        Then run the sender:
            python3 sender.py 11000 9000 FileToReceived.txt 1000 1
            python3 sender.py 11000 9000 random1.txt 3000 1
            python3 sender.py 11000 9000 random2.txt 1000 100
            python3 sender.py 11000 9000 file.txt 3000 1
            python3 sender.py 11000 9000 asyoulik.txt 4000 1
            python3 sender.py 59606 56007 asyoulik.txt 5000 100

    Author: Rui Li (Tutor for COMP3331/9331)
"""
# here are the libs you may find it useful:
import datetime, time  # to calculate the time delta of packet transmission
import logging, sys  # to write the log
import socket  # Core lib, to send packet via UDP socket
from threading import Thread  # (Optional)threading will make the timer easily implemented
import random  # for flp and rlp function
import segment 
from dataclasses import dataclass

BUFFERSIZE = 1024
MAX_SEQNO = 2 ** 16 - 1
# receiver state
CLOSED = 0
LISTEN = 1
ESTABLISHED = 2
TIME_WAIT = 3


@dataclass
class Buffer_obj:
    seqno: int
    exp_next_seqno: int
    data: bytes
    
class Receiver:
    def __init__(self, receiver_port: int, sender_port: int, filename: str, flp: float, rlp: float) -> None:
        '''
        The server will be able to receive the file from the sender via UDP
        :param receiver_port: the UDP port number to be used by the receiver to receive PTP segments from the sender.
        :param sender_port: the UDP port number to be used by the sender to send PTP segments to the receiver.
        :param filename: the name of the text file into which the text sent by the sender should be stored
        :param flp: forward loss probability, which is the probability that any segment in the forward direction (Data, FIN, SYN) is lost.
        :param rlp: reverse loss probability, which is the probability of a segment in the reverse direction (i.e., ACKs) being lost.

        '''
        self.address = "127.0.0.1"  # change it to 0.0.0.0 or public ipv4 address if want to test it between different computers
        self.receiver_port = int(receiver_port)
        self.sender_port = int(sender_port)
        self.server_address = (self.address, self.receiver_port)

        # init the UDP socket
        # define socket for the server side and bind address
        logging.debug(f"The sender is using the address {self.server_address} to receive message!")
        self.receiver_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.receiver_socket.bind(self.server_address)
        
        # init variables 
        self.state = CLOSED
        self.filename = filename
        self.flp = float(flp)
        self.rlp = float(rlp)
        self.isn = None
        # for storing all the bytes received
        self.buffer = []
        
        # 9. create log file
        # create a logger object
        self.logging = logging.getLogger(__name__)
        self.handler = logging.FileHandler("Receiver_log.txt", mode = 'w')
        self.formatter = logging.Formatter('%(message)s')
        self.handler.setFormatter(self.formatter)
        self.logging.addHandler(self.handler)
        self.logging.setLevel(logging.INFO)
        self.start_time = None
        self.total_data_received = 0
        self.total_segment_received = 0
        self.dup_segment_received = 0
        self.dropped_data_segment = 0
        self.dropped_ack_segment = 0
        pass

    def run(self) -> None:
        '''
        This function contain the main logic of the receiver
        '''
        self.state = LISTEN
        # start receive data:
        while True:
            if self.state == TIME_WAIT:
                # for closing: wait 2 MSL
                self.receiver_socket.settimeout(2)      
            try:
                # try to receive any incoming message from the sender
                incoming_message, sender_address = self.receiver_socket.recvfrom(BUFFERSIZE)
                curr_time = time.time()
            except:
                # for closing socket
                self.state = CLOSED 
                self.receiver_socket.close()
                break
            segment_type, segment_seqno, data = segment.unpack_segment(incoming_message)
            if segment_type == segment.SYN:
                self.start_time = curr_time
            # Simulate packet loss for any segment in the forward direction
            if segment_type != segment.RESET and random.random() < self.flp:
                if segment_type == segment.DATA:
                    self.dropped_data_segment += 1
                self.drp_log(curr_time, segment_type, segment_seqno, len(data))
                continue

            self.write_to_log(curr_time, segment_type, segment_seqno, len(data)) 
            
            if segment_type == segment.SYN:
                self.state = ESTABLISHED
                self.isn = segment_seqno
                segment_seqno += 1
            elif segment_type == segment.DATA:
                # creat buffer object and append to buffer
                self.append_to_buffer(Buffer_obj(segment_seqno, (segment_seqno + len(data)) % (2 ** 16), data))
                segment_seqno += len(data)
            elif segment_type == segment.FIN:    
                segment_seqno += 1
                self.state = TIME_WAIT
            elif segment_type == segment.RESET:
                # close socket
                self.state = CLOSED 
                self.receiver_socket.close()
                break
            
            segment_seqno = segment_seqno % (2 ** 16)
            
            # Simulate packet loss for any segment in the reverse direction
            if random.random() < self.rlp:
                self.dropped_ack_segment += 1
                self.drp_log(time.time(), segment.ACK, segment_seqno, 0)
                continue
            
            # reply "ACK" once receive any message from sender
            reply_message = segment.pack_segment(segment.ACK, segment_seqno, None)
            self.receiver_socket.sendto(reply_message, sender_address)
            self.write_to_log(time.time(), segment.ACK, segment_seqno, 0)
            
        # write from buffer to txt file
        self.write_to_txt()
        self.logging.info(f"Amount of (original) Data Received (in bytes) - does not include retransmitted data: {self.total_data_received}")
        self.logging.info(f"Number of (original) Data Segments Received: {self.total_segment_received}")
        self.logging.info(f"Number of duplicate Data Segments Received: {self.dup_segment_received}")
        self.logging.info(f"Number of Data segments dropped: {self.dropped_data_segment}")
        self.logging.info(f"Number of ACK segments dropped: {self.dropped_ack_segment}")
        
        return
        
    # helper function: write all the bytes in buffer to file    
    def write_to_txt(self):
        with open(self.filename, 'wb') as file:
            for item in self.buffer:
                file.write(item.data)
    
    # helper function: add received packets to buffer in the right order, ignore duplicate packets 
    def append_to_buffer(self, packet):
        # if buffer empty or seqno equal or larger than the last element exp_seqno, append
        seqno = packet.seqno
        for item in self.buffer:
            if item.seqno == seqno:
                self.dup_segment_received += 1
                return
        
        # for logging
        self.total_segment_received += 1
        self.total_data_received += len(packet.data)
        
        if not self.buffer or seqno >= self.buffer[-1].exp_next_seqno:
            self.buffer.append(packet)
        elif seqno < self.buffer[-1].exp_next_seqno:
            for i, item in enumerate(self.buffer):
                if item.exp_next_seqno == seqno:
                    self.buffer.insert(i, packet)
        return
    
    def write_to_log(self, curr_time, type, seqno, len):
        current_time = round((curr_time - self.start_time) * 1000, 2)
        if type == segment.SYN:
            self.logging.info(f"rcv\t0\tSYN\t{seqno}\t0")
        elif type == segment.ACK:
            self.logging.info(f"snd\t{current_time}\tACK\t{seqno}\t0")
        elif type == segment.DATA:
            self.logging.info(f"rcv\t{current_time}\tDATA\t{seqno}\t{len}")
        elif type == segment.FIN:
            self.logging.info(f"rcv\t{current_time}\tFIN\t{seqno}\t0")
        elif type == segment.RESET:
            self.logging.info(f"rcv\t{current_time}\tRESET\t0\t0")
    
    def drp_log(self, curr_time, type, seqno, len):
        current_time = round((curr_time - self.start_time) * 1000, 2)
        if type == segment.SYN:
            self.logging.info(f"drp\t0\tSYN\t{seqno}\t0")
        elif type == segment.ACK:
            self.logging.info(f"drp\t{current_time}\tACK\t{seqno}\t0")
        elif type == segment.DATA:
            self.logging.info(f"drp\t{current_time}\tDATA\t{seqno}\t{len}")
        elif type == segment.FIN:
            self.logging.info(f"drp\t{current_time}\tFIN\t{seqno}\t0")            

if __name__ == '__main__':
    # logging is useful for the log part: https://docs.python.org/3/library/logging.html
    logging.basicConfig(
        # filename="Receiver_log.txt",
        stream=sys.stderr,
        level=logging.DEBUG,
        format='%(asctime)s,%(msecs)03d %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S')

    if len(sys.argv) != 6:
        print(
            "\n===== Error usage, python3 receiver.py receiver_port sender_port FileReceived.txt flp rlp ======\n")
        exit(0)

    receiver = Receiver(*sys.argv[1:])    
    receiver.run()
