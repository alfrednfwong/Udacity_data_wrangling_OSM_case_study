# Takes the OSM_FILE, parse and validate it, clean up the bilingual
# street names and phone number format, and write the data into csv 
# files.
#
# Street names:
# First we'll update the official_list to rectify a few errors, 
# and then use it as a dictionary to update tags of street names that 
# are either missing or have errors in them.
#
# Phone numbers:
# Rewrite all the phone numbers in the OSM recommended format:
# +<country code> <area code> <number>;+<country code> <area code>... etc



import csv
import codecs
import pprint
import re
import xml.etree.cElementTree as ET
import pandas as pd
import string
import cerberus
import schema

OSM_FILE = 'Hong_Kong.osm'
STREET_NAME_FILE = 'PSI_Street Name_062017.xml'

NODES_PATH = 'nodes.csv'
NODE_TAGS_PATH = 'nodes_tags.csv'
WAYS_PATH = 'ways.csv'
WAY_NODES_PATH = 'ways_nodes.csv'
WAY_TAGS_PATH = 'ways_tags.csv'
UPDATE_HISTORY_PATH = 'update_history.csv'

LOWER_COLON = re.compile(r'^([a-z]|_)+:([a-z]|_)+')
PROBLEMCHARS = re.compile(r'[=\+/&<>;\'"\?%#$@\,\. \t\r\n]')
FIRST_COLON_RE = re.compile(r'(.*?):(.*)$')

CHI_NAME_RE = re.compile(r"([^A-Za-z'\-,. ]+[0-9]?[^A-Za-z'\-,. ]+)")
ENG_NAME_RE = re.compile(r"[ ]*([A-Za-z0-9'\-,. ]{4,})")

# From the audit we know that phone numbers can include the following
# characters:
#     The plus sign + 
#     Parentheses ()
#     Hypen -
#     Spaces. In one record, the value is weirdly segmented as 
#         "+85 22 19 21222" where 852 is the area code and the remaining 
#         8 digits are the local number.
#     A (Chinese) full width cross sign ＋ (unicode 65291 in Dec) that is 
#         presumably used instead of the regular ASCII plus sign. 
# We'll first strip phone numbers of these characters and then use 
# simpler regexes to format them
HK_PHONE_STRIPPED_RE = re.compile(r'^(852)?(\d{8})$')
PRC_CELL_STRIPPED_RE = re.compile(r'^(86)?(1[3-9]\d{9})$')
SZ_LAND_STRIPPED_RE = re.compile(r'^(86)?0?(755)(\d{6,8})$')
NON_DIGIT_CHAR_RE = re.compile(u'[- +)(＋]+')
DELIMITERS_RE = re.compile(',|;')

NODE_FIELDS = [
    'id', 'lat', 'lon', 'user', 'uid', 'version', 'changeset', 'timestamp'
]
NODE_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_FIELDS = ['id', 'user', 'uid', 'version', 'changeset', 'timestamp']
WAY_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_NODES_FIELDS = ['id', 'node_id', 'position']
UPDATE_HISTORY_FIELDS = ['id', 'element_type', 'field_updated']

# These are possible values for an osm way with a tag with 'highway' 
# as key, to be a government-named street.
STREET_VALUES = [
    'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 
    'residential',  'living_street', 'pedestrian', 'track', 
    'road', 'steps', 'path'
]

# These are streets that have the same names as streets in Shenzhen, right
# across the border that our osm file happen to include
sz_street_names = [u'文昌街', u'福民路', u'福祥街', u'丹桂路']
to_change_in_official = {
    # Typos made by the Lands Department in the STREET_NAME_FILE
    'Aberdeent Tuntntel': 'Aberdeen Tunnel',
    'Wan Chai Interchantge': 'Wan Chai Interchange', 
    # This one has a trailing space
    u'半山徑　': u'半山徑',
    # Some words with patterns that string.capwords() cannot recognize,
    # resulting in letters with wrong cases.
    "D'aguilar Street": "D'Aguilar Street",
    "O'brien Road": "O'Brien Road",
    "Cape D'aguilar Road": "Cape D'Aguilar Road",
    'Mcgregor Street': 'McGregor Street',
    'Boulevard De Cascade': 'Boulevard de Cascade',
    'Boulevard De Fontaine': 'Boulevard de Fontaine',
    'Boulevard De Foret': 'Boulevard de Foret',
    'Boulevard De Mer': 'Boulevard de Mer',
    'Boulevard Du Lac': 'Boulevard du Lac',
    'Boulevard Du Palais': 'Boulevard du Palais',
    'Haven Of Hope Road': 'Haven of Hope Road'
}

# From the audit results and after some looking, we can conclude that 
# if the key of a tag is in the following list and the value matches
# any of the phone regexes, it's a phone number
PHONE_KEYS = [
    'phone', 'fax', 'whatsapp', 'mobile', 'telephone', 'operator', 'source'
]

SCHEMA = schema.schema

# ================================================== #
#               Helper Functions                     #
# ================================================== #

def shape_element(element, node_attr_fields=NODE_FIELDS, 
                  way_attr_fields=WAY_FIELDS,
                  problem_chars=PROBLEMCHARS, default_tag_type='regular'):
    """Clean and shape node or way XML element to Python dict"""

    node_attribs = {}
    way_attribs = {}
    way_nodes = []
    # Handle secondary tags the same way for both node and way elements
    tags = []  
    position = 0

    for child in element:
        if (
            child.tag == 'tag' 
            and not PROBLEMCHARS.search(child.attrib['k'])
        ):
            tag_dict = {}
            tag_dict['id'] = element.attrib['id']
            tag_dict['value'] = child.attrib['v']
            m = FIRST_COLON_RE.search(child.attrib['k'])
            if m:
                tag_dict['key'] = m.group(2)
                tag_dict['type'] = m.group(1)
            else:
                tag_dict['key'] = child.attrib['k']
                tag_dict['type'] = 'regular'
            tags.append(tag_dict)
        if child.tag == 'nd':
            way_node_dict = {}
            way_node_dict['id'] = element.attrib['id']
            way_node_dict['node_id'] = child.attrib['ref']
            way_node_dict['position'] = position
            position += 1
            way_nodes.append(way_node_dict)
            
    if element.tag == 'node':
        for attribute_name in element.attrib:
            if attribute_name in NODE_FIELDS:
                node_attribs[attribute_name] = (
                    element.attrib[attribute_name]
                )
        return {'node': node_attribs, 'node_tags': tags}
    elif element.tag == 'way':
        for attribute_name in element.attrib:
            if attribute_name in WAY_FIELDS:
                way_attribs[attribute_name] = (
                    element.attrib[attribute_name]
                )
        return {
            'way': way_attribs, 'way_nodes': way_nodes, 'way_tags': tags
        }

def get_element(osm_file, tags=('node', 'way', 'relation')):
    """Yield element if it is the right type of tag"""

    context = ET.iterparse(osm_file, events=('start', 'end'))
    _, root = next(context)
    for event, elem in context:
        if event == 'end' and elem.tag in tags:
            yield elem
            root.clear()
def validate_element(element, validator, schema=SCHEMA):
    """Raise ValidationError if element does not match schema"""
    if validator.validate(element, schema) is not True:
        field, errors = next(validator.errors.iteritems())
        message_string = (
            "\nElement of type '{0}' has the following errors:\n{1}"
        )
        error_string = pprint.pformat(errors)
        
        raise Exception(message_string.format(field, error_string))


class UnicodeDictWriter(csv.DictWriter, object):
    """Extend csv.DictWriter to handle Unicode input"""

    def writerow(self, row):
        super(UnicodeDictWriter, self).writerow({
            k: (v.encode('utf-8') if isinstance(v, unicode) else v) 
            for k, v in row.iteritems()
        })

    def writerows(self, rows):
        for row in rows:
            self.writerow(row)


# ================================================== #
#               Main Function                        #
# ================================================== #
def process_map(file_in, validate):
    """Iteratively process each XML element and write to csv(s)"""

    with codecs.open(NODES_PATH, 'w') as nodes_file, \
         codecs.open(NODE_TAGS_PATH, 'w') as nodes_tags_file, \
         codecs.open(WAYS_PATH, 'w') as ways_file, \
         codecs.open(WAY_NODES_PATH, 'w') as way_nodes_file, \
         codecs.open(WAY_TAGS_PATH, 'w') as way_tags_file, \
         codecs.open(UPDATE_HISTORY_PATH, 'w') as update_history_file:

        nodes_writer = (
            UnicodeDictWriter(nodes_file, NODE_FIELDS,
                              lineterminator='\n')
        )
        node_tags_writer = (
            UnicodeDictWriter(nodes_tags_file, NODE_TAGS_FIELDS,
                              lineterminator='\n')
        )
        ways_writer = (
            UnicodeDictWriter(ways_file, WAY_FIELDS,
                              lineterminator='\n')
        )
        way_nodes_writer = (
            UnicodeDictWriter(way_nodes_file, WAY_NODES_FIELDS,
                              lineterminator='\n')
        )
        way_tags_writer = (
            UnicodeDictWriter(way_tags_file, WAY_TAGS_FIELDS,
                              lineterminator='\n')
        )
        update_history_writer = (
            UnicodeDictWriter(update_history_file, UPDATE_HISTORY_FIELDS,
                              lineterminator='\n')
        )

        nodes_writer.writeheader()
        node_tags_writer.writeheader()
        ways_writer.writeheader()
        way_nodes_writer.writeheader()
        way_tags_writer.writeheader()
        update_history_writer.writeheader()

        validator = cerberus.Validator()

        for element in get_element(file_in, tags=('node', 'way')):
            el = shape_element(element)
            if el:
                if validate is True:
                    validate_element(el, validator)
             
                phone_updated = False
                name_updated = False
                if element.tag == 'node':
                    tags = el['node_tags']
                    tags, phone_updated = fix_phones_in_tags(tags)
                    nodes_writer.writerow(el['node'])
                    node_tags_writer.writerows(tags)
                    if phone_updated:
                        node_id = el['node']['id']
                        update_history_writer.writerow({
                            'id': node_id,
                            'element_type': 'node',
                            'field_updated': 'phone'
                        })
                elif element.tag == 'way':
                    tags = el['way_tags']
                    tags, phone_updated = fix_phones_in_tags(tags)
                    tags, name_updated = fix_street_names(tags)
                    ways_writer.writerow(el['way'])
                    way_nodes_writer.writerows(el['way_nodes'])
                    way_tags_writer.writerows(tags)
                    if phone_updated:
                        way_id = el['way']['id']
                        update_history_writer.writerow({
                            'id': way_id,
                            'element_type': 'way',
                            'field_updated': 'phone'
                        })
                    if name_updated:
                        way_id = el['way']['id']
                        update_history_writer.writerow({
                            'id': way_id,
                            'element_type': 'way',
                            'field_updated': 'name'
                        })

# ================================================== #
#      Functions for the official name dictionary    #
# ================================================== #

def get_official_name_list(street_name_file):
    '''
    Takes the street names xml file from the HK government, 
    1. parse it,
    2. capitalize the first letter of each word
    3. delete rows with null values,
    4. delete duplicate rows and leaving only one copy,
    5. delete rows that share the same value for either the English name
    xor the Chinese name with another row, but not both names,
    and return a list of lists, where each list contains 2 strings, [0] 
    for the English name and [1] for the Chinese.
    '''
    temp_list = []
    official_list = []
    root = ET.parse(street_name_file)
    streets = root.findall('Row')
    for street in streets:
        eng_name = street.find('English_Street_Name').text
        chi_name = street.find('Chinese_Street_Name').text
        eng_name = string.capwords(eng_name)
        # discard the rows with null values
        if eng_name is not None and chi_name is not None:
            official_list.append([eng_name, chi_name, False])
    
    # discard all but one of the identical copies (same English name and
    # same Chinese name entries)
    temp_list = []
    for row in official_list:
        if row not in temp_list:
            temp_list.append(row)
    official_list = temp_list
    
    # i_row[2] is a flag for the row to be deleted. These rows have
    # either the same English name as other rows, or same Chinese
    # name, but not both.
    for i_row in official_list:
        for j_row in official_list:
            if (i_row[0] == j_row[0]) ^ (i_row[1] == j_row[1]):
                i_row[2] = True
    temp_list = []
    for row in official_list:
        if row[2] is False:
            temp_list.append([row[0], row[1]])
    official_list = temp_list
    return official_list

def update_official_list(official_list):
    '''
    Takes the street_name_list, update the names according to the 
    to_change_in_official, and discard those listed in sz_street_names, 
    and return the street_name_list updated.
    '''
    temp_list = []
    for row in official_list:
        for i in range(2):
            if row[i] in to_change_in_official:
                row[i] = to_change_in_official[row[i]]
        if row[1] not in sz_street_names:
            temp_list.append(row)
    official_list = temp_list
    return official_list

def create_lookups(official_list):
    '''
    Takes the processed official_list and returns two dicts.
    name_to_index has the street names as keys, English and Chinese 
    together, and the index numbers of the street names as values.
    index_to_name has the index numbers as keys and dicts
    {'eng': eng_name, 'chi': chi_name} as values
    '''
    name_to_index = {}
    index_to_name = {}
    for i in range(len(official_list)):
        eng_name = official_list[i][0]
        chi_name = official_list[i][1]
        name_to_index[eng_name] = i
        name_to_index[chi_name] = i
        index_to_name[i] = {'eng': eng_name, 'chi': chi_name}
    return name_to_index, index_to_name

# ================================================== #
#          Functions for fixing street names         #
# ================================================== #

def is_street(way_tags):
    '''
    Takes a way_tags list(of a single way) from the function
    shape_element(), and check if it is a road/street.
    '''
    for tag in way_tags:
        if tag['key'] == 'highway' and tag['value'] in STREET_VALUES:
            return True
    return False

def get_street_names(way_tags):
    '''
    Takes a way_tags list(of a single way) from the function
    shape_element() and return the various versions of the name in a dict.
    Called by street_dict_lookup(way_tags)
    '''
    osm_names = {}
    for tag in way_tags:
        if tag['key'] == 'en' and tag['type'] == 'name' :
            osm_names['en_only'] = tag['value']
        elif tag['key'] == 'zh' and tag['type'] == 'name':
            osm_names['zh_only'] = tag['value']
        elif tag['key'] == 'name' and tag['type'] == 'regular':
            m = ENG_NAME_RE.search(tag['value'])
            n = CHI_NAME_RE.search(tag['value'])
            if m:
                osm_names['reg_eng'] = m.group(1)
            if n:
                osm_names['reg_chi'] = n.group(1)
    return osm_names

def name_look_up(osm_names):
    '''
    Takes a dict of osm_names of a street, look up each name in the
    name_to_index dict, and returns a set of all index numbers as well
    as the number of times a name is not found in the index
    '''
    look_up_result_index = set()
    not_found_count = 0
    for version in osm_names:
        if osm_names[version] in name_to_index:
            look_up_result_index.add(name_to_index[osm_names[version]])
        else:
            not_found_count += 1
    return look_up_result_index, not_found_count
            
def fix_street_names(way_tags):
    '''
    Takes a list of way_tags and update the names if it's a street
    if possible, and add tags if any of the name tags is missing
    '''
    updated = False
    if is_street(way_tags):
        osm_names = get_street_names(way_tags)
        look_up_result_index, not_found_count = name_look_up(osm_names)
    else:
        return way_tags, updated
    
    # if there is no match, or multiple(contradicting) matches, we can't
    # decide which so we'll skip those
    if len(look_up_result_index) != 1:
        return way_tags, updated
    
    index = look_up_result_index.pop()
    way_id = way_tags[0]['id']
    eng_name = index_to_name[index]['eng']
    chi_name = unicode(index_to_name[index]['chi'])
    reg_name = chi_name + ' ' + eng_name
    eng_missing, chi_missing, reg_missing = True, True, True
    
    # overwrite with the official name if the tag exist
    for tag in way_tags:
        if tag['type'] == 'name' and tag['key'] == 'en':
            if tag['value'] != eng_name:
                updated = True
                tag['value'] = eng_name
            eng_missing = False
        if tag['type'] == 'name' and tag['key'] == 'zh':
            if tag['value'] != chi_name:
                updated = True
                tag['value'] = chi_name
            chi_missing = False
        if tag['type'] == 'regular' and tag['key'] == 'name':
            if tag['value'] != reg_name:
                updated = True
                tag['value'] = reg_name
            reg_missing = False
    
    # if they don't, we add the tag
    if eng_missing:
        way_tags.append({
            'id': way_id, 'type': 'name', 'key': 'en', 'value': eng_name
        })
        updated = True
    if chi_missing:
        way_tags.append({
            'id': way_id, 'type': 'name', 'key': 'zh', 'value': chi_name
        })
        updated = True
    if reg_missing:
        way_tags.append({
            'id': way_id, 'type': 'regular', 'key': 'name',
            'value': reg_name
        })
        updated = True
    return way_tags, updated

# ================================================== #
#       Functions for fixing phone numbers           #
# ================================================== #
def fix_phone_value(in_string):
    '''
    Takes a phone number value that may contain multiple numbers 
    separated by commas or semicolons, change them to the format
    recommended by OSM and return.
    '''
    phone_list = []
    out_string = ''
    for value in DELIMITERS_RE.split(in_string):
        stripped = re.sub(NON_DIGIT_CHAR_RE, '', value)
        m = HK_PHONE_STRIPPED_RE.search(stripped)
        if m:
            phone_list.append('+852 ' + m.group(2))
            continue

        m = PRC_CELL_STRIPPED_RE.search(stripped)
        if m:
            phone_list.append('+86 ' + m.group(2))
            continue
        m = SZ_LAND_STRIPPED_RE.search(stripped)
        if m:
            phone_list.append('+86 755 ' + m.group(3))
    if phone_list:
        for phone_number in phone_list:
            out_string = out_string + phone_number + ';'
        out_string = out_string[:-1]
    else:
        out_string = in_string
    if in_string == out_string:
        updated = False
    else:
        updated = True
    return out_string, updated

def fix_phones_in_tags(tags):
    '''
    Takes a list of tags and for every key in PHONE_KEYS, update the 
    corresponding value with the fix_phone_value() function.    
    To be called in the process_map() function.
    '''
    updated = False
    for tag in tags:
        if tag['key'] in PHONE_KEYS:
            tag['value'], updated = fix_phone_value(tag['value'])
    return tags, updated

official_list = get_official_name_list(STREET_NAME_FILE)
official_list = update_official_list(official_list)
name_to_index, index_to_name = create_lookups(official_list)
process_map(OSM_FILE, validate = False)
