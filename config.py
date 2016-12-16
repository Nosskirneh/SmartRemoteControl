import os
import xml.etree.ElementTree as ET

# Change to directory of script so relative file references work.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Name of configuration file.
FILE_NAME = 'activities.xml'

act = []

def get_activities():
    root = ET.parse(FILE_NAME)
    sections = root.findall('section')
    for s in sections:
        activities = s.findall('activity')
        for a in activities:
            codes = a.findall('code')
            codeList = {}
            for c in codes:
                codeList[c.attrib['type']] = []           # create list from code type
                codeList[c.attrib['type']].append(c.text) # add instruction to the corresponding group in codeList
        d = dict([(a.attrib['name'], codeList)])          # make a dict from the activity name and corresponding codes
        f = [d, s.attrib['name']]                         # make a list of the dict and group name
        act.append(f)                                     # add the list to the activity list
    return act

def get_acts_simple():
    root = ET.parse(FILE_NAME)
    groups = []
    total = []
    sections = root.findall('section')
    for s in sections:
        groupName = s.attrib['name']
        if groupName not in groups:
            groups.append(groupName)
            total.append({groupName: []})

        activities = s.findall('activity')
        for a in activities:
            actName = a.attrib['name']
            for t in total:
                if groupName in t.keys():
                    t[groupName].append(actName)
    return total
