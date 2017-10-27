import csv
import codecs
import pprint
import re
import xml.etree.cElementTree as ET

import cerberus

import schema

OSM_PATH = "greater_london.osm"

NODES_PATH = "nodes.csv"
NODE_TAGS_PATH = "nodes_tags.csv"
WAYS_PATH = "ways.csv"
WAY_NODES_PATH = "ways_nodes.csv"
WAY_TAGS_PATH = "ways_tags.csv"

LOWER_COLON = re.compile(r'^([a-z]|_)+:([a-z]|_)+')
PROBLEMCHARS = re.compile(r'[=\+/&<>;\'"\?%#$@\,\. \t\r\n]')
ABBREVIATED_ST = re.compile(r'^\b\S+\.?', re.IGNORECASE)
STREETNAMES = re.compile(r'^\b\S+\.?', re.IGNORECASE)

SCHEMA = schema.schema

# Make sure the fields order in the csvs matches the column order in the sql table schema
NODE_FIELDS = ['id','version', 'changeset', 'timestamp', 'user', 'uid', 'lat','lon']
WAY_FIELDS = ['id', 'version', 'changeset', 'timestamp','user', 'uid']
NODE_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_TAGS_FIELDS = ['id', 'key', 'value', 'type']
WAY_NODES_FIELDS = ['id', 'node_id', 'position']


def shape_element(element, node_attr_fields=NODE_FIELDS, way_attr_fields=WAY_FIELDS,
                  problem_chars=PROBLEMCHARS, default_tag_type='regular'):
    """Clean and shape node or way XML element to Python dict"""

    expected = ["Saint"]

    mapping = { "St": "Saint",
                "st": "Saint"}

    node_attribs = {}
    way_attribs = {}
    way_nodes = []
    tags = []  # Handle secondary tags the same way for both node and way elements

    if element.tag == 'node': # Parent tag
        nodes = element.attrib # Parent attribute
        for i in NODE_FIELDS:
                try:
                    node_attribs[i] = nodes[i]
                except:
                    # print(node)
                    node_attribs[i] = '000'
                    pass
        # print node_attribs
    if element.tag == 'way': # Parent tag
        ways = element.attrib # Parent attribute
        for i in WAY_FIELDS:
            way_attribs[i] = ways[i]
        # print way_attribs

    for tag in element.iter('tag'): # Child tag tag
        node_way_tags = {}
        value = tag.attrib

        if element.tag == 'node':
            node_way_tags['id'] = node_attribs['id']
        elif element.tag == 'way':
            node_way_tags['id'] = way_attribs['id']

        node_way_tags['value'] = value['v']
        # Drop all keys with these values as they are useless and will contaminate the data
        if PROBLEMCHARS.search(value['k']) or (value['k']) == 'fixme' or (value['k']) == 'FIXME' or (value['k']) == 'randomjunk_bot':
            continue

        if LOWER_COLON.match(value['k'].lower()): # since this regex works on lowercase, lower case all keys
            node_way_tags['type'] = value["k"].split(":", 1)[0]
            node_way_tags['key'] = value["k"].split(":", 1)[1]
        else:
            node_way_tags['key'] = (value['k'])
            node_way_tags['type'] = 'regular'

        # Remove the key "en" and replace it with proper key value
        if node_way_tags['key'] == 'en':
                node_way_tags['key'] = node_way_tags['type']
                node_way_tags['type'] = 'regular'


        elif value["k"] == 'addr:street':
            m = ABBREVIATED_ST.search(value['v'])
            if m:
                street_type = m.group()
                if street_type in mapping.keys():
                    node_way_tags['value'] = re.sub(ABBREVIATED_ST, mapping[m.group()], value['v'])

        elif value["k"] == 'addr:housenumber':
            m = STREETNAMES.search(value['v'])
            if m:
                # For all house numbers, replace the comma with a hyphen for consistency purposes
                node_way_tags['value'] = re.sub(',', '-', value['v'])

        elif value["k"] == 'wikipedia':
            value_of_k = value['v']
            # Remove first 3 letters of value in key wikipedia "en:"
            node_way_tags['value'] = value_of_k[3:]

        else:
            node_way_tags['value'] = value['v']

        tags.append(node_way_tags)
    # print tags

    if element.tag == 'way':
        count = 0
        for nd in element.iter('nd'):
            ways_dict = {}
            ways_dict['id'] = way_attribs['id']
            ways_dict['node_id'] = nd.attrib['ref']
            ways_dict['position'] = count
            count += 1
            way_nodes.append(ways_dict)
        # print way_nodes


    if element.tag == 'node':
        return {'node': node_attribs, 'node_tags': tags}
    elif element.tag == 'way':
        return {'way': way_attribs, 'way_nodes': way_nodes, 'way_tags': tags}



# ================================================== #
#               Helper Functions                     #
# ================================================== #
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
        message_string = "\nElement of type '{0}' has the following errors:\n{1}"
        error_string = pprint.pformat(errors)

        raise Exception(message_string.format(field, error_string))


class UnicodeDictWriter(csv.DictWriter, object):
    """Extend csv.DictWriter to handle Unicode input"""

    def writerow(self, row):
        super(UnicodeDictWriter, self).writerow({
            k: (v.encode('utf-8') if isinstance(v, unicode) else v) for k, v in row.iteritems()
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
         codecs.open(WAY_TAGS_PATH, 'w') as way_tags_file:

        nodes_writer = UnicodeDictWriter(nodes_file, NODE_FIELDS)
        node_tags_writer = UnicodeDictWriter(nodes_tags_file, NODE_TAGS_FIELDS)
        ways_writer = UnicodeDictWriter(ways_file, WAY_FIELDS)
        way_nodes_writer = UnicodeDictWriter(way_nodes_file, WAY_NODES_FIELDS)
        way_tags_writer = UnicodeDictWriter(way_tags_file, WAY_TAGS_FIELDS)

        nodes_writer.writeheader()
        node_tags_writer.writeheader()
        ways_writer.writeheader()
        way_nodes_writer.writeheader()
        way_tags_writer.writeheader()

        validator = cerberus.Validator()

        for element in get_element(file_in, tags=('node', 'way')):
            el = shape_element(element)
            if el:
                if validate is True:
                    validate_element(el, validator)

                if element.tag == 'node':
                    nodes_writer.writerow(el['node'])
                    node_tags_writer.writerows(el['node_tags'])
                elif element.tag == 'way':
                    ways_writer.writerow(el['way'])
                    way_nodes_writer.writerows(el['way_nodes'])
                    way_tags_writer.writerows(el['way_tags'])


if __name__ == '__main__':
    # Note: Validation is ~ 10X slower. For the project consider using a small
    # sample of the map when validating.
    process_map(OSM_PATH, validate=True)
