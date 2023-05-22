"""
    Sample code for Sender (multi-threading)
    Python 3
    Usage: python3 sender.py receiver_port sender_port FileToSend.txt max_recv_win rto
    coding: utf-8

    Notes:
        Try to run the server first with the command:
            python3 receiver_template.py 9000 10000 FileReceived.txt 1 1
        Then run the sender:
            python3 sender_template.py 11000 9000 FileToReceived.txt 1000 1

    Author: Rui Li (Tutor for COMP3331/9331)
"""
# here are the libs you may find it useful:
import datetime, time  # to calculate the time delta of packet transmission
import logging, sys  # to write the log
import socket  # Core lib, to send packet via UDP socket
from threading import Thread  # (Optional)threading will make the timer easily implemented
import segment
from dataclasses import dataclass
import random
BUFFERSIZE = 1024
# sender states
CLOSED = 0
SYN_SENT = 1
ESTABLISHED = 2
CLOSING = 3
FIN_WAIT = 4

@dataclass
class Segment:
    type: int 
    seqno: int
    data: bytes
    exp_ack: int
    packet: bytes
    ack_received: bool = False

class Sender:
    def __init__(self, sender_port: int, receiver_port: int, filename: str, max_win: int, rot: int) -> None:
        '''
        The Sender will be able to connect the Receiver via UDP
        :param sender_port: the UDP port number to be used by the sender to send PTP segments to the receiver
        :param receiver_port: the UDP port number on which receiver is expecting to receive PTP segments from the sender
        :param filename: the name of the text file that must be transferred from sender to receiver using your reliable transport protocol.
        :param max_win: the maximum window size in bytes for the sender window.
        :param rot: the value of the retransmission timer in milliseconds. This should be an unsigned integer.
        '''
        self.sender_port = int(sender_port)
        self.receiver_port = int(receiver_port)
        self.sender_address = ("127.0.0.1", self.sender_port)
        self.receiver_address = ("127.0.0.1", self.receiver_port)

        # init the UDP socket
        logging.debug(f"The sender is using the address {self.sender_address}")
        self.sender_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        self.sender_socket.bind(self.sender_address)

        #  (Optional) start the listening sub-thread first
        self._is_active = True  # for the multi-threading
        # listen_thread = Thread(target=self.listen)
        # listen_thread.start()

        # todo add codes here
        self.state = CLOSED
        self.isn = random.randint(0, 2 ** 16 - 1) # range 0 to 65535
        self.curr_seqno = self.isn 
        self.filename = filename
        self.max_win = int(max_win)
        self.timeout = int(rot) / 1000
        
        # 4. sliding window
        self.unack_packets = []
        self.base_pknum = 0 # list pos
        self.next_pknum = 0 # list pos
        
        # 9. create log file
        # create a logger object
        self.logging = logging.getLogger(__name__)
        self.handler = logging.FileHandler("Sender_log.txt", mode = 'w')
        self.formatter = logging.Formatter('%(message)s')
        self.handler.setFormatter(self.formatter)
        self.logging.addHandler(self.handler)
        self.logging.setLevel(logging.INFO)
        # store the time when the SYN segment was sent
        self.start_time = None
        self.total_data = 0
        self.total_segment_sent = 0
        self.total_retransmitted = 0
        self.total_duplicate_ack = 0
        pass

    def ptp_open(self):
        # todo add/modify codes here
        # send a greeting message to receiver
        syn_segment = segment.pack_segment(segment.SYN, self.curr_seqno, None)
        success = False
        attempt = 0
        while success == False and attempt < 3:
            self.sender_socket.sendto(syn_segment, self.receiver_address)
            self.state = SYN_SENT
            self.start_time = time.time()
            self.write_to_log(0, segment.SYN, self.curr_seqno, 0)
            self.addtimer()
            if self.try_receive_ACK() == True:
                success = True
                self.state = ESTABLISHED
            attempt += 1
         
        if success == False:
            reset_segment = segment.pack_segment(segment.RESET, 0, None)
            self.sender_socket.sendto(reset_segment, self.receiver_address)
            self.write_to_log(time.time(), segment.RESET, 0, 0)
            self.state = CLOSED 
            self.sender_socket.close()    
        pass

    def ptp_send(self):
        # todo add codes here
        listen_thread = Thread(target=self.listen)
        listen_thread.start()
        file = open(self.filename, 'rb')
        
        while True: 
            
            
            # Check if the window is full
            if self.next_pknum < self.base_pknum + self.max_win / 1000:
                data = file.read(1000)
                if not data:
                    # end of file
                    break
                # send next packet 
                # Maximum segment size is 1000
                data_segment = segment.pack_segment(segment.DATA, self.curr_seqno, data)
                
                if not self.unack_packets or self.oldest_unack_inlist() == -1:
                    self.addtimer()
                self.sender_socket.sendto(data_segment, self.receiver_address)
                self.write_to_log(time.time(), segment.DATA, self.curr_seqno, len(data))
                self.total_data += len(data)
                self.total_segment_sent += 1
                packet = Segment(segment.DATA, self.curr_seqno, data, (self.curr_seqno + len(data)) % (2 ** 16), data_segment, False)
                self.curr_seqno = (self.curr_seqno + len(data)) % (2 ** 16)
                self.unack_packets.append(packet)
                
                self.next_pknum += 1

        self.state = CLOSING
         
        while self.oldest_unack_inlist() != -1:
            # wait
            self._is_active = True
        self._is_active = False
        listen_thread.join()
        pass 
        

    def ptp_close(self):
        
        self.curr_seqno = (self.curr_seqno + 1) % (2 ** 16)
        fin_segment = segment.pack_segment(segment.FIN, self.curr_seqno, None)
        success = False
        attempt = 0
        while success == False and attempt < 3:
            self.addtimer()
            self.sender_socket.sendto(fin_segment, self.receiver_address)
            self.state = FIN_WAIT
            self.write_to_log(time.time(), segment.FIN, self.curr_seqno, 0)
            
            if self.try_receive_ACK() == True:
                success = True
            attempt += 1
         
        if success == False:
            reset_segment = segment.pack_segment(segment.RESET, 0, None)
            self.sender_socket.sendto(reset_segment, self.receiver_address)
            self.write_to_log(time.time(), segment.RESET, 0, 0)
            self.state = CLOSED
        
        self.sender_socket.close()    
        pass

    def listen(self):
        '''(Multithread is used)listen the response from receiver'''
        logging.debug("Sub-thread for listening is running")
        while self._is_active:
            try:
                incoming_message, _ = self.sender_socket.recvfrom(BUFFERSIZE)
                segment_type, segment_seqno, data = segment.unpack_segment(incoming_message)
                if segment_type == segment.ACK:
                    self.write_to_log(time.time(), segment.ACK, segment_seqno, 0)
                    result = -1
                    while result == -1:
                        result = self.set_segment_received(segment_seqno)
                    self.base_pknum += 1
            except socket.timeout:
                # resend the oldest unack packet             
                pos = self.oldest_unack_inlist()
                if pos == -1:
                    continue
                else: 
                    packet = self.unack_packets[pos]
                    retransmit_segment = packet.packet
                    self.sender_socket.sendto(retransmit_segment, self.receiver_address)
                    self.write_to_log(time.time(), segment.DATA, packet.seqno, len(packet.data))
                    self.total_retransmitted += 1
                    self.addtimer()

    def run(self):
        '''
        This function contain the main logic of the receiver
        '''
        # todo add/modify codes here
        self.ptp_open()
        if self.state == ESTABLISHED:
            self.ptp_send()
        self.ptp_close()
        self.logging.info(f"Amount of (original) Data Transferred(in bytes)(excluding retransmissions): {self.total_data}")
        self.logging.info(f"Number of Data Segments Sent(excluding transmissions): {self.total_segment_sent}")
        self.logging.info(f"Number of Retransmitted Data Segments: {self.total_retransmitted}")
        self.logging.info(f"Number of Duplicate Acknowledgments received: {self.total_duplicate_ack}")

    # only used by ptp_open and ptp_close to receive ack for SYN and FIN
    def try_receive_ACK(self):
        try:
            incoming_segment, _ = self.sender_socket.recvfrom(BUFFERSIZE)
            segment_type, segment_seqno, data = segment.unpack_segment(incoming_segment)
            if segment_type == segment.ACK:
                self.write_to_log(time.time(), segment.ACK, segment_seqno, 0)
                self.curr_seqno = segment_seqno
                return True
        except socket.timeout: 
            return False

    def addtimer(self):
        self.sender_socket.settimeout(self.timeout)
    
    # return the first position in the list where the struct boolean is false
    def oldest_unack_inlist(self):
        for i, segment in enumerate(self.unack_packets):
            if not segment.ack_received:
                return i
        return -1

    def set_segment_received(self, ack_seqno):
        for segment in self.unack_packets:
            if segment.exp_ack == ack_seqno:
                if segment.ack_received == True:
                    self.total_duplicate_ack += 1
                segment.ack_received = True
                return 0
        return -1 
    
    def write_to_log(self, curr_time, type, seqno, len):
        current_time = round((curr_time - self.start_time) * 1000, 2)
        if type == segment.SYN:
            self.logging.info(f"snd\t0\tSYN\t{seqno}\t0")
        elif type == segment.ACK:
            self.logging.info(f"rcv\t{current_time}\tACK\t{seqno}\t0")
        elif type == segment.DATA:
            self.logging.info(f"snd\t{current_time}\tDATA\t{seqno}\t{len}")
        elif type == segment.FIN:
            self.logging.info(f"snd\t{current_time}\tFIN\t{seqno}\t0")
        elif type == segment.RESET:
            self.logging.info(f"snd\t{current_time}\tRESET\t0\t0")

if __name__ == '__main__':
    # logging is useful for the log part: https://docs.python.org/3/library/logging.html
    logging.basicConfig(
        # filename="Sender_log.txt",
        stream=sys.stderr,
        level=logging.DEBUG,
        format='%(asctime)s,%(msecs)03d %(levelname)-8s %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S')

    if len(sys.argv) != 6:
        print(
            "\n===== Error usage, python3 sender.py sender_port receiver_port FileReceived.txt max_win rot ======\n")
        exit(0)

    sender = Sender(*sys.argv[1:])
    sender.run()
