def loadTags():
	from pycomm.ab_comm.clx import Driver as ClxDriver
	import pycomm.cip.cip_const as CIP
	from collections import OrderedDict
	import nautilus_utils, json, copy, os

	# if not session.tag_list == None:
	# 	return nautilus_utils.to_json(session.tag_list)
	session.tag_list = {}

	vars = request.get_vars
	if 'ip' in vars:
		if len(vars['ip']) <= 0:
			return dict()
	else:
		return dict()

	c = ClxDriver()

	tag_list = dict()
	tag_list['tags'] = []
	prob_tag = {}
	if not os.path.exists(request.folder + 'static\\plc_tag_trees\\' + vars['ip'] + '.json'):
		try:
			if c.open(vars['ip']):
				print "Conn"
				tags = c.get_tag_list()
				tag_cnt = 0
				user_tags = {}
				templates = {}

				for tag in tags:
					prob_tag = tag
					if tag['symbol_type'] & 0b0001000000000000:
						# System tag, ignore
						continue
					elif tag['tag_name'][0:2] == "__":
						continue
					elif ':' in tag['tag_name']:
						continue

					if tag['symbol_type'] & 0b1000000000000000:
						# if (tag['symbol_type'] & 0b0000111111111111) in range(0, 0xF00):
							# Predefined structs, don't care about these. LIES
							# print tag['tag_name']
							# continue
						tag['tag_type'] = 'struct'
						tag['attrs'] = c.get_tag_struct(tag['symbol_type'] & 0b0000111111111111)
						if (tag['symbol_type'] & 0b0000111111111111) in templates:
							tag['template'] = templates[tag['symbol_type'] & 0b0000111111111111]['name']
							tag['data_type'] = templates[tag['symbol_type'] & 0b0000111111111111]['name']
							t_mem = templates[tag['symbol_type'] & 0b0000111111111111]['members'][:]
							tag['members'] = t_mem
						else:
							template = c.read_template(tag['symbol_type'] & 0b0000111111111111, (tag['attrs']['obj_def_size'] * 4) - 21, tag['attrs']['member_cnt'])
							tag['template'] = template['name']
							tag['data_type'] = template['name']
							t_mem = template['members'][:]
							tag['members'] = t_mem
							templates[tag['symbol_type'] & 0b0000111111111111] = template
					# elif (tag['symbol_type'] & 0b0000111111111111) in range(0, 0x100):
					# 	system atomic (UINT, String, Etc.) don't care about these. ALSO LIES
					# 	continue
					else:
						tag['tag_type'] = 'atomic'
						tag['data_type'] = CIP.I_DATA_TYPE[tag['symbol_type'] & 0b0000000011111111]

					tag['dimensions'] = (tag['symbol_type'] & 0b0110000000000000) >> 13
					if tag['dimensions'] <= 0:
						tag['length'] = 1
					else:
						idx = 0
						lower = 0
						upper = 100
						# Find an upper bound
						done = False
						while not done:
							# da, dt = c.read_tag(tag['tag_name'] + '[' + str(upper) + ']')
							da, dt = c.read_array(tag['tag_name'], upper)
							# print '{0} {1} {2}\n'.format(da, dt, upper)
							if da == -1:
								done = True
							else:
								lower = upper
								upper *= 2
						# print "Got Upper Bound"
						idx = int(upper - round(float(upper - lower) / 2))
						while upper - lower != 1:
							# print "J"
							# da, dt = c.read_tag(tag['tag_name'] + '[' + str(idx) + ']')
							da, dt = c.read_array(tag['tag_name'], idx)
							# print '{0} {1} {2}\n'.format(da, dt, upper)
							if da == -1:
								# Too high
								upper = idx
								idx = int(upper - round(float(upper - lower) / 2))
							else:
								# Too low
								lower = idx
								idx = int(upper - round(float(upper - lower) / 2))
						tag['length'] = lower

					tag_cnt += 1
					populate_members(tag, c, templates, True)
					tag = populate_full_names(tag, '')
					user_tags[tag['tag_name']] = copy.deepcopy(tag)

				# print user_tags['CHAMP_TRACK_COUNTER_1']
				# for tag in user_tags:
				# 	populate_full_names(user_tags[tag], '')
				# print user_tags['CHAMP_TRACK_COUNTER_1']
				with open(request.folder + 'static\\plc_tag_trees\\' + vars['ip'] + '.json', 'w') as outfile:
					json.dump(user_tags, outfile, sort_keys=True, indent=4)

				sorted_tags = OrderedDict(sorted(user_tags.items()))
				session.sorted_tags = sorted_tags

			else:
				print "Couldn't reach PLC, can't build tag list."

		except Exception as e:
			print "Error occurred building tag list - {0}".format(e)
			print prob_tag
			return dict()
		finally:
			c.close()
	else:
		with open(request.folder + 'static\\plc_tag_trees\\' + vars['ip'] + '.json') as data_file:
			data = json.load(data_file)
		sorted_tags = OrderedDict(sorted(data.items()))
		session.sorted_tags = sorted_tags

	id = 0
	for t in session.sorted_tags:
		temp = {'id': id, 'text': t, "parentid": -1, 'expanded': True}
		tag_list['tags'].append(temp)
		id += 1

	session.tag_list = tag_list
	return nautilus_utils.to_json(session.tag_list)


def readTag():
	from pycomm.ab_comm.clx import Driver as ClxDriver
	import nautilus_utils

	vars = request.get_vars
	if 'tag' in vars and 'ip' in vars:
		c = ClxDriver()
		try:
			if c.open(vars['ip']):
				tag = session.sorted_tags[vars['tag']]
				data = ""
				d_type = ""
				if tag['dimensions'] > 0:
					t_data, d_type = c.read_array(vars['tag'], tag['length'])
					if tag['tag_type'] == 'struct':
						data = ''.join(t_data)
					else:
						data = t_data
				else:
					print "never"
					data, d_type = c.read_tag(vars['tag'])
					print "get here"
				if tag['tag_type'] == 'atomic':
					if tag['dimensions'] <= 0:
						tag['value'] = data
					else:
						for i in range(0, tag['length']):
							tag['members'][i]['value'] = data[i]
				else:
					populate_struct(vars['tag'], data)
					# print session.sorted_tags[vars['tag']]
					# print "|{0}|".format(data)
		except Exception as e:
			print "Error occurred reading tag - {0}".format(e)
		finally:
			c.close()
		return nautilus_utils.to_json(session.sorted_tags[vars['tag']])
	else:
		return dict()


def populate_struct(v_tag, data):

	try:
		tag = session.sorted_tags[v_tag]
		if tag['length'] > 1:
			x = 0
			struct_size = tag['attrs']['struct_size']
			while x < tag['length']:
				# print tag['members'][x]
				pop_struct(tag['members'][x], data[x*struct_size: (x + 1)*struct_size])
				x += 1
		else:
			pop_struct(tag, data)
	except Exception as e:
		print "Error populating data for {0}: {1}".format(v_tag, e)


def pop_struct(tag, data):
	import pycomm.cip.cip_const as CIP
	import pycomm.cip.cip_base as CBASE
	import copy

	cnt = len(tag['members'])
	x = 0
	while x < cnt:
		member = tag['members'][x]
		size = 0
		if tag['tag_type'] == 'atomic':
			size = CIP.DATA_FUNCTION_SIZE[member['data_type']]
		else:
			size = tag['attrs']['struct_size']

		if member['dimensions'] == 0:
			offset = member['offset']
			value = 0
			if member['data_type'] == 'BOOL':
				value = CBASE.UNPACK_DATA_FUNCTION['SINT'](data[offset:offset + size])
				shift = 0b1 << member['info']
				value = 1 if value & shift else 0
			else:
				if member['tag_type'] == 'struct':
					value = CBASE.UNPACK_DATA_FUNCTION['STRUCT'](data[offset:offset + size])
				else:
					value = CBASE.UNPACK_DATA_FUNCTION[member['data_type']](data[offset:offset + size])

			tag['members'][x]['value'] = value

			if member['tag_type'] == 'struct':
				pop_struct(member, data[offset:offset + size])
		else:
			print "NESTED ARRAYS"

		x += 1


def populate_full_names(tag, parent):
	if len(parent) < 1:
		tag['full_name'] = tag['tag_name']
	elif len(tag['tag_name']) < 1:
		tag['full_name'] = parent + '.' + tag['tag_name']
	elif tag['tag_name'][0] == '[':
		tag['full_name'] = parent + tag['tag_name']
	else:
		tag['full_name'] = parent + '.' + tag['tag_name']

	# print tag['full_name']

	if 'members' in tag:
		for member in tag['members']:
			papa = tag['full_name']
			# print papa
			populate_full_names(member, papa)
	return tag


def populate_members(tag, c, templates, top=False):
	import copy
	# print "-----"
	# print tag['tag_name']
	# print "-----"
	p_member = {}
	try:
		if 'members' in tag:
			if 'attrs' in tag:
				if not top:
					length = 0
					if tag['dimensions'] > 0:
						length = tag['attrs']['obj_def_size'] / tag['attrs']['struct_size']
					else:
						length = 1
					tag['length'] = length
				if tag['length'] > 1:
					members = []
					i = 0
					while i < tag['length']:
						memes = copy.deepcopy(tag['members'])
						members.append({'tag_name': '[' + str(i) + ']', 'data_type': tag['data_type'], 'tag_type': 'struct', 'members': memes, 'attrs': tag['attrs']})
						i += 1
					tag['members'] = members
				for member in tag['members']:
					if 'members' in member:
						for struct_mem in member['members']:
							p_member = struct_mem
							populate_members(struct_mem, c, templates)
					elif member['tag_type'] == 'struct':
						populate_members(member, c, templates)
		elif tag['tag_type'] == 'struct':
			symType = tag['data_type']
			tag['attrs'] = c.get_tag_struct(symType)
			if (symType) in templates:
				tag['template'] = templates[symType]['name']
				tag['data_type'] = templates[symType]['name']
				t_mem = templates[symType]['members'][:]
				tag['members'] = copy.deepcopy(t_mem)
			else:
				template = c.read_template(symType, (tag['attrs']['obj_def_size'] * 4) - 21, tag['attrs']['member_cnt'])
				tag['template'] = template['name']
				tag['data_type'] = template['name']
				t_mem = template['members'][:]
				tag['members'] = copy.deepcopy(t_mem)
				templates[symType] = template
			populate_members(tag, c, templates)
		elif 'dimensions' in tag:
			if tag['dimensions'] > 0:
				i = 0
				members = []
				if 'length' in tag:
					while i < tag['length']:
						members.append({'tag_name': '[' + str(i) + ']', 'data_type': tag['data_type'], 'tag_type': tag['tag_type']})
						i += 1
				else:
					i = 0
					if 'info' in tag:
						tag['length'] = tag['info']  # Just going to assume this is always true
						while i < tag['length']:
							members.append({'tag_name': '[' + str(i) + ']', 'data_type': tag['data_type'], 'tag_type': tag['tag_type']})
							i += 1

					# data, data_type = c.read_tag(tag['full_name'])
					# length = len(data) / CIP.DATA_FUNCTION_SIZE[data_type]
					# i = 0
					# members = []
					# while i < length:
					# 	members.append({'tag_name': '[' + i + ']', 'data_type': data_type, 'tag_type': 'atomic'})
					# 	i += 1
				tag['members'] = copy.deepcopy(members)


		return
	except Exception as e:
		print "Error populating member {0}: {1}".format(p_member, e)