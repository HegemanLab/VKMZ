#!/usr/bin/env python

import argparse
import csv
import math
import re
 
parser = argparse.ArgumentParser()
inputSubparser = parser.add_subparsers(help='Select mode:', dest='mode')
parse_db = inputSubparser.add_parser('db', help='Construct Database.')
parse_db.add_argument('--input', '-i', required=True, help='Path to tabular database file. The first two columns must be "mass" and "formula".')
parse_db.add_argument('--output','-o', nargs='?', type=str, required=True, help='Specify output file path.')
parse_tsv = inputSubparser.add_parser('tsv', help='Use tabular data as input.')
parse_tsv.add_argument('--input', '-i', required=True, help='Path to tabular file. Must include columns: sample ID, mz, polarity, intensity, & retention time.')
parse_xcms = inputSubparser.add_parser('xcms', help='Use XCMS data as input.')
parse_xcms.add_argument('--data-matrix', '-xd', required=True, nargs='?', type=str, help='Path to XCMS data matrix file.')
parse_xcms.add_argument('--sample-metadata', '-xs', required=True, nargs='?', type=str, help='Path to XCMS sample metadata file.')
parse_xcms.add_argument('--variable-metadata', '-xv', required=True, nargs='?', type=str, help='Path to XCMS variable metadata file.')
for inputSubparser in [parse_tsv, parse_xcms]:
  inputSubparser.add_argument('--output',   '-o', nargs='?', type=str, required=True, help='Specify output file path.')
  inputSubparser.add_argument('--error',    '-e', nargs='?', type=float, required=True, help='Mass error of mass spectrometer in parts-per-million.')
  inputSubparser.add_argument('--database', '-db', nargs='?', default='databases/bmrb-light.tsv', help='Select database of known formula masses.')
  inputSubparser.add_argument('--directory','-dir', nargs='?', default='', type=str, help='Define path of tool directory. Assumes relative path if unset.')
  inputSubparser.add_argument('--polarity', '-p', choices=['positive','negative'], help='Force polarity mode to positive or negative. Overrides variables in input file.')
  inputSubparser.add_argument('--neutral',  '-n', action='store_true', help='Set neutral flag if masses in input data are neutral. No mass adjustmnet will be made.')
  inputSubparser.add_argument('--unique',   '-u', action='store_true', help='Set flag to remove features with multiple predictions.')
args = parser.parse_args()

featureList = []
class Feature(object):
 def __init__(self, sample_id, polarity, mz, rt, intensity):
   self.sample_id = sample_id
   self.polarity = polarity
   self.mz = mz
   self.rt = rt
   self.intensity = intensity

def makeFeature(sample_id, polarity, mz, rt, intensity):
  feature = Feature(sample_id, polarity, mz, rt, intensity)
  return feature

# store input constants
MODE = getattr(args, "mode")
OUTPUT = getattr(args, "output")

if MODE == "db":
  dbFileIn = getattr(args, "input")
  try:
    with open(dbFileIn, 'r') as f:
      database = []
      dbData = csv.reader(f, delimiter='\t')
      next(dbData) 
      for row in dbData:
        if not row[0].isspace() and not row[1].isspace():
          database.append((float(row[0]), row[1].strip().replace(" ","")))
      database = sorted(set(database))
      try:
        with open(OUTPUT, 'w') as dbFileOut: 
          dbFileOut.write("mass\tformula\n")
          for pair in database:
            dbFileOut.write(str(pair[0])+'\t'+pair[1]+'\n')
    except ValueError:
      print('Error while writing the %s database file.' % dbFileOut)
  except ValueError:
    print('Error while reading the %s database file.' % dbFileIn)
  exit()

def polaritySanitizer(sample_polarity):
  if sample_polarity.lower() in {'positive','pos','+'}:
    sample_polarity = 'positive'
  elif sample_polarity.lower() in {'negative', 'neg', '-'}:
    sample_polarity = 'negative'
  else:
    print('A sample has an unknown polarity type: %s. Polarity in the XCMS sample metadata should be set to "negative" or "positive".' % sample_polarity)
    raise ValueError
  return sample_polarity

# read input
POLARITY = getattr(args, "polarity")
if MODE == "tsv":
  tsvFile = getattr(args, "input")
  try:
    with open(tsvFile, 'r') as f:
      next(f) # skip hearder line
      tsvData = csv.reader(f, delimiter='\t')
      for row in tsvData:
        feature = makeFeature(row[0], polaritySanitizer(row[1]), float(row[2]), float(row[3]), float(row[4]))
        featureList.append(feature)
  except ValueError:
    print('The %s data file could not be read.' % tsvFile)
else: # MODE == "xcms"
  # extract sample polarities
  xcmsSampleMetadataFile = getattr(args, "sample_metadata")
  try:
    polarity = {}
    with open(xcmsSampleMetadataFile, 'r') as f:
      xcmsSampleMetadata = csv.reader(f, delimiter='\t')
      next(xcmsSampleMetadata, None) # skip header
      for row in xcmsSampleMetadata:
        sample = row[0]
        if POLARITY:
          polarity[sample] = POLARITY
        else:
          sample_polarity = polaritySanitizer(row[2])
          polarity[sample] = sample_polarity
  except ValueError:
    print('The %s data file could not be read. Check that polarity is set to "negative" or "positive"' % xcmsSampleMetadataFile)
  # extract variable mz & rt
  xcmsVariableMetadataFile = getattr(args, "variable_metadata")
  try:
    mz = {}
    rt = {}
    variable_index = {}
    mz_index = int()
    rt_index = int()
    with open(xcmsVariableMetadataFile, 'r') as f:
      xcmsVariableMetadata = csv.reader(f, delimiter='\t')
      i = 0
      for row in xcmsVariableMetadata:
        if i != 0:
          mz[row[0]] = float(row[mz_index])
          rt[row[0]] = float(row[rt_index])
        else:
          for column in row:
            variable_index[column] = i
            i += 1
          mz_index = variable_index["mz"]
          rt_index = variable_index["rt"]
  except ValueError:
    print('The %s data file could not be read.' % xcmsVariableMetadataFile)
  # extract intensity and relate polarity, mz, & rt to variable names
  # to create feature objects
  xcmsDataMatrixFile = getattr(args, "data_matrix")
  try:
    with open(xcmsDataMatrixFile, 'r') as f:
      xcmsDataMatrix = csv.reader(f, delimiter='\t')
      samples = next(xcmsDataMatrix, None)
      # remove empty columns, XCMS bug?
      samples = [x for x in samples if x is not '']
      for row in xcmsDataMatrix:
        row = [x for x in row if x is not '']
        i = 1
        while(i < len(row)):
          intensity = row[i] # keep as string for test
          if intensity not in {"NA", "#DIV/0!", '0'}:
            variable = row[0]
            sample_id = samples[i]
            feature = makeFeature(sample_id, polarity[sample], mz[variable], rt[variable], float(intensity))
            featureList.append(feature)
          i+=1
  except ValueError:
    print('The %s data file could not be read.' % xcmsDataMatrixFile)

# store||generate remaining constants
MASS_ERROR = getattr(args, "error")
UNIQUE = getattr(args, "unique")
NEUTRAL = getattr(args, "neutral")
DATABASE = getattr(args, "database")
DIRECTORY = getattr(args, "directory")
MASS = []
FORMULA = []
try:
  with open(DIRECTORY+DATABASE, 'r') as tsv:
    for row in tsv:
      mass, formula = row.split()
      MASS.append(mass)
      FORMULA.append(formula)
except ValueError:
  print('The %s database could not be loaded.' % DATABASE)
MAX_MASS_INDEX = len(MASS)-1

# adjust charged mass to a neutral mass
def adjust(mass, polarity):
  # value to adjust by
  proton = 1.007276
  if polarity == 'positive':
    mass -= proton
  else: # sanitized to negative
    mass += proton
  return mass

# binary search to match a neutral mass to known mass within error
def predict(mass, uncertainty, left, right):
  mid = int(((right - left) / 2) + left)
  if left <= mid <= right and mid <= MAX_MASS_INDEX:
    delta = float(MASS[mid]) - mass
    if uncertainty >= abs(delta):
      return mid
    elif uncertainty < delta:
      return predict(mass, uncertainty, left, mid-1)
    else:
      return predict(mass, uncertainty, mid+1, right)
  return -1

# find and rank predictions which are adjacent to the index of an intial prediction
def predictNeighbors(mass, uncertainty, prediction):
  i = 0
  neighbors = [(float(MASS[prediction]),FORMULA[prediction],(float(MASS[prediction])-mass)),]
  while prediction+i+1 <= MAX_MASS_INDEX:
    neighbor = prediction+i+1
    delta = float(MASS[neighbor])-mass
    if uncertainty >= abs(delta):
      neighbors.append((float(MASS[neighbor]),FORMULA[neighbor],delta))
      i += 1
    else:
      break
  i = 0
  while prediction+i-1 >= 0:
    neighbor = prediction+i-1
    delta = float(MASS[neighbor])-mass
    if uncertainty >= abs(delta):
      neighbors.append((float(MASS[neighbor]),FORMULA[neighbor],(float(MASS[neighbor])-mass)))
      i -= 1
    else:
      break
  neighbors = sorted(neighbors, key = (lambda delta: abs(delta[2])))
  return neighbors

# predict formulas by the mass of a feature
def featurePrediction(feature):
  if NEUTRAL:
    mass = feature.mz
  else:
    mass = adjust(feature.mz, feature.polarity) # mz & polarity
  uncertainty = mass * MASS_ERROR / 1e6
  prediction = predict(mass, uncertainty, 0, MAX_MASS_INDEX)
  if prediction != -1: # else feature if forgotten
    predictions = predictNeighbors(mass, uncertainty, prediction)
    if UNIQUE and len(predictions) > 1:
      return
    feature.predictions = predictions
    # calculate elemental ratios
    formula = predictions[0][1] # formula of prediction with lowest abs(delta)
    formulaList = re.findall('[A-Z][a-z]?|[0-9]+', formula)
    formulaDictionary = {'C':0,'H':0,'O':0,'N':0} # other elements are easy to add
    i = 0;
    while i < len(formulaList):
      if formulaList[i] in formulaDictionary:
        # if there is only one of this element
        if i+1 == len(formulaList) or formulaList[i+1].isalpha():
          formulaDictionary[formulaList[i]] = 1
        else:
          formulaDictionary[formulaList[i]] = formulaList[i+1]
          i+=1
      i+=1
    feature.hc = float(formulaDictionary['H'])/float(formulaDictionary['C'])
    feature.oc = float(formulaDictionary['O'])/float(formulaDictionary['C'])
    feature.nc = float(formulaDictionary['N'])/float(formulaDictionary['C'])
    return(feature)
 
# write output file
def write(predictionList):
  json = ''
  try: 
    # write tabular file and generate json for html output
    with open(OUTPUT+'.tsv', 'w') as fileTSV: 
      fileTSV.writelines("sample_id\tpolarity\tmz\trt\tintensity\tpredictions\thc\toc\tnc\n")
      for p in predictionList:
        fileTSV.writelines(p.sample_id+'\t'+p.polarity+'\t'+str(p.mz)+'\t'+str(p.rt)+'\t'+str(p.intensity)+'\t'+str(p.predictions)+'\t'+str(p.hc)+'\t'+str(p.oc)+'\t'+str(p.nc)+'\n')
        json += "{sample_id: \'"+p.sample_id+"\', polarity: \'"+p.polarity+"\', mz: "+str(p.mz)+", rt: "+str(p.rt)+", intensity: "+str(p.intensity)+", predictions: "+str(p.predictions)+", hc: "+str(p.hc)+", oc: "+str(p.oc)+", nc: "+str(p.nc)+"},"
    json = json[:-1] # remove final comma
    # write html
    try:
      with open(DIRECTORY+'d3.html', 'r', encoding='utf-8') as templateHTML, open(OUTPUT+'.html', 'w', encoding='utf-8') as fileHTML:
       for line in templateHTML:
         line = re.sub('^var data.*$', 'var data = ['+json+']', line, flags=re.M)
         fileHTML.write(line)
    except ValueError:
      print('"%s" could not be read or "%s" could not be written' % (templateHTML, fileHTML))
  except ValueError:
    print('"%s" could not be saved.' % fileTSV)

# main
predictionList = map(featurePrediction, featureList)
predictionList = [x for x in predictionList if x is not None]
# sort by intensity so D3 draws largest symbols first
predictionList.sort(key=lambda x: x.intensity, reverse=True)
write(predictionList)
