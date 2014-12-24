import socket
import struct


class EipBase:
    EIP_COMMAND = {"nop": 0x00,
                   "list_targets": 0x01,
                   "list_services": 0x04,
                   "list_identity": 0x63,
                   "list_interfaces": 0x64,
                   "register_session": 0x65,
                   "unregister_session": 0x66,
                   "send_rr_data": 0x6F,
                   "send_unit_data": 0x70}

    EIP_STATUS = {0x0000: "0x0000: Success",
                  0x0001: "0x0001: Unsupported Command",
                  0x0002: "0x0002: No Resources to Process",
                  0x0003: "0x0003: Poorly Formed/Bad Data Attached",
                  0x0064: "0x0064: Invalid Session",
                  0x0065: "0x0065: Request was Invalid Length",
                  0x0069: "0x0069: Unsupported Protocol Version"}

    def __init__(self):
        self.__version__ = '0.1'
        self.s = None
        self.params = {'session': 0, 'status': 0, 'name': 'ucmm',
                        'port': 0xAF12, 'timeout': 5.0, 'context': '_pycomm_',
                        'option': 0, 'protocol_version': 0}
        self.session = 0
        self.context = '_pycomm_'
        self.protocol_version = 0
        self.status = 0
        self.name = 'ucmm'
        self.port = 0xAF12
        self.timeout = 5.0
        self.option = 0

    @property
    def session(self):
        """The session property"""
        return self.session

    @session.setter
    def session(self, par):
        self.session = par

    @property
    def context(self):
        return self.context

    @context.setter
    def context(self, par):
        self.context = par

    @property
    def status(self):
        return self.status

    @status.setter
    def status(self, par):
        self.status = par

    def set_session(self, s):
        self.params['session'] = s

    def version(self):
        return self.__version__

    def str_AddLE16(self, n): # convert 16-bit integer into 2xbyte
        return struct.pack('<H', n)

    def str_AddLE32( self, n): # convert 32-bit integer into 4xbyte
        return struct.pack('<I', n)

    def n_ParseLE16( self, st): # convert 16-bit integer into 2xbyte
        return int(struct.unpack('<H', st[0:2])[0])

    def n_ParseLE32( self, st): # convert 32-bit integer into 4xbyte
        return int(struct.unpack('<I', st[0:4])[0])

    def printHeader(self, eip_hdr):
        print
        n = len( eip_hdr)
        print "  Full length of EIP = %d (0x%04x)" % (n,n)

        cmd = self.n_ParseLE16(eip_hdr[:2])
        print "         EIP Command =",
        if( cmd == 0):
            print "NOP"
        elif( cmd == 0x01):
            print "List Targets"
        elif( cmd == 0x04):
            print "List Services"
        elif( cmd == 0x63):
            print "List Identity"
        elif( cmd == 0x64):
            print "List Interfaces"
        elif( cmd == 0x65):
            print "Register Session"
        elif( cmd == 0x66):
            print "Unregister Session"
        else:
            print "Unknown command: 0x%02x" % cmd

        nAttachedData = self.n_ParseLE16(eip_hdr[2:4])
        print "Attached Data Length = %d" % nAttachedData

        n = self.n_ParseLE32(eip_hdr[4:8])
        print "      Session Handle = %d (0x%08x)" % (n,n)

        n = self.n_ParseLE32(eip_hdr[8:12])
        print "      Session Status = %d (0x%08x)" % (n,n)

        print "      Sender Context = %s" % eip_hdr[12:20]

        n = self.n_ParseLE32(eip_hdr[20:24])
        print "    Protocol Options = %d (0x%08x)" % (n,n)

        if( nAttachedData > 0):
            if( nAttachedData < 500):
                print "data =", list(eip_hdr[24:])
            else:
                print "attached data is longer than 500 bytes"

        return


    def parse_register_session_reply(self, rsp):

        if not rsp or len(rsp) != 28:
            print "bad length!"
            self.set_session(0)
            return False

        if self.n_ParseLE16(rsp[:2]) != 0x65:
            print "bad command!"
            self.set_session(0)
            return False

        if(self.n_ParseLE32(rsp[8:12])!= 0):
            print "bad status!"
            self.set_session(0)
            return False

        # ignore the rest

        self.session = self.n_ParseLE32(rsp[4:8])

        n = self.session
        print "EIPC: New Session Handle = %d (0x%08x)" % (n,n)
        return True

    def parse_replay(self, rsp):
        pass


    def __build_header(self, command, lenght):
        """
        private  method called by the commands method to build the header
        :param command:
        :param lenght:
        :return:header
        """
        h = self.str_AddLE16(command)
        h += self.str_AddLE16(lenght)
        h += self.str_AddLE32(self.session)
        h += self.str_AddLE32(self.status)
        h += self.context
        h += self.str_AddLE32(self.protocol_version)
        self.printHeader(h)
        return h

    def register_session(self):
        """
        0x65
        :return:
        """
        msg = self.__build_header(self.EIP_COMMAND['register_session'], 4)
        msg += self.str_AddLE16(1)
        msg += self.str_AddLE16(0)
        self.printHeader(msg)
        return msg

    def unregister_session(self):
        return self.__build_header(self.EIP_COMMAND['unregister_session'], 0)

    def send(self, msg):
        if self.s is not None:
            self.s.send(msg)

    def open(self, ip_address):
        # handle the socket layer
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.settimeout(self.params['timeout'])
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.s.connect_ex((ip_address, self.params['port']))

        self.s.send(self.register_session())

        # wait for the response
        rsp = self.s.recv(100)

        # parse the response
        self.parse_register_session_reply(rsp)

        # return the session
        return self.session

    def close(self):
        if self.session != 0:
            self.s.send(self.unregister_session())
        try:
            self.s.close()
        except:
            print "Connection Close Error"

        self.s = None
        self.session = 0