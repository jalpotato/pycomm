# -*- coding: utf-8 -*-
#
# clx.py - Ethernet/IP Client for Rockwell PLCs
#
#
# Copyright (c) 2014 Agostino Ruscito <ruscito@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#


import logging,string
from pycomm.cip.cip_base import *


class Driver(object):
	"""
	This Ethernet/IP client is based on Rockwell specification. Please refer to the link below for details.

	http://literature.rockwellautomation.com/idc/groups/literature/documents/pm/1756-pm020_-en-p.pdf

	The following services have been implemented:
		- Read Tag Service (0x4c)
		- Read Tag Fragment Service (0x52)
		- Write Tag Service (0x4d)
		- Write Tag Fragment Service (0x53)
		- Multiple Service Packet (0x0a)

	The client has been successfully tested with the following PLCs:
		- CompactLogix 5330ERM
		- CompactLogix 5370
		- ControlLogix 5572 and 1756-EN2T Module

"""
	def __init__(self):
		self.logger = logging.getLogger('ab_comm.clx')
		self.__version__ = '0.1'
		self.__sock = Socket(None)
		self._session = 0
		self._connection_opened = False
		self._reply = None
		self._message = None
		self._target_cid = None
		self._target_is_connected = False
		self._tag_list = []
		self._tag_struct = {}
		self._tag_template = {}
		self._template_buffer = ""
		self._template_member_cnt = 0
		self._sequence = 1
		self._last_instance = 0
		self._byte_offset = 0
		self._last_position = 0
		self._more_packets_available = False
		self._last_tag_read = ()
		self._last_tag_write = ()
		self._status = (0, "")

		self.attribs = {'context': '_pycomm_', 'protocol version': 1, 'rpi': 5000, 'port': 0xAF12, 'timeout': 10,
						'backplane': 1, 'cpu slot': 0, 'option': 0, 'cid': '\x27\x04\x19\x71', 'csn': '\x27\x04',
						'vid': '\x09\x10', 'vsn': '\x09\x10\x19\x71'}

	def __len__(self):
		return len(self.attribs)

	def __getitem__(self, key):
		return self.attribs[key]

	def __setitem__(self, key, value):
		self.attribs[key] = value

	def __delitem__(self, key):
		try:
			del self.attribs[key]
		except LookupError:
			pass

	def __iter__(self):
		return iter(self.attribs)

	def __contains__(self, item):
		return item in self.attribs

	def build_header(self, command, length):
		""" Build the encapsulate message header

		The header is 24 bytes fixed length, and includes the command and the length of the optional data portion.

		 :return: the headre
		"""
		h = command                                 # Command UINT
		h += pack_uint(length)                      # Length UINT
		h += pack_dint(self._session)                # Session Handle UDINT
		h += pack_dint(0)                           # Status UDINT
		h += self.attribs['context']                # Sender Context 8 bytes
		h += pack_dint(self.attribs['option'])      # Option UDINT
		return h

	def nop(self):
		""" No reply command

		A NOP provides a way for either an originator or target to determine if the TCP connection is still open.
		"""
		self._message = self.build_header(ENCAPSULATION_COMMAND['nop'], 0)
		self._send()

	def list_identity(self):
		""" ListIdentity command to locate and identify potential target

		After sending the message the client wait for the reply
		"""
		self._message = self.build_header(ENCAPSULATION_COMMAND['list_identity'], 0)
		self._send()
		self._receive()

	def get_status(self):
		""" Get the last status/error

		This method can be used after any call to get any details in case of error
		:return: A tuple containing (error group, error message)
		"""
		return self._status

	def get_last_tag_read(self):
		""" Return the last tag read by a multi request read

		:return: A tuple (tag name, value, type)
		"""
		return self._last_tag_read

	def get_last_tag_write(self):
		""" Return the last tag write by a multi request write

		:return: A tuple (tag name, 'GOOD') if the write was successful otherwise (tag name, 'BAD')
		"""
		return self._last_tag_write

	def clear(self):
		""" Clear the last status/error

		:return: return am empty tuple
		"""
		self._status = (0, "")

	def register_session(self):
		""" Register a new session with the communication partner

		:return: None if any error, otherwise return the session number
		"""
		if self._session:
			return self._session

		self._message = self.build_header(ENCAPSULATION_COMMAND['register_session'], 4)
		self._message += pack_uint(self.attribs['protocol version'])
		self._message += pack_uint(0)
		self._send()
		self._receive()
		if self._check_reply():
			self._session = unpack_dint(self._reply[4:8])
			self.logger.info("Session ={0} has been registered.".format(print_bytes_line(self._reply[4:8])))
			return self._session
		self.logger.warning('Session not registered.')
		return None

	def un_register_session(self):
		""" Un-register a connection

		"""
		self._message = self.build_header(ENCAPSULATION_COMMAND['unregister_session'], 0)
		self._send()
		self._session = None

	def send_rr_data(self, msg):
		""" SendRRData transfer an encapsulated request/reply packet between the originator and target

		:param msg: The message to be send to the target
		:return: the reply received from the target
		"""
		self._message = self.build_header(ENCAPSULATION_COMMAND["send_rr_data"], len(msg))
		self._message += msg
		self._send()
		self._receive()
		return self._check_reply()

	def send_unit_data(self, msg):
		""" SendUnitData send encapsulated connected messages.

		:param msg: The message to be send to the target
		:return: the reply received from the target
		"""
		self._message = self.build_header(ENCAPSULATION_COMMAND["send_unit_data"], len(msg))
		self._message += msg
		self._send()
		self._receive()
		return self._check_reply()

	def _get_sequence(self):
		""" Increase and return the sequence used with connected messages

		:return: The New sequence
		"""
		if self._sequence < 65535:
			self._sequence += 1
		else:
			self._sequence = 1
		return self._sequence

	def _parse_tag_list(self, start_tag_ptr, status):
		""" extract the tags list from the message received

		:param start_tag_ptr: The point in the message string where the tag list begin
		:param status: The status of the message receives
		"""
		tags_returned = self._reply[start_tag_ptr:]
		tags_returned_length = len(tags_returned)
		idx = 0
		instance = 0
		try:
			while idx < tags_returned_length:
				instance = unpack_dint(tags_returned[idx:idx+4])
				idx += 4
				tag_length = unpack_uint(tags_returned[idx:idx+2])
				idx += 2
				tag_name = tags_returned[idx:idx+tag_length]
				idx += tag_length
				symbol_type = unpack_uint(tags_returned[idx:idx+2])
				idx += 2
				#self._tag_list.append((instance, tag_name, symbol_type))
				self._tag_list.append({'instance_id': instance, 'tag_name': tag_name, 'symbol_type': symbol_type})

			if status == SUCCESS:
				self._last_instance = -1
			elif status == 0x06:
				self._last_instance = instance + 1
			else:
				self._status = (1, 'unknown status during _parse_tag_list')
				self.logger.warning(self._status)
				self._last_instance = -1

		except Exception as e:
			self._status = (1, "Error :{0} inside _parse_tag_list".format(e))
			self.logger.warning(self._status)
			self._last_instance = -1

	def _parse_tag_struct(self, start_tag_ptr, status):
		""" extract the tags list from the message received

		:param start_tag_ptr: The point in the message string where the tag list begin
		:param status: The status of the message receives
		"""
		attrs_returned = self._reply[start_tag_ptr:]
		attrs_returned_length = len(attrs_returned)
		if attrs_returned_length < 30:
			print attrs_returned_length
			self._status = (1, 'response too short _parse_tag_struct')
			return

		self._tag_struct = {}
		idx = 4
		try:
			success = unpack_uint(attrs_returned[idx:idx + 2])
			if not success:
				idx += 2
				self._tag_struct['obj_def_size'] = unpack_dint(attrs_returned[idx:idx + 4])
			idx += 6
			success = unpack_uint(attrs_returned[idx:idx + 2])
			if not success:
				idx += 2
				self._tag_struct['struct_size'] = unpack_dint(attrs_returned[idx:idx + 4])
			idx += 6
			success = unpack_uint(attrs_returned[idx:idx + 2])
			if not success:
				idx += 2
				self._tag_struct['member_cnt'] = unpack_uint(attrs_returned[idx:idx + 2])
			idx += 4
			success = unpack_uint(attrs_returned[idx:idx + 2])
			if not success:
				idx += 2
				self._tag_struct['struct_handle'] = unpack_uint(attrs_returned[idx:idx + 2])

			# self._tag_list.append((instance, tag_name, symbol_type))
			# self._tag_struct.append({'instance_id': instance, 'tag_name': tag_name, 'symbol_type': symbol_type})

			if status != SUCCESS:
				self._status = (1, 'unknown status during _parse_tag_list')
				self.logger.warning(self._status)

		except Exception as e:
			self._status = (1, "Error :{0} inside _parse_tag_struct".format(e))
			self.logger.warning(self._status)

	def _parse_template(self, start_tag_ptr, status):
		""" extract the tags list from the message received

		:param start_tag_ptr: The point in the message string where the tag list begin
		:param status: The status of the message receives
		"""
		tags_returned = self._reply[start_tag_ptr:]
		tags_returned_length = len(tags_returned)
		member = 0
		idx = 0
		offset = 0
		template_members = []
		#self._tag_template = {}
		try:
			self._template_buffer += tags_returned

			if status == SUCCESS:
				self._last_instance = -1
			elif status == 0x06:
				self._last_instance += tags_returned_length
			else:
				self._status = (1, 'unknown status {0} during _parse_template'.format(status))
				self.logger.warning(self._status)
				self._last_instance = -1

		except Exception as e:
			self._status = (1, "Error :{0} inside _parse_template".format(e))
			self.logger.warning(self._status)
			self._last_instance = -1

	def _parse_fragment(self, start_ptr, status):
		""" parse the fragment returned by a fragment service.

		:param start_ptr: Where the fragment starts within the reply
		:param status: status field used to decide if keep parsing or stop
		"""
		data_type = unpack_uint(self._reply[start_ptr:start_ptr+2])
		fragment_returned = self._reply[start_ptr+2:]

		fragment_returned_length = len(fragment_returned)
		idx = 0
		try:
			while idx < fragment_returned_length:
				typ = I_DATA_TYPE[data_type]
				value = UNPACK_DATA_FUNCTION[typ](fragment_returned[idx:idx+DATA_FUNCTION_SIZE[typ]])
				idx += DATA_FUNCTION_SIZE[typ]
				self._tag_list.append((self._last_position, value))
				self._last_position += 1
			if status == SUCCESS:
				self._byte_offset = -1
			elif status == 0x06:
				self._byte_offset += fragment_returned_length
			else:
				self.logger.warning(2, 'unknown status during _parse_fragment')
				self._byte_offset = -1
		except Exception as e:
			self._status = (2, "Error :{0} inside _parse_fragment".format(e))
			self.logger.warning(self._status)
			self._byte_offset = -1

	def _parse_multiple_request_read(self, tags):
		""" parse the message received from a multi request read:

		For each tag parsed, the information extracted includes the tag name, the value read and the data type.
		Those information are appended to the tag list as tuple

		:return: the tag list
		"""
		offset = 50
		position = 50
		number_of_service_replies = unpack_uint(self._reply[offset:offset+2])
		tag_list = []
		for index in range(number_of_service_replies):
			position += 2
			start = offset + unpack_uint(self._reply[position:position+2])
			general_status = unpack_sint(self._reply[start+2:start+3])

			if general_status == 0:
				data_type = unpack_uint(self._reply[start+4:start+6])
				try:
					value_begin = start + 6
					value_end = value_begin + DATA_FUNCTION_SIZE[I_DATA_TYPE[data_type]]
					value = self._reply[value_begin:value_end]
					self._last_tag_read = (tags[index], UNPACK_DATA_FUNCTION[I_DATA_TYPE[data_type]](value),
										   I_DATA_TYPE[data_type])
				except LookupError:
					self._last_tag_read = (tags[index], None, None)
			else:
				self._last_tag_read = (tags[index], None, None)

			tag_list.append(self._last_tag_read)

		return tag_list

	def _parse_multiple_request_write(self, tags):
		""" parse the message received from a multi request writ:

		For each tag parsed, the information extracted includes the tag name and the status of the writing.
		Those information are appended to the tag list as tuple

		:return: the tag list
		"""
		offset = 50
		position = 50
		number_of_service_replies = unpack_uint(self._reply[offset:offset+2])
		tag_list = []
		for index in range(number_of_service_replies):
			position += 2
			start = offset + unpack_uint(self._reply[position:position+2])
			general_status = unpack_sint(self._reply[start+2:start+3])

			if general_status == 0:
				self._last_tag_write = (tags[index] + ('GOOD',))
			else:
				self._last_tag_write = (tags[index] + ('BAD',))

			tag_list.append(self._last_tag_write)
		return tag_list

	def _check_reply(self):
		""" check the reply message for error

		"""
		self._more_packets_available = False
		try:
			if self._reply is None:
				self._status = (3, '%s without reply' % REPLY_INFO[unpack_dint(self._message[:2])])
				self.logger.warning(self._status)
				return False
			# Get the type of command
			typ = unpack_uint(self._reply[:2])

			# Encapsulation status check
			if unpack_dint(self._reply[8:12]) != SUCCESS:
				self._status = (3, "{0} reply status:{1}".format(REPLY_INFO[typ],
																 SERVICE_STATUS[unpack_dint(self._reply[8:12])]))
				self.logger.warning(self._status)
				return False

			# Command Specific Status check
			if typ == unpack_uint(ENCAPSULATION_COMMAND["send_rr_data"]):
				status = unpack_sint(self._reply[42:43])
				if status != SUCCESS:
					self._status = (3, "send_rr_data reply:{0} - Extend status:{1}".format(
						SERVICE_STATUS[status], get_extended_status(self._reply, 42)))
					self.logger.warning(self._status)
					return False
				else:
					return True

			elif typ == unpack_uint(ENCAPSULATION_COMMAND["send_unit_data"]):
				status = unpack_sint(self._reply[48:49])
				if unpack_sint(self._reply[46:47]) == I_TAG_SERVICES_REPLY["Read Tag Fragmented"]:
					self._parse_fragment(50, status)
					return True
				if unpack_sint(self._reply[46:47]) == I_TAG_SERVICES_REPLY["Get Instance Attribute List"]:
					self._parse_tag_list(50, status)
					return True
				if unpack_sint(self._reply[46:47]) == I_TAG_SERVICES_REPLY["Get Attribute List"]:
					self._parse_tag_struct(50, status)
					return True
				if unpack_sint(self._reply[46:47]) == I_TAG_SERVICES_REPLY["Read Template"]:
					self._parse_template(50, status)
					return True
				if status == 0x06:
					self._status = (3, "Insufficient Packet Space")
					self.logger.warning(self._status)
					self._more_packets_available = True
				elif status != SUCCESS:
					self._status = (3, "send_unit_data reply:{0} - Extend status:{1}".format(
						SERVICE_STATUS[status], get_extended_status(self._reply, 48)))
					self.logger.warning(self._status)
					return False
				else:
					return True

		except LookupError:
			self._status = (3, "LookupError inside _check_reply")
			self.logger.warning(self._status)
			# Prevent infinite looping for multi-part responses
			self._last_instance = -1
			return False

		return True

	def forward_open(self):
		""" CIP implementation of the forward open message

		Refer to ODVA documentation Volume 1 3-5.5.2

		:return: False if any error in the reply message
		"""
		if self._session == 0:
			self._status = (4, "A session need to be registered before to call forward_open.")
			self.logger.warning(self._status)
			return None

		forward_open_msg = [
			FORWARD_OPEN,
			pack_sint(2),
			CLASS_ID["8-bit"],
			CLASS_CODE["Connection Manager"],  # Volume 1: 5-1
			INSTANCE_ID["8-bit"],
			CONNECTION_MANAGER_INSTANCE['Open Request'],
			PRIORITY,
			TIMEOUT_TICKS,
			pack_dint(0),
			self.attribs['cid'],
			self.attribs['csn'],
			self.attribs['vid'],
			self.attribs['vsn'],
			TIMEOUT_MULTIPLIER,
			'\x00\x00\x00',
			pack_dint(self.attribs['rpi'] * 1000),
			pack_uint(CONNECTION_PARAMETER['Default']),
			pack_dint(self.attribs['rpi'] * 1000),
			pack_uint(CONNECTION_PARAMETER['Default']),
			TRANSPORT_CLASS,  # Transport Class
			CONNECTION_SIZE['Backplane'],
			pack_sint(self.attribs['backplane']),
			pack_sint(self.attribs['cpu slot']),
			CLASS_ID["8-bit"],
			CLASS_CODE["Message Router"],
			INSTANCE_ID["8-bit"],
			pack_sint(1)
		]

		if self.send_rr_data(
				build_common_packet_format(DATA_ITEM['Unconnected'], ''.join(forward_open_msg), ADDRESS_ITEM['UCMM'],)):
			self._target_cid = self._reply[44:48]
			self._target_is_connected = True
			self.logger.info("The target is connected end returned CID %s" % print_bytes_line(self._target_cid))
			return True
		self._status = (4, "forward_open returned False")
		self.logger.warning(self._status)
		return False

	def forward_close(self):
		""" CIP implementation of the forward close message

		Each connection opened with the froward open message need to be closed.
		Refer to ODVA documentation Volume 1 3-5.5.3

		:return: False if any error in the reply message
		"""
		if self._session == 0:
			self._status = (5, "A session need to be registered before to call forward_close.")
			self.logger.warning(self._status)
			return None

		forward_close_msg = [
			FORWARD_CLOSE,
			pack_sint(2),
			CLASS_ID["8-bit"],
			CLASS_CODE["Connection Manager"],  # Volume 1: 5-1
			INSTANCE_ID["8-bit"],
			CONNECTION_MANAGER_INSTANCE['Open Request'],
			PRIORITY,
			TIMEOUT_TICKS,
			self.attribs['csn'],
			self.attribs['vid'],
			self.attribs['vsn'],
			CONNECTION_SIZE['Backplane'],
			'\x00',     # Reserved
			pack_sint(self.attribs['backplane']),
			pack_sint(self.attribs['cpu slot']),
			CLASS_ID["8-bit"],
			CLASS_CODE["Message Router"],
			INSTANCE_ID["8-bit"],
			pack_sint(1)
		]
		if self.send_rr_data(
				build_common_packet_format(DATA_ITEM['Unconnected'], ''.join(forward_close_msg), ADDRESS_ITEM['UCMM'])):
			self._target_is_connected = False
			return True
		self._status = (5, "forward_close returned False")
		self.logger.warning(self._status)
		return False

	def read_tag(self, tag):
		""" read tag from a connected plc

		Possible combination can be passed to this method:
				- ('Counts') a single tag name
				- (['ControlWord']) a list with one tag or many
				- (['parts', 'ControlWord', 'Counts'])

		At the moment there is not a strong validation for the argument passed. The user should verify
		the correctness of the format passed.

		:return: None is returned in case of error otherwise the tag list is returned
		"""
		multi_requests = False
		if isinstance(tag, list):
			multi_requests = True

		if self._session == 0:
			self._status = (6, "A session need to be registered before to call read_tag.")
			self.logger.warning(self._status)
			return None

		if not self._target_is_connected:
			if not self.forward_open():
				self._status = (5, "Target did not connected. read_tag will not be executed.")
				self.logger.warning(self._status)
				return None

		if multi_requests:
			rp_list = []
			for t in tag:
				rp = create_tag_rp(t, multi_requests=True)
				if rp is None:
					self._status = (6, "Cannot create tag {0} request packet. read_tag will not be executed.".format(tag))
					self.logger.warning(self._status)
					return None
				else:
					rp_list.append(chr(TAG_SERVICES_REQUEST['Read Tag']) + rp + pack_uint(1))
			message_request = build_multiple_service(rp_list, self._get_sequence())

		else:
			rp = create_tag_rp(tag)
			if rp is None:
				self._status = (6, "Cannot create tag {0} request packet. read_tag will not be executed.".format(tag))
				self.logger.warning(self._status)
				return None
			else:
				# Creating the Message Request Packet
				message_request = [
					pack_uint(self._get_sequence()),
					chr(TAG_SERVICES_REQUEST['Read Tag']),  # the Request Service
					chr(len(rp) / 2),                       # the Request Path Size length in word
					rp,                                     # the request path
					pack_uint(1)
				]

		self.send_unit_data(
			build_common_packet_format(
				DATA_ITEM['Connected'],
				''.join(message_request),
				ADDRESS_ITEM['Connection Based'],
				addr_data=self._target_cid,
			))

		if multi_requests:
			return self._parse_multiple_request_read(tag)
		else:
			# Get the data type
			data_type = unpack_uint(self._reply[50:52])
			try:
				return UNPACK_DATA_FUNCTION[I_DATA_TYPE[data_type]](self._reply[52:]), I_DATA_TYPE[data_type]
			except LookupError:
				self._status = (6, "Unknown data type returned by read_tag")
				self.logger.warning(self._status)
				return None

	def read_array(self, tag, counts):
		""" read array of atomic data type from a connected plc

		At the moment there is not a strong validation for the argument passed. The user should verify
		the correctness of the format passed.

		:param tag: the name of the tag to read
		:param counts: the number of element to read
		:return: None is returned in case of error otherwise the tag list is returned
		"""
		if self._session == 0:
			self._status = (7, "A session need to be registered before to call read_array.")
			self.logger.warning(self._status)
			return None

		if not self._target_is_connected:
			if not self.forward_open():
				self._status = (7, "Target did not connected. read_tag will not be executed.")
				self.logger.warning(self._status)
				return None

		self._byte_offset = 0
		self._last_position = 0

		while self._byte_offset != -1:
			rp = create_tag_rp(tag)
			if rp is None:
				self._status = (7, "Cannot create tag {0} request packet. read_tag will not be executed.".format(tag))
				self.logger.warning(self._status)
				return None
			else:
				# Creating the Message Request Packet
				message_request = [
					pack_uint(self._get_sequence()),
					chr(TAG_SERVICES_REQUEST["Read Tag Fragmented"]),  # the Request Service
					chr(len(rp) / 2),                                  # the Request Path Size length in word
					rp,                                                # the request path
					pack_uint(counts),
					pack_dint(self._byte_offset)
				]

			self.send_unit_data(
				build_common_packet_format(
					DATA_ITEM['Connected'],
					''.join(message_request),
					ADDRESS_ITEM['Connection Based'],
					addr_data=self._target_cid,
				))

		return self._tag_list

	def write_tag(self, tag, value=None, typ=None):
		""" write tag/tags from a connected plc

		Possible combination can be passed to this method:
				- ('tag name', Value, data type)  as single parameters or inside a tuple
				- ([('tag name', Value, data type), ('tag name2', Value, data type)]) as array of tuples

		At the moment there is not a strong validation for the argument passed. The user should verify
		the correctness of the format passed.

		The type accepted are:
			- BOOL
			- SINT
			- INT'
			- DINT
			- REAL
			- LINT
			- BYTE
			- WORD
			- DWORD
			- LWORD

		:param tag: tag name, or an array of tuple containing (tag name, value, data type)
		:param value: the value to write or none if tag is an array of tuple or a tuple
		:param typ: the type of the tag to write or none if tag is an array of tuple or a tuple
		:return: None is returned in case of error otherwise the tag list is returned
		"""
		multi_requests = False
		if isinstance(tag, list):
			multi_requests = True

		if self._session == 0:
			self._status = (8, "A session need to be registered before to call write_tag.")
			self.logger.warning(self._status)
			return None

		if not self._target_is_connected:
			if not self.forward_open():
				self._status = (8, "Target did not connected. write_tag will not be executed.")
				self.logger.warning(self._status)
				return None

		if multi_requests:
			rp_list = []
			tag_to_remove = []
			idx = 0
			for name, value, typ in tag:
				# Create the request path to wrap the tag name
				rp = create_tag_rp(name, multi_requests=True)
				if rp is None:
					self._status = (8, "Cannot create tag{0} req. packet. write_tag will not be executed".format(tag))
					self.logger.warning(self._status)
					return None
				else:
					try:    # Trying to add the rp to the request path list
						val = PACK_DATA_FUNCTION[typ](value)
						rp_list.append(
							chr(TAG_SERVICES_REQUEST['Write Tag'])
							+ rp
							+ pack_uint(S_DATA_TYPE[typ])
							+ pack_uint(1)
							+ val
						)
						idx += 1
					except (LookupError, struct.error) as e:
						self._status = (8, "Tag:{0} type:{1} removed from write list. Error:{2}.".format(name, typ, e))
						self.logger.warning(self._status)

						# The tag in idx position need to be removed from the rp list because has some kind of error
						tag_to_remove.append(idx)

			# Remove the tags that have not been inserted in the request path list
			for position in tag_to_remove:
				del tag[position]
			# Create the message request
			message_request = build_multiple_service(rp_list, self._get_sequence())

		else:
			if isinstance(tag, tuple):
				name, value, typ = tag
			else:
				name = tag

			rp = create_tag_rp(name)
			if rp is None:
				self._status = (8, "Cannot create tag {0} request packet. write_tag will not be executed.".format(tag))
				self.logger.warning(self._statustag)
				return None
			else:
				# Creating the Message Request Packet
				message_request = [
					pack_uint(self._get_sequence()),
					chr(TAG_SERVICES_REQUEST["Write Tag"]),   # the Request Service
					chr(len(rp) / 2),               # the Request Path Size length in word
					rp,                             # the request path
					pack_uint(S_DATA_TYPE[typ]),    # data type
					pack_uint(1),                    # Add the number of tag to write
					PACK_DATA_FUNCTION[typ](value)
				]

		ret_val = self.send_unit_data(
			build_common_packet_format(
				DATA_ITEM['Connected'],
				''.join(message_request),
				ADDRESS_ITEM['Connection Based'],
				addr_data=self._target_cid,
			)
		)

		if multi_requests:
			return self._parse_multiple_request_write(tag)
		else:
			return ret_val

	def write_array(self, tag, data_type, values):
		""" write array of atomic data type from a connected plc

		At the moment there is not a strong validation for the argument passed. The user should verify
		the correctness of the format passed.

		:param tag: the name of the tag to read
		:param data_type: the type of tag to write
		:param values: the array of values to write
		"""
		if not isinstance(values, list):
			self._status = (9, "A list of tags must be passed to write_array.")
			self.logger.warning(self._status)
			return None

		if self._session == 0:
			self._status = (9, "A session need to be registered before to call write_array.")
			self.logger.warning(self._status)
			return None

		if not self._target_is_connected:
			if not self.forward_open():
				self._status = (9, "Target did not connected. write_array will not be executed.")
				self.logger.warning(self._status)
				return None

		array_of_values = ""
		byte_size = 0
		byte_offset = 0

		for i, value in enumerate(values):
			array_of_values += PACK_DATA_FUNCTION[data_type](value)
			byte_size += DATA_FUNCTION_SIZE[data_type]

			if byte_size >= 450 or i == len(values)-1:
				# create the message and send the fragment
				rp = create_tag_rp(tag)
				if rp is None:
					self._status = (9, "Cannot create tag {0} request packet. \
						write_array will not be executed.".format(tag))
					self.logger.warning(self._status)
					return None
				else:
					# Creating the Message Request Packet
					message_request = [
						pack_uint(self._get_sequence()),
						chr(TAG_SERVICES_REQUEST["Write Tag Fragmented"]),  # the Request Service
						chr(len(rp) / 2),                                   # the Request Path Size length in word
						rp,                                                 # the request path
						pack_uint(S_DATA_TYPE[data_type]),                  # Data type to write
						pack_uint(len(values)),                             # Number of elements to write
						pack_dint(byte_offset),
						array_of_values                                     # Fragment of elements to write
					]
					byte_offset += byte_size

				self.send_unit_data(
					build_common_packet_format(
						DATA_ITEM['Connected'],
						''.join(message_request),
						ADDRESS_ITEM['Connection Based'],
						addr_data=self._target_cid,
					))
				array_of_values = ""
				byte_size = 0

	def get_tag_list(self):
		""" get a list of the tags in the plc

		"""

		if self._session == 0:
			self._status = (10, "A session need to be registered before to call get_tag_list.")
			self.logger.warning(self._status)
			return None

		if not self._target_is_connected:
			if not self.forward_open():
				self._status = (10, "Target did not connected. get_tag_list will not be executed.")
				self.logger.warning(self._status)
				return None

		self._last_instance = 0

		while self._last_instance != -1:

			# Creating the Message Request Packet

			message_request = [
				pack_uint(self._get_sequence()),
				chr(TAG_SERVICES_REQUEST['Get Instance Attribute List']),
				# the Request Path Size length in word
				chr(3),
				# Request Path ( 20 6B 25 00 Instance )
				CLASS_ID["8-bit"],       # Class id = 20 from spec 0x20
				CLASS_CODE["Symbol Object"],  # Logical segment: Symbolic Object 0x6B
				INSTANCE_ID["16-bit"],   # Instance Segment: 16 Bit instance 0x25
				'\x00',
				pack_uint(self._last_instance),          # The instance
				# Request Data
				pack_uint(2),   # Number of attributes to retrieve
				pack_uint(1),   # Attribute 1: Symbol name
				pack_uint(2)    # Attribute 2: Symbol type
			]

			self.send_unit_data(
				build_common_packet_format(
					DATA_ITEM['Connected'],
					''.join(message_request),
					ADDRESS_ITEM['Connection Based'],
					addr_data=self._target_cid,
				))

		return self._tag_list

	def get_tag_struct(self, instance_id):
		""" get the structure of a tag in the plc

		"""

		if self._session == 0:
			self._status = (10, "A session need to be registered before to call get_tag_list.")
			self.logger.warning(self._status)
			return None

		if not self._target_is_connected:
			if not self.forward_open():
				self._status = (10, "Target did not connected. get_tag_list will not be executed.")
				self.logger.warning(self._status)
				return None

		# Creating the Message Request Packet

		message_request = [
			pack_uint(self._get_sequence()),
			chr(TAG_SERVICES_REQUEST['Get Attribute List']),  # the Request Path Size length in word
			chr(3),  # Request Path ( 20 6B 25 00 Instance )
			CLASS_ID["8-bit"],  # Class id = 20 from spec 0x20
			CLASS_CODE["Template Object"],  # Logical segment: Template Object 0x6C
			INSTANCE_ID["16-bit"],  # Instance Segment: 16 Bit instance 0x25
			'\x00',
			pack_uint(instance_id),  # self._last_instance),  # The instance  # Request Data
			pack_uint(4),  # Number of attributes to retrieve
			pack_uint(4),  # Attribute 4: Template Object Definition Size
			pack_uint(5),  # Attribute 5: Template Structure Size
			pack_uint(2),  # Attribute 2: Member Count
			pack_uint(1)  # Attribute 1: Structure Handle
		]

		self.send_unit_data(
			build_common_packet_format(
				DATA_ITEM['Connected'],
				''.join(message_request),
				ADDRESS_ITEM['Connection Based'],
				addr_data=self._target_cid,
			))

		return self._tag_struct

	def read_template(self, instance_id, to_read, mem_cnt):
		""" get a list of the tags in the plc

		"""

		if self._session == 0:
			self._status = (10, "A session need to be registered before to call get_tag_list.")
			self.logger.warning(self._status)
			return None

		if not self._target_is_connected:
			if not self.forward_open():
				self._status = (10, "Target did not connected. get_tag_list will not be executed.")
				self.logger.warning(self._status)
				return None

		self._last_instance = 0
		self._template_buffer = ""

		while self._last_instance != -1:
			# Creating the Message Request Packet

			message_request = [
				pack_uint(self._get_sequence()),
				chr(TAG_SERVICES_REQUEST['Read Template']),  # the Request Path Size length in word
				chr(3),  # Request Path ( 20 6B 25 00 Instance )
				CLASS_ID["8-bit"],  # Class id = 20 from spec 0x20
				CLASS_CODE["Template Object"],  # Logical segment: Template Object 0x6C
				INSTANCE_ID["16-bit"],  # Instance Segment: 16 Bit instance 0x25
				'\x00',
				pack_uint(instance_id), #self._last_instance),  # The instance  # Request Data
				pack_dint(self._last_instance),  # Offset
				pack_uint(to_read - self._last_instance),  # Attribute 1: Symbol name
			]

			self.send_unit_data(
				build_common_packet_format(
					DATA_ITEM['Connected'],
					''.join(message_request),
					ADDRESS_ITEM['Connection Based'],
					addr_data=self._target_cid,
				))

		member = 0
		idx = 0
		template_returned = self._template_buffer
		template_members = []
		try:
			while member < mem_cnt:
				info = unpack_uint(template_returned[idx:idx + 2])
				idx += 2
				symbol_type = unpack_uint(template_returned[idx:idx + 2])
				dimensions = (symbol_type & 0b0110000000000000) >> 13
				data_type = symbol_type & 0b0000111111111111
				tag_type = 'atomic'
				if symbol_type & 0b1000000000000000:
					tag_type = 'struct'
				else:
					data_type = I_DATA_TYPE[data_type]
				idx += 2
				offset = unpack_dint(template_returned[idx:idx + 4])
				idx += 4
				template_members.append({'info': info, 'tag_type': tag_type, 'data_type': data_type, 'dimensions': dimensions, 'offset': offset})
				member += 1

			member = 0
			names = string.split(template_returned[idx:], '\x00')
			if len(names) != mem_cnt + 1:
				err = "Failed to read member names {" + str(len(names)) + "} {" + str(mem_cnt + 1) + "}."
				raise Exception(err)

			while member < mem_cnt:
				template_members[member]['member_name'] = names[member + 1]
				member += 1

			self._tag_template = {'name': names[0], 'members': template_members}
		except Exception as e:
			self._status = (1, "Error :{0} inside read_template during parsing of template".format(e))
			self.logger.warning(self._status)

		return self._tag_template

	def _send(self):
		""" socket send

		:return: true if no error otherwise false
		"""
		try:
			self.logger.debug(print_bytes_msg(self._message, '-------------- SEND --------------'))
			self.__sock.send(self._message)
		except SocketError as e:
			self._status = (11, "Error {0} during {1}".format(e, 'send'))
			self.logger.critical(self._status)
			return False

		return True

	def _receive(self):
		""" socket receive

		:return: true if no error otherwise false
		"""
		try:
			self._reply = self.__sock.receive()
			self.logger.debug(print_bytes_msg(self._reply, '----------- RECEIVE -----------'))
		except SocketError as e:
			self._status = (12, "Error {0} during {1}".format(e, 'receive'))
			self.logger.critical(self._status)
			return False

		return True

	def open(self, ip_address):
		""" socket open

		:return: true if no error otherwise false
		"""
		# handle the socket layer
		if not self._connection_opened:
			try:
				self.__sock.connect(ip_address, self.attribs['port'])
				self._connection_opened = True
				if self.register_session() is None:
					self._status = (13, "Session not registered")
					self.logger.error(self._status)
					return False
				return True
			except SocketError as e:
				self._status = (13, "Error {0} during {1}".format(e, 'open'))
				self.logger.critical(self._status)
		return False

	def close(self):
		""" socket close

		:return: true if no error otherwise false
		"""
		if self._target_is_connected:
			self.forward_close()
		if self._session != 0:
			self.un_register_session()
		self.__sock.close()
		self.__sock = None
		self._session = 0
		self._connection_opened = False
