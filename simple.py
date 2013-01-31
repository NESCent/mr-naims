#######################################################
# Simple Name Cleaner 
#   produced at Phylotastic-II / NESCent::HIP
# 
# TNRS Team: Dan Leehr, Andrew Lenards, Guarav Vaidya
#######################################################
import requests
import codecs
import csv
import time
import json
import sys
import os
import Bio.Phylo as phylo
from optparse import OptionParser

taxosaurus_url="http://taxosaurus.org/"
gnrd_url='http://gnrd.globalnames.org/name_finder.json'
MATCH_THRESHOLD=0.9

def lookup_taxosaurus(names,limit_source):
    print('Calling Taxosaurus'),
    payload={'query': '\n'.join(names)}
    if limit_source:
        payload['source'] = limit_source
    response = requests.post(taxosaurus_url + 'submit',params=payload)
    while response.status_code == 302:
        print('.'),
        sys.stdout.flush()
        time.sleep(0.5)
        response = requests.get(response.url)
    response.raise_for_status()
    print('')
    return response.json()


def get_args():
    m_thres_help = ("the matching score threshold to use, defined as a " \
                   "decimal, all matches equal to or greater will be replaced." \
                   " The default is %s") % MATCH_THRESHOLD
    usage = "usage:\n %prog [options] file-input\n or\n %prog [options] --file file-input"

    parser = OptionParser(usage=usage)
    parser.add_option("-f", "--file", dest="filename",
              help="the file, FILE, read from...", metavar="FILE")
    parser.add_option("-s", "--skip-gnrd", 
              help="Do not lookup names at GNRD.  Only valid for a text file or newick tree",
              dest="skip_gnrd",
              action="store_true",
              default=False)
    parser.add_option("-n", "--newick",
              help="The file is a newick tree",
              dest="is_newick",
              action="store_true",
              default=False)
    parser.add_option("--source",
              help="Limit taxosaurus to a single source: [MSW3|iPlant|NCBI]",
              dest="limit_source",
              default=None)
    parser.add_option("--match-threshold", dest="m_threshold", 
              default=MATCH_THRESHOLD, help=m_thres_help, 
              metavar="MATCH_SCORE_THRESHOLD")
    return parser.parse_args()


def grab_file(options, args):
    """
    Returns the assumed input file

    If the --file/-f argument is not pass in, assume the first
    positional argument is the filename to operate on
    """
    if (options.filename == None):
        return args[0]
    return options.filename

def replace_names(mapping, source_filename, dest_filename):
    with codecs.open(source_filename, 'r', encoding='utf-8') as source:
        with codecs.open(dest_filename, 'w', encoding='utf-8') as dest:
            for line in source:
                key = line.rstrip()
                if key in mapping.keys():
                    val = mapping[key]
                    if (val != None):
                        line = val + '\n'
                dest.write(line)


def replace_names(names, mapping):
    """
    names is the original list
    mapping is the dictionary
    """
    results = []
    for name in names:
        if name in mapping.keys():
            results.append(mapping[name])
        else:
            results.append(name)
    return results


def get_best_match(matches):
    """
    Returns the best match from the list of matches
    """ 
    if (len(matches) == 0):
        # No matches
        return None 
    else:
        # sort by score and return the highest
        return sorted(matches, key=lambda k: float(k['score']))[-1]

def log_record_in(report, name, match, matches):
    """
    Mutate the report's record for a given submitted name
    """
    prov_record = report[name]
    prov_record['submittedName'] = name
#   prov_record['otherMatches'] = json.dumps(matches)
    if not match:
        prov_record['accepted'] = 'none'
    # if there's no match, then skip this
    else:
        prov_record['accepted'] = match['acceptedName']
        prov_record['sourceId'] = match['sourceId']
        prov_record['uri'] = match['uri']
        prov_record['score'] = match['score']


def create_name_mapping(names, match_threshold):
    """
    Returns the mapping of input to clean names above the minimum score
    and a report of all action taken
    """
    mapping = dict()
    prov_report = dict() 

    for name in names:
        matches = name['matches']
        submittedName = name['submittedName']

        prov_report[submittedName] = dict()

        if (len(matches) >= 1):
            match = get_best_match(matches)
            if match:
                log_record_in(prov_report, submittedName, match, matches)

                accepted = match['acceptedName']
                score = float(match['score'])
                if ((accepted != "") and (score >= match_threshold)):
                    mapping[submittedName] = accepted
            else:
                log_record_in(prov_report, submittedName, match, matches)

    return mapping, prov_report


def get_names_from_file(filename,skip_gnrd=False,is_newick=False):
    """
    Returns a list of names.
    If use_gnrd is false, it is assumed that there is one name per line
    If true, it is sent to http://gnrd.globalnames.org/api
    for name recognition, and the resulting list is returned
    """
    names = []
    
    # If the file is a newick tree, extract the terminal nodes
    
    if(not skip_gnrd):
        # needs to be multipart/form-data
        response = None
        files = {}
        params={'unique':'false'}
        base_filename = os.path.basename(filename)
        if(is_newick):
            # can't send a newick tree to gnrd, send the extracted terminal node names
            tree = phylo.read(filename,'newick')
            terminal_nodes = [x.name.replace('_',' ') for x in tree.get_terminals()]
            files={'file': (base_filename, '\n'.join(terminal_nodes))}
        else:
            files={'file': (base_filename, open(filename,'rb'))}    
        print("Calling Global Names Discovery Service"),
        response = requests.get(gnrd_url, params=params, files=files)
        while response.json()['status'] == 303:
            print('.'),
            sys.stdout.flush()            
            time.sleep(0.5)
            response = requests.get(response.url)
        response.raise_for_status()
        print('')
        names_dict = {}
        for name in response.json()['names']:
            # response json with unique true
            # {
            #   "identifiedName": "Carnivora", 
            #   "scientificName": "Carnivora", 
            #   "verbatim": "Carnivora:"
            # }
            # 
            # response json with unique false
            # {
            #   "identifiedName": "Halichoerus grypus", 
            #   "offsetEnd": 3430, 
            #   "offsetStart": 3411, 
            #   "scientificName": "Halichoerus grypus", 
            #   "verbatim": "(Halichoerus grypus)"
            # }
            scientific_name = name['scientificName']
            name_dict = {} # keyed by scientificName
            if scientific_name in names_dict.keys():
                name_dict = names_dict[scientific_name]
            else:
                name_dict['scientific_name'] = name['scientificName']
                name_dict['verbatims'] = []
                name_dict['identified_names'] = []
                name_dict['offsets'] = []
            name_dict['verbatims'].append(name['verbatim'])
            name_dict['identified_names'].append(name['identifiedName'])
            name_dict['offsets'].append((name['offsetStart'], name['offsetEnd']))
            names_dict[scientific_name] = name_dict
        return (names_dict.keys(), names_dict)
    else:
        # text file
        with codecs.open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                names.append(line.rstrip())
    return (names, {})

#######################################################
# just testing the prov_report written to standard out
import sys
#######################################################

def main():
    global MATCH_THRESHOLD
    (options, args) = get_args()

    fname = grab_file(options, args)
    if (options.m_threshold != None and options.m_threshold != MATCH_THRESHOLD):
        MATCH_THRESHOLD = float(options.m_threshold)

    (names, names_dict) = get_names_from_file(fname, options.skip_gnrd, options.is_newick)
    # names_dict contains results of GNRD extraction if performed
    result = lookup_taxosaurus(names,options.limit_source)
    # Check for errors in taxosaurus lookup
    for source in result['metadata']['sources']:
        if 'errorMessage' in source.keys():
            print "Error querying %s: %s: %s" % (source['sourceId'], source['status'], source['errorMessage'])
        else:
            print "Queried %s: %s" % (source['sourceId'], source['status'])

    (mapping, prov_report) = create_name_mapping(result['names'], MATCH_THRESHOLD)

#    fields = ('submittedName','accepted','sourceId','uri','score','otherMatches')
    fields = ('submittedName','accepted','sourceId','uri','score')

    headers = dict((field,field) for field in fields)

    writer = csv.DictWriter(sys.stdout, fieldnames=fields)
    writer.writerow(headers)
    for record in prov_report.keys():
        writer.writerow({k:v.encode('utf-8') for k,v in prov_report[record].items()})

    replaced = replace_names(names, mapping)
    # For now, just write the list out to file
    with codecs.open(fname + '.clean', 'w', encoding='utf-8') as dest:
        for item in replaced:
            dest.write(item + '\n')



if __name__ == "__main__":
    main()

