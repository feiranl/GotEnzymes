import os
import math
import DLKcat
import torch
import json
import pickle
import numpy as np
from rdkit import Chem
from Bio import SeqIO
from collections import defaultdict
from scipy import stats
import gzip # read fasta file in .gz
import glob # get file name with matching the .pep.gz
import sys

KEGG_local_path = '/proj/nobackup/snic2021-22-16/kegg' # remember to switch to the downloaded KEGG path
data_for_prediction = '../../dataProcess/output/'
# load data
fingerprint_dict = DLKcat.load_pickle('../data/DLKcat/fingerprint_dict.pickle')
atom_dict = DLKcat.load_pickle('../data/DLKcat/atom_dict.pickle')
bond_dict = DLKcat.load_pickle('../data/DLKcat/bond_dict.pickle')
edge_dict = DLKcat.load_pickle('../data/DLKcat/edge_dict.pickle')
word_dict = DLKcat.load_pickle('../data/DLKcat/sequence_dict.pickle')
comSmiles = DLKcat.load_pickle('../data/DLKcat/kegg_smiles_dict.pickle')

def split_sequence(sequence, ngram):
    sequence = '-' + sequence + '='
    # print(sequence)
    # words = [word_dict[sequence[i:i+ngram]] for i in range(len(sequence)-ngram+1)]

    words = list()
    for i in range(len(sequence)-ngram+1) :
        try :
            words.append(word_dict[sequence[i:i+ngram]])
        except :
            word_dict[sequence[i:i+ngram]] = 0
            words.append(word_dict[sequence[i:i+ngram]])

    return np.array(words)
    # return word_dict

def create_atoms(mol):
    """Create a list of atom (e.g., hydrogen and oxygen) IDs
    considering the aromaticity."""
    # atom_dict = defaultdict(lambda: len(atom_dict))
    atoms = [a.GetSymbol() for a in mol.GetAtoms()]
    # print(atoms)
    for a in mol.GetAromaticAtoms():
        i = a.GetIdx()
        atoms[i] = (atoms[i], 'aromatic')
    atoms = [atom_dict[a] for a in atoms]
    # atoms = list()
    # for a in atoms :
    #     try: 
    #         atoms.append(atom_dict[a])
    #     except :
    #         atom_dict[a] = 0
    #         atoms.append(atom_dict[a])

    return np.array(atoms)

def create_ijbonddict(mol):
    """Create a dictionary, which each key is a node ID
    and each value is the tuples of its neighboring node
    and bond (e.g., single and double) IDs."""
    # bond_dict = defaultdict(lambda: len(bond_dict))
    i_jbond_dict = defaultdict(lambda: [])
    for b in mol.GetBonds():
        i, j = b.GetBeginAtomIdx(), b.GetEndAtomIdx()
        bond = bond_dict[str(b.GetBondType())]
        i_jbond_dict[i].append((j, bond))
        i_jbond_dict[j].append((i, bond))
    return i_jbond_dict

def extract_fingerprints(atoms, i_jbond_dict, radius):
    """Extract the r-radius subgraphs (i.e., fingerprints)
    from a molecular graph using Weisfeiler-Lehman algorithm."""

    # fingerprint_dict = defaultdict(lambda: len(fingerprint_dict))
    # edge_dict = defaultdict(lambda: len(edge_dict))

    if (len(atoms) == 1) or (radius == 0):
        fingerprints = [fingerprint_dict[a] for a in atoms]

    else:
        nodes = atoms
        i_jedge_dict = i_jbond_dict

        for _ in range(radius):

            """Update each node ID considering its neighboring nodes and edges
            (i.e., r-radius subgraphs or fingerprints)."""
            fingerprints = []
            for i, j_edge in i_jedge_dict.items():
                neighbors = [(nodes[j], edge) for j, edge in j_edge]
                fingerprint = (nodes[i], tuple(sorted(neighbors)))
                # fingerprints.append(fingerprint_dict[fingerprint])
                # fingerprints.append(fingerprint_dict.get(fingerprint))
                try :
                    fingerprints.append(fingerprint_dict[fingerprint])
                except :
                    fingerprint_dict[fingerprint] = 0
                    fingerprints.append(fingerprint_dict[fingerprint])

            nodes = fingerprints

            """Also update each edge ID considering two nodes
            on its both sides."""
            _i_jedge_dict = defaultdict(lambda: [])
            for i, j_edge in i_jedge_dict.items():
                for j, edge in j_edge:
                    both_side = tuple(sorted((nodes[i], nodes[j])))
                    # edge = edge_dict[(both_side, edge)]
                    # edge = edge_dict.get((both_side, edge))
                    try :
                        edge = edge_dict[(both_side, edge)]
                    except :
                        edge_dict[(both_side, edge)] = 0
                        edge = edge_dict[(both_side, edge)]

                    _i_jedge_dict[i].append((j, edge))
            i_jedge_dict = _i_jedge_dict

    return np.array(fingerprints)

def create_adjacency(mol):
    adjacency = Chem.GetAdjacencyMatrix(mol)
    return np.array(adjacency)

def dump_dictionary(dictionary, filename):
    with open(filename, 'wb') as file:
        pickle.dump(dict(dictionary), file)

def load_tensor(file_name, dtype):
    return [dtype(d).to(device) for d in np.load(file_name + '.npy', allow_pickle=True)]

def get_refSeq(org) :
    # get the protein sequence accoding to protein sequence id
    # Note that the fasta file is located in the downloaded KEGG ftp file
    proteinSeq = dict()
    fastafile = glob.glob(KEGG_local_path + "/genes/organisms/" + org + "/*.pep.gz")[0]
    with gzip.open(fastafile, "rt") as handle:
        for record in SeqIO.parse(handle, "fasta"):
            proteinSeq[record.id] = str(record.seq)
        print("The protein number of %s is: %d" % (org,len(proteinSeq)))
    return proteinSeq

def get_organisms() :
    filenames = os.listdir(data_for_prediction)
    filenames = [filename.split('.')[0] for filename in filenames if filename.endswith('.txt')]
    print(len(filenames)) 
    # print(filenames[:3])  
    return filenames

class Predictor(object):
    def __init__(self, model):
        self.model = model

    def predict(self, data):
        predicted_value = self.model.forward(data)

        return predicted_value

def main():
    
    n_fingerprint = len(fingerprint_dict)
    n_word = len(word_dict)
    n_edge = len(edge_dict)

    radius=2
    ngram=3

    dim=10
    # dim=5
    layer_gnn=3
    side=5
    window=11
    layer_cnn=3
    layer_output=3
    lr=1e-3
    lr_decay=0.5
    decay_interval=10
    weight_decay=1e-6
    iteration=100

    if torch.cuda.is_available():
        device = torch.device('cuda')
    else:
        device = torch.device('cpu')

    # torch.manual_seed(1234)
    Kcat_model = DLKcat.KcatPrediction(device, n_fingerprint, n_word, 2*dim, layer_gnn, window, layer_cnn, layer_output).to(device)
    Kcat_model.load_state_dict(torch.load('../data/DLKcat/all--radius2--ngram3--dim20--layer_gnn3--window11--layer_cnn3--layer_output3--lr1e-3--lr_decay0.5--decay_interval10--weight_decay1e-6--iteration50', map_location=device))
    # print(state_dict.keys())
    # model.eval()
    predictor = Predictor(Kcat_model)

    print('It\'s time to start the prediction!')
    print('-----------------------------------')

    organisms = get_organisms() # since it is quite large number, we split to be batches
    (startnum, endnum) = sys.argv[1:]
    (startnum, endnum) = map(int, [startnum, endnum])

    i = 0
    exception = list()
    for organism in organisms[startnum:endnum]: 
        i += 1
        print('This is', i, '---------------------------------------')
        print(organism)
        proteinSeq = get_refSeq(organism)

        with open(data_for_prediction + organism + '.txt', 'r') as infile :
            lines = infile.readlines()

        print(len(lines))  # 6291
        print(lines[:2])
        print('--'*20+'\n')

        # The generated prediction results for each organisms are stored
        file =open('../output/%s_kcat.txt' % organism, 'w')

        #file.write(lines[0].strip() + '\t%s\n' % 'Kcat value (/s)')

        for line in lines:  # [1:]
            data = line.strip('\n').split('\t')
            #print(data)
            #print(data[0])  # ProteinID
            #print(data[6])  # compound
            sequence_id = data[0]
            compound = data[6]
            if sequence_id :
                #print(sequence_id)
                #print(proteinSeq[sequence_id])
                sequence = proteinSeq[sequence_id]
                if compound:
                    #print(compound)
                    try :
                        smiles = comSmiles[compound]
                        if "." not in smiles :
                            # i += 1
                            # print('This is',i)
                            mol = Chem.AddHs(Chem.MolFromSmiles(smiles))

                            atoms = create_atoms(mol)
                            # print(atoms)
                            i_jbond_dict = create_ijbonddict(mol)
                            # print(i_jbond_dict)

                            fingerprints = extract_fingerprints(atoms, i_jbond_dict, radius)
                            # print(fingerprints)
                            # compounds.append(fingerprints)

                            adjacency = create_adjacency(mol)
                            # print(adjacency)
                            # adjacencies.append(adjacency)

                            words = split_sequence(sequence,ngram)
                            # print(words)
                            # proteins.append(words)

                            fingerprints = torch.LongTensor(fingerprints)
                            adjacency = torch.FloatTensor(adjacency)
                            words = torch.LongTensor(words)

                            inputs = [fingerprints, adjacency, words]
                            # try :
                            prediction = predictor.predict(inputs)
                            Kcat_log_value = prediction.item()
                            Kcat_value = '%.4f' %(math.pow(2,Kcat_log_value))
                            added_content = Kcat_value + '\t'
                            sequence_id = sequence_id.split(':')[1]
                            outline = sequence_id + '\t'+ data[1] + '\t'+ data[2] + '\t'+ data[3] + '\t'+ data[4] + '\t'+ data[5] + '\t'+ data[6]
                            file.write(outline)
                            file.write(added_content)
                            file.write('\n')
                            # Kcat_value = math.pow(10,Kcat_log_value)

                            # print(Kcat_log_value)
                            print(added_content)
                            print(type(Kcat_value))
                            #Kcat_value = '%.4f' %(Kcat_value)
                            #print(Kcat_value)
                    except :
                        Kcat_value = '#'
                        exception.append([compound,organism]) 
        file.close() 

if __name__ == '__main__':
    main()


            
