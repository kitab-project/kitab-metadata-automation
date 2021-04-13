"""Generate OpenITI metadata files.

The script is best run from the command line.

You can adapt the parameters in a number of ways:

* by adapting the default config file (utility/config.py)
  (restore default by running `python generate-metadata.py -d`)
* by providing a custom config file:
  `python generate-metadata.py -c D:/OpenITI/RELEASE_config.py`
* by specifying command-line arguments (see example below)
* by running the script with default configurations
  (`python generate-metadata.py`)
  and replying to the questions when prompted (see example below)


Examples:
    $ python3 generate-metadata.py --help
    Command line arguments for generate-metadata.py:

    -h, --help : print help info
    -t, --token_counts : update token counts
                         => sets check_token_counts variable to True
    -l, --char_length : update character counts
                        => sets incl_char_length to True
    -f, --flat_data : data not in 25 year repos
                      => sets data_in_25_year_repos to False
    -d, --restore_default : restore values in config.py to default
    -r, --recheck_yml : include a check of whether all yml files are complete

    -i, --input_folder : (str) path to the input folder
                               => sets corpus_path variable
    -o, --output_folder : (str) path to the output folder for metadata files
                                => sets output_path variable
                                (default = "./output/")
    -t, --tsv_fp : (str) file path to the tsv output file
                         (only if you do not want it in the defined output folder)
                         => sets meta_tsv_fp variable
    -y, --yml_fp : (str) file path to the yml output file
                         (only if you do not want it in the defined output folder)
                         => sets meta_yml_fp variable
    -j, --json_fp : (str) file path to the json output file
                          (only if you do not want it in the defined output folder)
                          => sets out_fp variable
    -a, --arab_header_fp: (str) file path to the json file 
                                that will contain all Arabic metadata 
                                extracted from text file headers.
                                (only if you do not want it in the defined output folder)
                                => sets meta_header_fp variable
    -x, --exclude : (list) list of folder names to exclude from metadata
    -c, --config : (str) name of a python file with custom configuration variables
                         (default: ./utility/config.py)

    # run the script with custom config file (model: utility/config.py):
    
    $ python3 generate-metadata.py -c utility/config_RELEASE.py

    # run the script with default configuration and add variables:
    
    $ python3 generate-metadata.py -i ../RELEASE/data_temp -f -r -t -l

    # run the script with default configuration; you will be prompted
    # to provide answers to configure the metadata generation:
    
    $ python3 generate-metadata.py
    Insert the path to the parent folder of the repos: ../RELEASE/data_temp
    Metadata will be collected in ../RELEASE/data_temp
    Is the data in 25-years folders? (press 'N' for RELEASE data)
    N/Y? N
    Do you want to check completeness of the yml files?
    N/Y? Y
    Do you want to re-calculate the Arabic token length of every text?
    This may take up to an hour on a slow machine.
    Y/N: Y
    Do you want to include character count in addition to token count?
    N/Y? Y

The script takes as inputs:
* the uris of all text versions in the corpus
* all yml files for authors, books and versions in the corpus
* all issues in the OpenITI/Annotation GitHub repository
* a tsv file ID_TAGS.txt containing normalized tags from the source libraries
  and Brockelmann

NB: Arabic author names and book titles are taken from the yml files alone
    if the yml files contain this info; otherwise they are taken from the
    text file headers.
    => if the text file headers contain wrong metadata,
       add the correct metadata to the yml file!
    Dates are taken from the URI alone.
    

And creates the following outputs:
* OpenITI_metadata_light.csv:
    a csv file containing the metadata extracted from the URI,
    YML files and text file headers
* OpenITI_metadata_light.json:
    a json representation of the same metadata, with in addition:
    - lists of GitHub issues related to each version/book/author
    - lists of passim runs related to each version
* OpenITI_metadata_complete.yml:
    Master yml file created from all author, book and version yml files
* OpenITI_header_metadata.json:
    A json file with all the metadata from the text file headers.

"""

import csv
import configparser
import json
import os
import re
import shutil
import sys
import textwrap
import time
import getopt
from datetime import datetime


# (in a later stage to be imported from the openiti python library):

#from utility import betaCode
#from utility.betaCode import deNoise, betaCodeToArSimple
#from utility import zfunc  # functions used: zfunc.readYML, zfunc.dicToYML
#from utility.uri import URI, check_yml_files
#from utility import get_issues

from openiti.helper.uri import URI, check_yml_files
from openiti.git import get_issues
from openiti.helper.yml import readYML, dicToYML
from openiti.helper.ara import deNoise, ar_cnt_file
from utility.betaCode import betaCodeToArSimple

splitter = "##RECORD"+"#"*64+"\n"
all_header_meta = dict()
VERBOSE = False

def LoadTags():
    """Load tags from the tags/genre file created by Maxim."""
    mapping_file = "./utility/ID_TAGS.txt"
    with open(mapping_file, "r", encoding="utf8") as f1:
        dic = {}
        data = f1.read().split("\n")

        for d in data:
            d = d.split("\t")
            dic[d[0]] = re.sub(";", " :: ", d[1])
    return dic

tagsDic = LoadTags()

# define a metadata category for all relevant items in the text file headers:
headings_dict = {  
     'Iso' : "Title", 
     'Lng' : "AuthorName",
     'higrid': "Date",
     'HigriD': "Date",
     'auth' : "AuthorName",
     'bk' : "Title", # 
     'cat' : "Genre", # Values: max 3-digit integer
     'name' : "Genre", 
     'البلد' : "Edition:Place", 
     'الطبعة' : "Edition:Date", # date + number (al-ula, al-thaniya, ...)
     'الكتاب' : "Title", 
     'المؤلف' : "AuthorName", 
     'المحقق' : "Edition:Editor", 
     'الناشر' : "Edition:Publisher", 
     'تأليف' : "AuthorName", 
     'تحقيق' : "Edition:Editor", 
     'تقديم وتعليق' : "Edition:Editor", 
     'حققه' : "Edition:Editor", 
     'خرج أحاديثه' : "Edition:Editor", 
     'دار النشر' : "Edition:Publisher", 
     'دراسة وتحقيق' : "Edition:Editor", 
     'سنة الطبع' : "Edition:Date", 
     'سنة النشر' : "Edition:Date", 
     'شهرته' : "AuthorName", 
     'عام النشر' : "Edition:Date", 
     'مكان النشر' : "Edition:Place", 
     'وضع حواشيه' : "Edition:Editor", 
     'أشرف عليه وراجعه وقدم له' : "Edition:Editor", # thesis supervisor
     'أصدرها':  "Edition:Editor",
     'أعتنى به' : "Edition:Editor",
     'أعد أصله' : "Edition:Editor",
     'أعده' : "Edition:Editor",
     'أعده للنشر' : "Edition:Editor",
     'أعده ونشره' : "Edition:Editor",
     'ألحقها' : "Edition:Editor",
     'تقديم وإشراف ومراجعة' : "Edition:Editor", 
     '010.AuthorAKA' : "AuthorName", 
     '010.AuthorNAME' : "AuthorName", 
     '011.AuthorDIED' : "Date", 
     '019.AuthorDIED' : "Date", 
     '020.BookTITLE' : "Title", 
     '021.BookSUBJ' : "Genre", # separated by :: 
     '029.BookTITLEalt' : "Title", 
     '040.EdEDITOR' : "Edition:Editor", 
     '043.EdPUBLISHER' : "Edition:Publisher", 
     '044.EdPLACE' : "Edition:Place", 
     '045.EdYEAR' : "Edition:Date", 
     }


def load_srt_meta(srt_folder, passim_runs):
    """Create a dictionary for all existing srt files for every OpenITI text.

    Args:
       srt_folder (str): path to the folder in which the html files
          for each passim run containing links to all srt file folders are saved
        passim_runs (list): a list of 2-item lists of the
            text reuse detection algorithm passim:
            - first list member: description (date + version number)
            - second list member: run id

    Returns:
        dict (key: bare id of a text (without Vols, -ara/per/..., extension, ...);
              value: list (each item is a list with two items:
                           date of the passim run, link to the relevant srt folder)
    """
    srt_d = dict()
    u = "http://dev.kitab-project.org"
    runs = {item[1]: item[0] for item in passim_runs}
    for fn in os.listdir(srt_folder):
        if fn[:-5] in runs:
##            # extract passim run date from `fn` and format as YYYY-MM-DD
##            date = re.sub("\D+", "", fn)
##            if len(date) == 8:
##                date = "{}-{}-{}".format(date[4:], date[2:4], date[:2])
##            elif len(date) == 4:
##                date = "20{}-{}".format(date[2:], date[:2])

            # extract text ids from html file and add their links to `srt_d`
            fp = os.path.join(srt_folder, fn)
            with open(fp, mode="r", encoding="utf-8") as file:
                html = file.read()
            ids = re.findall('<a href="([^\-"]+-[^"]+)"', html)
            print(len(ids))
            for id_ in ids:
                #id_ = re.sub("Vols[A-Z]*|BK\d+", "", id_)
                bare_id = id_.split("-")[0]
                if not bare_id in srt_d:
                    srt_d[bare_id] = []
                srt_d[bare_id].append([runs[fn[:-5]], "/".join([u, fn[:-5], id_])])
##    with open("output/srt_d.json", mode="w", encoding="utf-8") as file:
##        json.dump(srt_d, file, indent=2, sort_keys=True, ensure_ascii=False)
    return srt_d
        
        
        



def createJsonFile(csv_fp, out_fp, passim_runs, issues_uri_dict):
    """Convert the csv file into a json file,
    adding passim data and Github issues.

    Args:
        csv_fp (str): the filepath of the csv with the input data
        out_fp (str): the filepath of the output json file
        passim_runs (list): a list of 2-item lists of the
            text reuse detection algorithm passim:
            - first list member: description (date + version number)
            - second list member: run id
        issues_uri_dict (dict): a dictionary mapping containing the
            GitHub issues, sorted by URI:
                - key: uri
                - value: a list of GitHub issue objects

    Returns:
        None
    """
    json_objects = []
##    webserver_url = 'http://dev.kitab-project.org'
    srt_d = load_srt_meta("./utility/srt/", passim_runs)

    with open(csv_fp) as csvfile:
        reader = csv.DictReader(csvfile, delimiter='\t')
        record = {}

        for row in reader:
            record = row
            
            # Create a URL for KITAB Web Server for SRT Files
            
            #new_id = row['url'].split('/')[-1].split('.')[-1] # may get the extension!
            uri = URI(row['url'])
            v_id = uri("version", ext="").split(".")[-1]
##            bare_id = re.sub("Vols[A-Z]*|BK\d+", "", v_id)
##            bare_id = bare_id.split("-")[0]

            srts = []

            # get all srt files connected to the current version ID:
            bare_id = v_id.split("-")[0]
            if bare_id in srt_d:
                srts += srt_d[bare_id]
            # add srt files connected to previous versions of this text,
            # before it was split into different parts or joined with other texts:
            bare_id = re.sub("Vols[A-Z]*|BK\d+", "", bare_id)
            if bare_id in srt_d:
                old_srts = [x for x in srt_d[bare_id] if x not in srts]
                srts = old_srts + srts
            record["srts"] = srts
##            try:
##                record["srts"] = srt_d[bare_id]
##            except:
##                print("no srt files found for", bare_id)
##                record["srts"] = []
##            record['srts'] = []
##            if passim_runs:
##                for descr, run_id in passim_runs:
##                    if "2017" in descr:
##                        srt_link = "/".join([webserver_url, run_id, v_id[:-5]])
##                    else:
##                        srt_link = "/".join([webserver_url, run_id, v_id])
##                    record['srts'].append([descr, srt_link])

            # get issues related to the current book/version:
            
            uri = URI(row["versionUri"])
            book_issues = []
            if uri("book") in issues_uri_dict:
                book_issues = issues_uri_dict[uri("book")]
                book_issues = [[x.number, x.labels[0].name] for x in book_issues]
            author_issues = []
            if uri("author") in issues_uri_dict:
                author_issues += issues_uri_dict[uri("author")]
                author_issues = [[x.number, x.labels[0].name] for x in author_issues]
            version_issues = []
            if uri("version") in issues_uri_dict:
                version_issues = issues_uri_dict[uri("version")]
                version_issues = [[x.number, x.labels[0].name] for x in version_issues]
            record["author_issues"] = author_issues
            record["book_issues"] = book_issues
            record["version_issues"] = version_issues
            json_objects.append(record)


    # The required format for json file is data:[{jsonobjects}]
    first_json_key = {}
    first_json_key['data'] = json_objects
    first_json_key['date'] = datetime.now().strftime("%d %B %Y")
    first_json_key['time'] = datetime.now().strftime("%H:%M:%S")
    print("first_json_key['date']", first_json_key['date'])
    with open(out_fp, 'w') as json_file:
        json.dump(first_json_key, json_file,
                  ensure_ascii=False, sort_keys=True)


def read_header(fp):
    """Read only the OpenITI header of a file without opening the entire file.

    Args:
        fp (str): path to the text file

    Returns:
        header (list): A list of all metadata lines in the header
    """
    with open(fp, mode="r", encoding="utf-8") as file:
        header = []
        line = file.readline()
        i=0
        while "#META#Header#End" not in line and i < 100:
            if "#META#" in line or "#NewRec#" in line:
                header.append(line)
            line = file.readline() # move to next line
            i += 1
    return header


def extract_metadata_from_header(fp):
    """Extract the metadata from the headers of the text files.

    Args:
        fp (str): path to the text file

    Returns:
        meta (dict): dictionary containing relevant extracted header items
    """
    header = read_header(fp)
    categories = "AuthorName Title Date Genre "
    categories += "Edition:Editor Edition:Publisher Edition:Place Edition:Date"
    meta = {x : [] for x in categories.split()}
    unreadable = []
    all_meta = dict()
    
    for line in header:
        split_line = line[7:].split("\t::")  # [7:] : start reading after #META# tag
        if len(split_line) == 1:
            split_line = line[7:].split(": ", 1)  # split after first colon
        if len(split_line) > 1:
            val = split_line[1].strip()
            if val.startswith("NO"):
                val = ""
            else:
                # remove line endings within heading categories: 
                val = re.sub(" +", "@@@", val)
                val = re.sub("\s+", "¶ ", val)
                val = re.sub("@@@", " ", val).strip()
                if val.isnumeric():
                    val = str(int(val))
            if val != "":
                key = re.sub("\# ", "", split_line[0])
                all_meta[key] = val
                # reorganize the relevant headers under overarching categories:
                if key in headings_dict:
                    cat = headings_dict[key]
                    meta[cat].append(val)
        else:
            unreadable.append(line)
    if VERBOSE:
        if unreadable:
            print(fp, "METADATA IN UNREADABLE FORMAT")
            for line in unreadable:
                print(line)
            print(meta)
            input("press enter to continue")

    
    all_header_meta[os.path.split(fp)[0]] = all_meta
    return meta

def insert_spaces(s):
    """Split the camel-case string s and insert a space before each capital."""
    return re.sub("([a-z])([A-Z])", r"\1 \2", s)

def collectMetadata(start_folder, exclude, csv_outpth, yml_outpth,
                    incl_char_length=False, split_ar_lat=False,
                    flat_folder=False, output_files_path=None):
    """Collect the metadata from URIs, YML files and text file headers
    and save the metadata in csv and yml files.

    Args:
        start_folder (str): path to the parent folder of all folders
            from which metadata should be collected
        exclude (list): list of directory names that should be excluded
            from the metadata collections
        csv_outpth (str): path to the output csv file
        yml_outpth (str): path to the output yml file
        incl_char_length (bool): if True, a column for character length
            will be included in the metadata
        split_ar_lat (bool): if True, Arabic and transliterated data on
            title and author will be put into separate columns
    """

    print("collecting metadata from OpenITI...")

    dataYML = []
    dataCSV = {}  # vers-uri, date, author, book, id, status, length, fullTextURL, instantiationURL, tags, localPath
    statusDic = {}
    split_files = dict()
    start_folder = re.sub("\\\\", "/", start_folder)

    for root, dirs, files in os.walk(start_folder):
        dirs = [d for d in sorted(dirs) if d not in exclude]
        
        for file in files:
            # select only the version yml files:
            if re.search("^\d{4}[A-Za-z]+\.[A-Za-z\d]+\.\w+-(ara|per)\d\.yml$",
                         file):
                uri = URI(os.path.join(root, file))

                # build the filepaths to all yml files related
                # to the current version yml file:
                if not flat_folder:
                    #versF = uri.build_pth(uri_type="version_yml")
                    #bookF = uri.build_pth(uri_type="book_yml")
                    #authF = uri.build_pth(uri_type="author_yml")
                    auth_folder = os.path.dirname(root)
                else:
                    #versF = os.path.join(root, file)
                    #bookF = os.path.join(root, uri.build_uri(uri_type="book")+".yml")
                    #authF = os.path.join(root, uri.build_uri(uri_type="author")+".yml")
                    auth_folder = root
                versF = os.path.join(root, file)
                bookF = os.path.join(root, uri.build_uri(uri_type="book")+".yml")
                authF = os.path.join(auth_folder, uri.build_uri(uri_type="author")+".yml")
                #print("versF:", versF)
                #print("bookF:", bookF)
                #print("authF:", authF)

                # bring together all yml data related to the current version
                # and store in the master dataYML variable:
##                versD = zfunc.dicToYML(zfunc.readYML(versF)) + "\n"
##                bookD = zfunc.dicToYML(zfunc.readYML(bookF)) + "\n"
##                authD = zfunc.dicToYML(zfunc.readYML(authF)) + "\n"
                versD = readYML(versF)
                versD_yml = dicToYML(versD) + "\n"
                try:
                    bookD = readYML(bookF)
                    bookD_yml = dicToYML(bookD) + "\n"
                except:
                    print("No book yml file found")
                    bookD = ""
                    bookD_yml = ""
                try:
                    authD = readYML(authF)
                    authD_yml = dicToYML(authD) + "\n"
                except:
                    print("No author yml file found")
                    authD = ""
                    bookD_yml = ""
                record = splitter + versD_yml + bookD_yml + authD_yml
                dataYML.append(record)

                # collect the metadata related to the current version:


                # 1) from the YML files:

                # - length in number of characters:
##                versD = zfunc.readYML(versF)
##                versD = readYML(versF)
                length = versD["00#VERS#LENGTH###:"].strip()
                if incl_char_length:
                    try:
                        char_length = versD["00#VERS#CLENGTH##:"].strip()
                    except:
                        uri.extension = ""
                        #pth = uri.build_pth(uri_type="version_file")
                        pth = versF[:-4]
                        for ext in [".mARkdown", ".completed", ".inProgress", ""]:
                            version_fp = pth + ext
                            if os.path.exists(version_fp):
                                char_length = ar_cnt_file(version_fp, mode="char")
                                char_length = str(char_length)
                                versD["00#VERS#CLENGTH##:"] = char_length
                                ymlS = dicToYML(versD)
                                with open(versF, mode="w", encoding="utf-8") as file:
                                    file.write(ymlS)
                                break

                # - edition information:
                ed_info = []
                if not versD["80#VERS#BASED####:"].strip().startswith("perma")\
                   and not versD["80#VERS#BASED####:"].strip().startswith("NO"):
                    ed_info = [versD["80#VERS#BASED####:"].strip(), ]

                # - title:
##                bookD = zfunc.readYML(bookF)
                title_lat = []
                title_ar = []
##                try:
##                    bookD = readYML(bookF)
##                    #title = []
                if bookD:
                    for c in ["10#BOOK#TITLEA#AR:", "10#BOOK#TITLEB#AR:"]:
                        if not "al-Muʾallif" in bookD[c]:
    ##                        title.append(bookD[c].strip())
    ##                        title.append(betaCodeToArSimple(title[-1]))
                            title_lat.append(bookD[c].strip())
                            title_ar.append(betaCodeToArSimple(title_lat[-1]))
##                except:
##                    print("No book yml file found")

 
                # - author:
##                authD = zfunc.readYML(authF)
                shuhra = ""
                full_name = ""
##                try:
##                    authD = readYML(authF)
                if authD:
                    if not "Fulān" in authD["10#AUTH#SHUHRA#AR:"]:
                        shuhra = authD["10#AUTH#SHUHRA#AR:"].strip()
                    name_comps = ["10#AUTH#LAQAB##AR:",
                                  "10#AUTH#KUNYA##AR:",
                                  "10#AUTH#ISM####AR:",
                                  "10#AUTH#NASAB##AR:",
                                  "10#AUTH#NISBA##AR:"]
                    full_name = [authD[x] for x in name_comps \
                                 if "Fulān" not in authD[x]]
                    full_name = " ".join(full_name)
##                except:
##                    print("No author yml file found")


                # 2) from the URI: 

                # - date:
                date = uri.date

                # - author:
##                author = insert_spaces(uri.author)
                author_from_uri = insert_spaces(uri.author)
                author_lat = [author_from_uri, ]
                author_ar = []

                # - book title:
##                if not title:
##                    title.append(insert_spaces(uri.title))
                if not title_lat:
                    title_lat.append(insert_spaces(uri.title))

                # - book URI
                bookURI = uri.build_uri("book")

                # - version URI:
                versURI = uri.build_uri("version")

                # - collection ID:
                coll_id = re.findall("[A-Za-z]+", versURI.split(".")[-1])[0]

                # - make a provisional (i.e., without extension)
                #   local filepath  to the current version:
                uri.extension = ""
                #local_pth = uri.build_pth("version_file")
                local_pth = re.sub(r"\\", "/", versF[:-4])
                #print("local_pth:", local_pth)
                #print(local_pth)

                # - set temporary secondary status for every book.
                #   the primary version of a book is the one that
                #   has the most developed annotation
                #   (signalled by the extension: mARkdown>completed>inProgress)
                #   If no version has an extension,
                #   the longest version will provisorally be considered primary.
                #   The length comparison can take place only after all versions
                #   have been documented.
                #   For this reason, versions with an extension
                #   are provisionally given a very high number
                #   in the statusDic instead of their real length,
                #   so that they will be chosen as primary version
                #   once the lengths are compared:
                status = "sec"
                if os.path.isfile(local_pth+".inProgress"):
                    lenTemp = 100000000
                    uri.extension = "inProgress"
                elif os.path.isfile(local_pth+".completed"):
                    lenTemp = 1000000000
                    uri.extension = "completed"
                elif os.path.isfile(local_pth+".mARkdown"):
                    lenTemp = 10000000000
                    uri.extension = "mARkdown"
                elif "Sham30K" in local_pth: # give Sham30K files lowest priority
                    lenTemp = 0
                    uri.extension = ""
                else:
                    uri.extension = ""
                    if length:
                        lenTemp = length
                    else:
                        lenTemp = 0

                # - rebuild the local_path, with the extension:
                #local_pth = uri.build_pth("version_file")
                if uri.extension:
                    local_pth+= "." + uri.extension

                # - add the uri to the statusDic if the file is not missing:
                if os.path.exists(local_pth):
                    
                    if bookURI in statusDic:
                        statusDic[bookURI].append("%012d##" % int(lenTemp) + versURI)
                    else:
                        statusDic[bookURI] = []
                        statusDic[bookURI].append("%012d##" % int(lenTemp) + versURI)


##                # - build the path to the full text file on Github:
##                if URI.data_in_25_year_repos:
##                    uri.base_pth = "https://raw.githubusercontent.com/OpenITI"
##                    #fullTextURL = re.sub("data/", "master/data/", uri.build_pth("version_file"))
##                    fullTextURL = re.sub("data/", "master/data/", local_pth) 
##                else:
##                    uri.base_pth = "data"
##                    #fullTextURL = uri.build_pth("version_file")
##                    fullTextURL = re.sub(".+?/data/", "data/", local_pth)

                # - build the link/path to the text file in the output file:
                
                #print(fullTextURL)
                if output_files_path:
                    fullTextURL = re.sub(start_folder, output_files_path, local_pth)
                else:
                    fullTextURL = local_pth
                if "githubusercontent" in fullTextURL:
                    fullTextURL = re.sub("data/", "master/data/", fullTextURL)

                # - tags (for extension + "genres")
                tags = ""
                if uri.extension:
                    tags += uri.extension.upper()+","
                if uri.version in tagsDic:
                    tags += tagsDic[uri.version]
                    #print(uri.version, tagsDic[uri.version])
                if bookD and not bookD["10#BOOK#GENRES###:"].startswith("src"):
                    tags += "," + bookD["10#BOOK#GENRES###:"]
                version_tags = re.findall("[A-Z_]{5,}",
                                          versD["90#VERS#ISSUES###:"])
                if version_tags:
                    tags += "," + ",".join(version_tags)
                


                # 3) collect additional metadata (mostly in Arabic!)
                #    from the text file headers:

                if not os.path.exists(local_pth):
                    print("MISSING FILE? {} does not exist".format(local_pth))
                else:
                    header_meta = extract_metadata_from_header(local_pth)
                    #print(local_pth, header_meta)

                    # - author name (combine with the uri's author component)
                    #add_arabic_name = True
                    if shuhra:
                        author_lat.append(shuhra)
                        author_ar.append(betaCodeToArSimple(shuhra))
                        print(betaCodeToArSimple(shuhra))
                        #add_arabic_name = False
                    if full_name:
                        author_lat.append(full_name)
                        author_ar.append(betaCodeToArSimple(full_name))
                        #add_arabic_name = False
                    #if add_arabic_name:
##                        author = [author,] + list(set(header_meta["AuthorName"]))
                    if not author_ar: # if no Arabic author name was taken from YML files:
                        author_ar = list(set(header_meta["AuthorName"]))

                    # - book title (combine with the uri's title component)
##                    if len(title) < 2: # if no title was taken from the YML file
##                        title += list(set(header_meta["Title"]))
                    if not title_ar: # if no title was taken from the YML file
                        title_ar += list(set(header_meta["Title"]))

                    # - information about the current version's edition: 
                    ed_info = header_meta["Edition:Editor"] +\
                              header_meta["Edition:Place"] +\
                              header_meta["Edition:Date"] +\
                              header_meta["Edition:Publisher"] +\
                              ed_info

                    # - additional genre tags:
##                    tags = tags.split(",") + list(set(header_meta["Genre"]))
                    tags = tags.split(",")
                    for el in header_meta["Genre"]:
                        for t in el.split(" :: "):
                            if coll_id+"@"+t not in tags:
                                tags.append(coll_id+"@"+t)

                    # if there are multiple values: separate with " :: ":
##                    cats = [author, title, ed_info, tags]
##                    author, title, ed_info, tags = [" :: ".join(x) for x in cats]
                    cats = [author_ar, author_lat, title_ar, title_lat, ed_info, tags]
                    author_ar, author_lat, title_ar, title_lat, ed_info, tags = [" :: ".join(x) for x in cats]

                    # compile the data in a tsv line and store in dataCSV dict:
                    if not split_ar_lat:
                        title = " :: ".join([title_lat, title_ar])
                        author = " :: ".join([author_lat,author_ar])
                        v = [versURI, date, author, bookURI, title, ed_info,
                             uri.version, status, length, fullTextURL, tags,
                             author_from_uri, shuhra, full_name]
                    else:
                        v = [versURI, date, author_ar, author_lat, bookURI,
                             title_ar, title_lat, ed_info,
                             uri.version, status, length, fullTextURL, tags,
                             author_from_uri, shuhra, full_name]
                    if incl_char_length:
                        v.append(char_length)
                    value = "\t".join(v)
                    dataCSV[versURI] = value

                # Deal with files split into multiple parts because
                # they were too big: 
                if re.search("[A-Z]-", versURI):
                    print(versURI)
                    m = re.sub("[A-Z]-", "-", versURI)
                    if m not in split_files:
                        split_files[m] = []
                    split_files[m].append(versURI)


    # Give primary status to "longest" version:
    for k, v in statusDic.items():
        v = sorted(v, reverse=True)
        key = v[0].split("##")[1]
        dataCSV[key] = dataCSV[key].replace("\tsec\t", "\tpri\t")


    # define the csv file header: 
    if not split_ar_lat:
        h = ["versionUri", "date", "author", "book",
             "title", "ed_info", "id", "status",
             "tok_length", "url",
             #"instantiation", "localPath",
             "tags", "author_from_uri", "author_shuhra", "author_full_name"]
    else:
        h = ["versionUri", "date", "author_ar", "author_lat", "book",
             "title_ar", "title_lat", "ed_info", "id", "status",
             "tok_length", "url",
             #"instantiation", "localPath",
             "tags", "author_from_uri", "author_lat_shuhra", "author_lat_full_name"]
    if incl_char_length:
        h.append("char_length")
    header = "\t".join(h)

    # Write a json file containing all texts that have been split
    # into parts because they were too big (URIs with VolsA, VolsB, ...):
    split_files_fp = re.sub("metadata_light.csv", "split_files.json", csv_outpth)
    with open(split_files_fp, mode='w', encoding='utf-8') as outfile:
        json.dump(split_files, outfile, indent=4)  

    # add data for files split into multiple parts:
    
    for file in split_files:
##        print(file, "consists of mutltiple files:")
##        print(split_files[file])
        first_part = split_files[file][0]
        file_length = 0
        file_clength = 0
        for part in split_files[file]:
            # make each part a primary version:
            dataCSV[part] = dataCSV[part].replace("\tsec\t", "\tpri\t")
            # collect the token and character length from each part
            file_length += int(dataCSV[part].split("\t")[h.index("tok_length")])
            if incl_char_length:
                file_clength += int(dataCSV[part].split("\t")[-1])
        # add an extra line to the csv data with metadata of the compound file:
        file_csv_line = dataCSV[first_part].split("\t")
        file_csv_line[h.index("versionUri")] = file
        #file_csv_line[h.index("id")] = re.sub("Vols[A-Z]", "", file_csv_line[h.index("id")])
        file_csv_line[h.index("id")] = file_csv_line[h.index("id")][:-1]
        file_csv_line[h.index("status")] = "sec"
        file_csv_line[h.index("tok_length")] = str(file_length)
        print(file_csv_line[h.index("url")])
        #file_csv_line[h.index("url")] = re.sub("Vols[A-Z]", "",
        file_csv_line[h.index("url")] = re.sub("[A-Z](-[a-z]{3}\d)", r"\1",
                                               file_csv_line[h.index("url")]) # fullTextURL
        print(file_csv_line[h.index("url")])
        print("---")
        if incl_char_length:
            file_csv_line[-1] = str(file_clength)
        file_csv_line = "\t".join(file_csv_line)
        dataCSV[file] = file_csv_line

    # Sort the tsv data and save it to file: 
    dataCSV_New = []
    for k, v in dataCSV.items():
        #print("\t"+k)
        dataCSV_New.append(v)
    dataCSV = sorted(dataCSV_New)

    print("="*80)
    print("COLLECTING INTO A CSV FILE ({} LINES)...".format(len(dataCSV)))
    print("="*80)


    
    with open(csv_outpth, "w", encoding="utf8") as outfile:
        outfile.write(header+"\n"+"\n".join(dataCSV))#.replace(" ", ""))

    # Finally, also save the combined yml data in a master yml file: 
    with open(yml_outpth, "w", encoding="utf8") as outfile:
        outfile.write("\n".join(dataYML))

def restore_config_to_default():
    def_config = """\
# RESTORED DEFAULTS:

# Path to the input folder:
corpus_path = ""

# list of folder names to be excluded from metadata generation:
exclude = (["OpenITI.github.io", "Annotation", "maintenance", "i.mech00",
            "i.mech01", "i.mech02", "i.mech03", "i.mech04", "i.mech05",
            "i.mech06", "i.mech07", "i.mech08", "i.mech09", "i.logic",
            "i.cex", "i.cex_Temp", "i.mech", "i.mech_Temp", ".git"])

# Set to True if the data is in 25-year folders, False if they are not:
data_in_25_year_repos = None  # True/False

# Set to True if the script needs to check completeness of the yml files:
perform_yml_check = None  # True/False

# Set to True if the script needs to update the token counts in the yml files:
check_token_counts = None  # True/False

# Set to True if the script needs to include character length in the yml files:
incl_char_length = None  # True/False

# Split title and author data in Arabic and Latin script into separate columns:
split_ar_lat = None  # True/False

# path to the output folder:
output_path = "./output/"

# Use this path instead of the `corpus_path` for text and yml files in output metadata:
# E.g., "https://raw.githubusercontent.com/OpenITI", ".."
output_files_path = None  # write path to use instead of corpus_path

# path to the output files (default: in the folder at output_path)
meta_tsv_fp = None
meta_yml_fp = None
meta_json_fp = None
meta_header_fp = None

# List of lists (description, run_id on server):  
passim_runs = [['October 2017 (V1)', 'passim1017'],
               ['February 2019 (V2)', 'passim01022019'],
#               ['May 2019 (Aggregated)', 'aggregated01052019'],
               ['February 2020', 'passim01022020'],
               ['October 2020', 'passim01102020']]

# Set to True to allow the script to make changes to yml files without asking:
silent = False  # True/False"""
    
    with open("utility/config.py", mode="w", encoding="utf-8") as file:
        file.write(def_config)

def check_input(msg, responses={"Y": True, "N": False}):
    print(msg)
    responses = {k.upper(): v for k,v in responses.items()}
    r = input("{}? ".format("/".join(responses.keys())))
    if r.upper() in responses:
        return responses[r.upper()]
    else:
        print("Response not recognized. Try again:")
        return check_input(msg, responses)

def get_github_issues(token_fp="GitHub personalAccessTokenReadOnly.txt"):
    try:
        with open(token_fp, mode="r", encoding="utf-8") as file:
            github_token = file.read().strip()
    except:
        github_token = None # you will be prompted to insert the token manually

    issues = get_issues.get_issues("OpenITI/Annotation",
                                   access_token=github_token,
                                   issue_labels=["URI change suggestion",
                                                 "text quality",
                                                 "PRI & SEC Versions"])
    issues = get_issues.define_text_uris(issues)
    issues_uri_dict = get_issues.sort_issues_by_uri(issues)
    return issues_uri_dict

def supplement_config_variables(cfg_dict, v_list):
    """Check if all vars in v_list are in config_dict; \
    add missing vars with value None."""
    for v in v_list:
        if v not in cfg_dict:
            cfg_dict[v] = None

def read_config(config_pth):
    """Read the config file into a dictionary

    NB: Python's ConfigParser works with config files that contain sections.
        Since our config files do not have sections, a dummy section is added.
        See https://stackoverflow.com/a/25493615.
    """
    with open(config_pth, mode="r") as file:
        config_string = "[dummy_section]\n" + file.read()
    cp = configparser.ConfigParser(inline_comment_prefixes=["#"])
    cp.read_string(config_string)
    cfg_dict = dict(cp["dummy_section"])
    for k,v in cfg_dict.items():
        if v.strip() == "True":
            cfg_dict[k] = True
        elif v.strip() == "False":
            cfg_dict[k] = False
        elif v.strip() == "None":
            cfg_dict[k] = None
        elif v.strip().startswith(("(", "[", "{")):
            #cfg_dict[k] = json.loads(v.strip())
            cfg_dict[k] = eval(v.strip())
        elif v.strip().startswith(("r'", 'r"')):
            cfg_dict[k] = v.strip()[2:-1].replace("\\", "/")
            print(v, ">", v.strip()[2:-1].replace("\\", "/"))
        elif v.strip().startswith(("'", '"')):
            cfg_dict[k] = v.strip()[1:-1]
    return cfg_dict
    


def main():
    
    info = """\
Command line arguments for generate-metadata.py:

-h, --help : print help info
-t, --token_counts : update character and token counts
                     => sets check_token_counts variable to True
-l, --char_length : include character counts in metadata
                    => sets incl_char_length to True
-f, --flat_data : data not in 25 year repos
                  => sets data_in_25_year_repos to False
-d, --restore_default : restore values in config.py to default
-r, --recheck_yml : include a check of whether all yml files are complete
-p, --split_ar_lat : put arabic and latin info in separate columns
-s, --silent : execute changes to yml files without asking questions

-i, --input_folder : (str) path to the input folder
                           => sets corpus_path variable
-o, --output_folder : (str) path to the output folder for metadata files
                            => sets output_path variable
                            (default = "./output/")
-t, --tsv_fp : (str) file path to the tsv output file
                     (only if you do not want it in the defined output folder)
                     => sets meta_tsv_fp variable
-y, --yml_fp : (str) file path to the yml output file
                     (only if you do not want it in the defined output folder)
                     => sets meta_yml_fp variable
-j, --json_fp : (str) file path to the json output file
                      (only if you do not want it in the defined output folder)
                      => sets out_fp variable
-a, --arab_header_fp: (str) file path to the json file 
                            that will contain all Arabic metadata 
                            extracted from text file headers.
                            (only if you do not want it in the defined output folder)
                            => sets meta_header_fp variable
-x, --exclude : (list) list of folder names to exclude from metadata
-c, --config : (str) name of a python file with custom configuration variables
                     (default: ./utility/config.py)
"""
    argv = sys.argv[1:]
    opt_str = "htlfdprsi:o:t:y:j:a:x:c:"
    opt_list = ["help", "token_counts", "char_length", "flat_data",
                "restore_default", "split_ar_lat", "recheck_yml", "silent",
                "input_folder=", "output_folder=", "csv_fp=", "yml_fp=",
                "json_fp=", "arab_header_fp=", "exclude=", "config="]
    try:
        opts, args = getopt.getopt(argv, opt_str, opt_list)
    except Exception as e:
        print(e)
        print("Input incorrect: \n"+info)
        sys.exit(2)

    # 0a- import variables from config file

    configured = False
    for opt, arg in opts:
        if opt in ["-c", "--config"]:
            # load variables from custom config file provided in command line:
            print ("config", arg)
            shutil.copy(arg, "utility/temp_config.py")
##            from utility.temp_config import corpus_path, \
##                               exclude, data_in_25_year_repos, \
##                               perform_yml_check, check_token_counts, \
##                               incl_char_length, output_path, \
##                               meta_tsv_fp, meta_yml_fp, \
##                               meta_json_fp, meta_header_fp, \
##                               passim_runs, silent, split_ar_lat
            cfg_dict = read_config("utility/temp_config.py")
            os.remove("utility/temp_config.py")
            configured = True
        elif opt in ["-d", "--restore_default"]:
            restore_config_to_default()
            print("default values in config.py restored")
    if not configured: # load variables from default configuration file
        cfg_dict = read_config("utility/config.py")
##        from utility.config import corpus_path, exclude, \
##                               data_in_25_year_repos, \
##                               perform_yml_check, check_token_counts, \
##                               incl_char_length, output_path, \
##                               meta_tsv_fp, meta_yml_fp, \
##                               meta_json_fp, meta_header_fp, \
##                               passim_runs, silent, split_ar_lat

##    for k,v in cfg_dict.items():
##        print([k,v])
##    input("continue?")

    v_list = ["corpus_path", "exclude", "data_in_25_year_repos",
              "perform_yml_check", "check_token_counts",
              "incl_char_length", "output_path",
              "meta_tsv_fp", "meta_yml_fp", "meta_json_fp", "meta_header_fp",
              "passim_runs", "silent", "split_ar_lat", "output_files_path"]
    supplement_config_variables(cfg_dict, v_list)

    corpus_path = cfg_dict["corpus_path"]
    exclude = cfg_dict["exclude"]
    data_in_25_year_repos = cfg_dict["data_in_25_year_repos"]
    perform_yml_check = cfg_dict["perform_yml_check"]
    check_token_counts = cfg_dict["check_token_counts"]
    incl_char_length = cfg_dict["incl_char_length"]
    output_path = cfg_dict["output_path"]
    meta_tsv_fp = cfg_dict["meta_tsv_fp"]
    meta_yml_fp = cfg_dict["meta_yml_fp"]
    meta_json_fp = cfg_dict["meta_json_fp"]
    meta_header_fp = cfg_dict["meta_header_fp"]
    passim_runs = cfg_dict["passim_runs"]
    silent = cfg_dict["silent"]
    split_ar_lat = cfg_dict["split_ar_lat"]
    output_files_path = cfg_dict["output_files_path"]

    print("output_files_path", output_files_path)


    # 0b- override config variables from command line arguments:

    for opt, arg in opts:
        if opt in ["-h", "--help"]:
            print(info)
            return
        elif opt in ["-t", "--token_counts"]:
            check_token_counts = True
            print("check_token_counts", check_token_counts)
        elif opt in ["-l", "--char_length"]:
            incl_char_length = True
            print("incl_char_length", incl_char_length)
        elif opt in ["-f", "--flat_data"]:
            data_in_25_year_repos = False
            print("data_in_25_year_repos", data_in_25_year_repos)
        elif opt in ["-p", "--split_ar_lat"]:
            split_ar_lat = True
            print("split_ar_lat", split_ar_lat)
        elif opt in ["-r", "--recheck_yml"]:
            perform_yml_check = True
            print("perform_yml_check", perform_yml_check)
        elif opt in ["-s", "--silent"]:
            silent = True
            print("silent", silent)
        elif opt in ["-i", "--input_folder"]:
            corpus_path = arg
            print("corpus_path", corpus_path)
        elif opt in ["-o", "--output_folder"]:
            output_path = arg
            print("output_path", output_path)
        elif opt in ["-t", "--tsv_fp"]:
            meta_tsv_fp = arg
            print("meta_tsv_fp", meta_tsv_fp)
        elif opt in ["-y", "--yml_fp"]:
            meta_yml_fp = arg
            print("meta_yml_fp", meta_yml_fp)
        elif opt in ["-j", "--json_fp"]:
            meta_json_fp = arg
            print("out_fp", out_fp)
        elif opt in ["-a", "--arab_header_fp"]:
            meta_header_fp = arg
            print("meta_header_fp", meta_header_fp)
        elif opt in ["-x", "--exclude"]:
            exclude = arg
            print("exclude", exclude)

    # 0c- deal with variables that remain undefined:
 
    if not corpus_path:
        msg = "Insert the path to the parent folder of the repos: "
        corpus_path = input(msg)
        print("Metadata will be collected in", corpus_path)

    if output_files_path == None:
        msg = "Do you want to use another path (e.g., relative path, URL) to this folder in the output file?"
        print(msg)
        r = input("Y/N? ")
        if r.lower() == "y":
            msg = "Write the path to the parent folder of the repos for use in output file: "
            output_files_path = input(msg)
 
    flat_folder = False
    if data_in_25_year_repos == None:
##        print("Is the data in 25-years folders? (press 'N' for RELEASE data)")
##        resp = input("Y/N: ")
##        check_input(msg, responses={"Y": True, "N": False})
##        if resp.upper() == "N":
##            data_in_25_year_repos = False
##        else:
##            data_in_25_year_repos = True
        msg = "Is the data in 25-years folders? (press 'N' for RELEASE data)"
        data_in_25_year_repos = check_input(msg)
        if not data_in_25_year_repos:
            msg = "Is the folder structure entirely flat? "
            flat_folder = check_input(msg)
    URI.data_in_25_year_repos = data_in_25_year_repos

    if perform_yml_check == None:
##        print("Do you want to check completeness of the yml files?")
##        resp = input("Y/N: ")
##        if resp.upper() == "Y":
##            perform_yml_check = True
        msg = "Do you want to check completeness of the yml files?"
        perform_yml_check = check_input(msg)
        if perform_yml_check:
            print("Do you want to re-calculate the Arabic token length of every text?")
            print("This may take up to an hour on a slow machine.")
            resp = input("Y/N: ")
            if resp == "Y":
                check_token_counts = True
            else:
                check_token_counts = False
 
    if incl_char_length == None:
##        print("Do you want to include character count in addition to token count?")
##        resp = input("Y/N: ")
##        if resp.upper() == "Y":
##            incl_char_length = True
##        else:
##            incl_char_length = False
        msg = "Do you want to include character count in addition to token count?"
        incl_char_length = check_input(msg)

    if split_ar_lat == None:
        msg = "Do you want to keep Arabic and Latin metadata in separate columns?"
        split_ar_lat = check_input(msg)



    pth_string = re.sub("\.+[\\/]", "", corpus_path)
    pth_string = re.sub(r"[\\/]", "_", pth_string)
    pth_string = os.path.join(output_path, pth_string)
    if meta_yml_fp == None: 
        meta_yml_fp = pth_string + "_metadata_complete.yml"
    if meta_tsv_fp == None: 
        meta_tsv_fp = pth_string + "_metadata_light.csv"
    if meta_json_fp == None:
        meta_json_fp = pth_string + "_metadata_light.json"
    if meta_header_fp == None:
        meta_header_fp = pth_string + "_header_metadata.json"

    print("corpus_path", corpus_path)
    print("exclude", exclude)
    print("data_in_25_year_repos", data_in_25_year_repos)
    print("perform_yml_check", perform_yml_check)
    print("check_token_counts", check_token_counts)
    print("incl_char_length", incl_char_length)
    print("output_path", output_path)
    print("meta_tsv_fp", meta_tsv_fp)
    print("meta_yml_fp", meta_yml_fp)
    print("meta_json_fp", meta_json_fp)
    print("meta_header_fp", meta_header_fp)
    print("silent", silent)
    print("output_files_path", output_files_path)

    if not silent:
        input("Press Enter to start generating metadata ")

    start = time.time()
        
    # 1a- check and update yml files:

    if perform_yml_check:
        print("Checking yml files before collecting metadata...")
        # execute=False forces the script to show you all changes it wants to make
        # before prompting you whether to execute the proposed changes:
        check_yml_files(corpus_path, exclude=exclude,
                        execute=silent, check_token_counts=check_token_counts)
        print()
        end = time.time()
        print("Processing time: {0:.2f} sec".format(end - start))

    # 1b- collect metadata and save to csv:

    end = time.time()
    print("="*80)
    print("Collecting metadata...")
    collectMetadata(corpus_path, exclude, meta_tsv_fp, meta_yml_fp,
                    incl_char_length=incl_char_length,
                    split_ar_lat=split_ar_lat, flat_folder=flat_folder,
                    output_files_path=output_files_path)
    temp = end
    end = time.time()
    print("Processing time: {0:.2f} sec".format(end - start))

    # 1c - get github issues:

    print("="*80)
    print("Collecting issues from GitHub...")
    issues_uri_dict = get_github_issues()
    temp = end
    end = time.time()
    print("GitHub fetching time: {0:.2f} sec".format(end - temp))

    # 2a - Save main metadata

    print("="*80)
    print("Saving metadata...")
    print("="*80)

##    passim_runs = [['October 2017 (V1)', 'passim1017'],
##                   ['February 2019 (V2)', 'passim01022019'],
##                   ['May 2019 (Aggregated)', 'aggregated01052019'],
##                   ['February 2020', 'passim01022020']]
    createJsonFile(meta_tsv_fp, meta_json_fp, passim_runs, issues_uri_dict)

    
    # 2b- Save header metadata

    with open(meta_header_fp, mode="w", encoding="utf-8") as file:
        json.dump(all_header_meta, file, ensure_ascii=False)

    print("Tada!")
    print("Total processing time: {0:.2f} sec".format(end - start))




if __name__ == "__main__":
    main()
