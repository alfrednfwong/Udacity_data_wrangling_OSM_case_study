# Audit phone number fields in an OSM file.
# Target area is Hong Kong with a little bit of Shenzhen, PRC.
# Prints all values in way_tags and node_tags that look like a 
# phone number, or has the key = 'phone'. 
# Also prints a count of all keys of these tags as well as a list 
# of all characters present in the values.

# test change

import csv
import re
import xml.etree.cElementTree as ET
import pandas as pd


OSM_FILE = "Hong_Kong.osm"

NODES_PATH = 'nodes.csv'
NODE_TAGS_PATH = 'nodes_tags.csv'
WAYS_PATH = 'ways.csv'
WAY_NODES_PATH = 'ways_nodes.csv'
WAY_TAGS_PATH = 'ways_tags.csv'

LOWER_COLON = re.compile(r'^([a-z]|_)+:([a-z]|_)+')
PROBLEMCHARS = re.compile(r'[=\+/&<>;\'"\?%#$@\,\. \t\r\n]')
FIRST_COLON_RE = re.compile(r'(.*?):(.*)$')

# To match Hong Kong phone numbers. 
# Match group 1 is the optional country code 852.
# Match groups 2 and 3 make up the 8 digit number, land line or cell phone
HK_PHONE_RE = re.compile(
    r'^[＋+(]{0,2}[ ]?(852)?\)?[- ]?([0-9]{4})[- ]?([0-9]{4})$'
)

# To match PRC land line phone number in Shenzhen (just north of Hong Kong).
# Match group 1 is the optional country code 86.
# Match group 2 is the compulsory area code 755, with the optional prefix 0
# Match groups 3 and 4 make up the local number ranging from 6 to 8 digits.
# People in the PRC always include the area code in the phone number, 
# and 755 has to be matched here because if it's not there, it can't be
# a Shenzhen number, and our map doesn't include any other PRC area.
# The prefix 0 is in fact a signal for intra-area calls within the PRC, 
# just like the + sign before the country code, and it's therefore 
# redundant. However some people seem to include it as a habit.
SZ_LAND_RE = re.compile(
    r'^[＋+(]?(86)?\)?[- ]?\(?0?(755)\)?[- ]?([0-9]{3,4})[- ]?([0-9]{3,4})$'
)

# To match PRC cell phone numbers. (Cell phone numbers are country-wide)
# Match group 1 is the optional country code 86.
# Match group 2 to 4 make up the 11 digit cell phone number.
# As of Janurary 2018, cell phone numbers in the PRC always starts between
# 13 to 19.
PRC_CELL_RE = re.compile(
    r'^[＋+(]?(86)?\)?[- ]?(1[3-9][0-9])[- ]?([0-9]{4})[- ]?([0-9]{4})$'
)

NODE_FIELDS = [
    'id', 'lat', 'lon', 'user', 'uid', 'version', 'changeset', 'timestamp'
]
NODE_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_FIELDS = ['id', 'user', 'uid', 'version', 'changeset', 'timestamp']
WAY_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_NODES_FIELDS = ['id', 'node_id', 'position']


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

def is_phone_pattern(in_string):
    '''
    Takes a string and returns true if it matches any of the phone patterns
    '''
    if HK_PHONE_RE.search(in_string):
        return True
    elif SZ_LAND_RE.search(in_string):
        return True
    elif PRC_CELL_RE.search(in_string):
        return True
    else:
        return False

def audit_phone_numbers(osm_file):
    '''
    Takes an osm file, iterparse it and return all the tags whose values
    look like a phone number.
    '''
    possible_phone_numbers = []
    for element in get_element(osm_file, tags=('node', 'way')):
        if element.tag == 'node':
            tags = shape_element(element)['node_tags']
        elif element.tag == 'way':
            tags = shape_element(element)['way_tags']
        
        for tag in tags:
            if tag['key'] == 'phone' or tag['key'] == 'fax':
                possible_phone_numbers.append(tag)
            else:
                # there can be multiple phone numbers separated by a colon
                for value in tag['value'].split(';'):
                    if is_phone_pattern(value):
                        possible_phone_numbers.append(tag)
    return possible_phone_numbers

def list_chars(possible_phone_numbers):
    '''
    Takes the possible_phone_numbers list and returns all characters
    present in the value of ['value'] of each dict in the list
    '''
    char_list = []
    for tag in possible_phone_numbers:
        for char in tag['value']:
            if char not in char_list:
                char_list.append(char)
    return char_list

possible_phone_numbers = audit_phone_numbers(OSM_FILE)
df = pd.DataFrame(possible_phone_numbers)
pd.set_option('display.max_rows', 5000)
pd.set_option('display.max_columns', 6)
print('\n\nPossible phone numbers:')
print(df)

print('\n\nCounts of keys:')
print(df.key.value_counts())

print('\n\nCharacters present in values:')
print(list_chars(possible_phone_numbers))
