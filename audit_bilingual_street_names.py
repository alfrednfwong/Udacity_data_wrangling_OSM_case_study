# Audit street names of both Chinese and English in an OSM file.
# The target area is Hong Kong, with a little bit of Shenzhen, PRC
#
# Hong Kong is a bilingual jurisdiction with both Chinese and English
# as the official languanges. According to the OSM guidelines, names
# of places in Hong Kong should be recorded in 3 tags. The full name is 
# in key:name, where the Chinese name is followed by a space and then
# the English name. The second tag is key:name:en for the English name, 
# and the third is key:name:zh for the Chinese name.
#
# We have an xml file with the official Chinese and English names of 
# all the streets/roads, etc in Hong Kong in the Government's Lands 
# Department.
#
# We'll audit the OSM file, by printing all sets of names where one 
# version (e.g. the name:zh) matches an official name while other(s) 
# (e.g. the name:en) do not.

import csv
import re
import xml.etree.cElementTree as ET
import string
import pandas as pd

OSM_FILE = 'Hong_Kong.osm'
STREET_NAME_FILE = 'PSI_Street Name_062017.xml'

NODES_PATH = 'nodes.csv'
NODE_TAGS_PATH = 'nodes_tags.csv'
WAYS_PATH = 'ways.csv'
WAY_NODES_PATH = 'ways_nodes.csv'
WAY_TAGS_PATH = 'ways_tags.csv'

LOWER_COLON = re.compile(r'^([a-z]|_)+:([a-z]|_)+')
PROBLEMCHARS = re.compile(r'[=\+/&<>;\'"\?%#$@\,\. \t\r\n]')
FIRST_COLON_RE = re.compile(r'(.*?):(.*)$')

CHI_NAME_RE = re.compile(r"([^A-Za-z'\-,. ]+[0-9]?[^A-Za-z'\-,. ]+)")
ENG_NAME_RE = re.compile(r"[ ]*([A-Za-z0-9'\-,. ]{4,})")

NODE_FIELDS = [
    'id', 'lat', 'lon', 'user', 'uid', 'version', 'changeset', 'timestamp'
]
NODE_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_FIELDS = ['id', 'user', 'uid', 'version', 'changeset', 'timestamp']
WAY_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_NODES_FIELDS = ['id', 'node_id', 'position']

# These are possible values for an osm way with a tag with 'highway' 
# as key, to be a government-named street.
STREET_VALUES = [
    'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 
    'residential',  'living_street', 'pedestrian', 'track', 
    'road', 'steps', 'path'
]

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
            
def audit_bilingual_street_names(OSM_FILE):
    '''
    Takes the OSM_FILE, interate through the elements, and returns a
    list of lists, where each element list is the various versions 
    of the street's name, as well as the look up result from the
    name_to_index lookups, of streets that fulfill the following 
    conditions.
    
    
    - If the look up yielded exactly one result. Without manually
    checking each street or some extra data for cross reference, we 
    cannot determine what actual street an osm way is, if the look up 
    didn't yield any result, or if the look up yield multiple results,
    indicating one name version is contradicting another), and
    
    - If any name version does not match the look up result. No point
    looking at perfect entries.
    '''
    possibly_dirty = []
    
    for element in get_element(OSM_FILE, tags=('way')):
        way_tags = shape_element(element)['way_tags']
        # Check if it's a street at all, if not skip this set of way tags
        if is_street(way_tags):
            osm_names = get_street_names(way_tags)
            look_up_result_index, not_found_count = name_look_up(osm_names)
            if (
                (len(look_up_result_index) == 1)
                and (not_found_count > 0 or len(osm_names) < 4)
                ):
                look_up_result_names = []
                index = look_up_result_index.pop()
                for name in (index_to_name[index].values()):
                    look_up_result_names.append(name)
                row_to_add = osm_names.copy()
                row_to_add.update({'look_up_results': look_up_result_names})
                possibly_dirty.append(row_to_add)
    return possibly_dirty

official_list = get_official_name_list(STREET_NAME_FILE)
name_to_index, index_to_name = create_lookups(official_list)
possibly_dirty = audit_bilingual_street_names(OSM_FILE)
df = pd.DataFrame(possibly_dirty, columns = [
    'en_only', 'reg_eng', 'zh_only', 'reg_chi', 'look_up_results'
])
pd.set_option('display.max_rows', 5000)
pd.set_option('display.max_columns', 6)
pd.set_option('display.max_colwidth', 35)
print(df)