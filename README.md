# Udacity_data_wrangling_OSM_case_study


# This is a case study of some map data from the openstreetmap.org. We'll parse the data from an XML file exported from their website, clean up two problems we have found in the data, import it into an SQL database, and explore the data.

# In this case study we'll work with the map data of Hong Kong. http://www.openstreetmap.org/node/2833125787

# case_study_osm.pdf is the full report

# PSI_Street Name_062017.xml (the official list) is a file with the government-named streets/roads in both Chinese and English, the two official languages of Hong Kong.

# audit_bilingual_street_names.py is for auditing street names in the 3 tags that are supposed to be there. The print out is a list of streets that can be matched to the official list, and yet have one or more values missing or cannot be matched to the corresponding translation in the official list.

# audit_phone_numbers.py is for auditing phone number formats. The print out is a list of tags where either the key is 'phone' or the value can be matched by one of the 3 regex patterns.

# parse_clean_and_csv.py parses the data, clean the street names with the official list and reformats all phone numbers, and then writes them to csv files.

# shatin.osm is the osm data of a sample area in Hong Kong
