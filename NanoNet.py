import argparse
import os
import sys
import numpy as np
import logging
import subprocess
from Bio import SeqIO
from Bio.PDB import Polypeptide
from timeit import default_timer as timer
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # or any {'0', '1', '2'}
import tensorflow as tf
from tqdm import tqdm


HEADER = "HEADER    IMMUNE SYSTEM - NANOBODY                           \nTITLE     COMPUTATIONAL MODELING     \nREMARK 777 MODEL GENERATED BY NANONET \n"
ATOM_LINE = "ATOM{}{}  {}{}{} H{}{}{}{:.3f}{}{:.3f}{}{:.3f}  1.00{}{:.2f}           {}\n"
END_LINE = "END\n"

NB_MAX_LENGTH = 140
FEATURE_NUM = 22
AA_DICT = {"A": 0, "C": 1, "D": 2, "E": 3, "F": 4, "G": 5, "H": 6, "I": 7, "K": 8, "L": 9, "M": 10, "N": 11, "P": 12,
           "Q": 13, "R": 14, "S": 15, "T": 16, "W": 17, "Y": 18, "V": 19, "-": 21, "X": 20}
# BACKBONE_FILE_NAME =
# FULL_ATOM_FILE_NAME =


def pad_seq(seq):
    """
    pads a Nb sequence with "-" to match the length required for NanoNetWeights (NB_MAX_LENGTH)
    :param seq: Nb sequence (String) with len =< 140
    :return: Nb sequence (String) with len == 140 (with insertions)
    """
    seq_len = len(seq)
    up_pad = (NB_MAX_LENGTH - seq_len) // 2
    down_pad = NB_MAX_LENGTH - up_pad - seq_len

    # pad the sequence with '-'
    seq = up_pad * "-" + seq + down_pad * "-"
    return seq


def seq_iterator(fasta_file_path):
    """
    iterates over a fasta file
    :param fasta_file_path: path to fasta file
    :return:yields sequence, name
    """
    for seq_record in SeqIO.parse(fasta_file_path, "fasta"):
        seq = str(seq_record.seq)
        name = str(seq_record.name)
        yield seq, name


def generate_input(seq):
    """
    receives a Nb sequence and returns its  sequence in a one-hot encoding matrix (each row is an aa in the sequence, and
    each column represents a different aa out of the 20 aa + 2 special columns).
    :param seq: sequence (string)
    :return: numpy array of size (NB_MAX_LENGTH * FEATURE_NUM)
    """

    if "X" in seq:
        print("Warning, sequence: {}, has unknown aa".format(seq))

    # pad the sequence with '-'
    seq = pad_seq(seq)

    # turn in to one-hot encoding matrix
    seq_matrix = np.zeros((NB_MAX_LENGTH, FEATURE_NUM))
    for i in range(NB_MAX_LENGTH):
        seq_matrix[i][AA_DICT[seq[i]]] = 1

    return seq_matrix


def matrix_to_pdb(pdb_file, seq, coord_matrix):
    """
    writes coord_matrix into pdb_file with PDB format
    :param pdb_file: file to write into
    :param seq: sequence of the Nb
    :param coord_matrix: ca coordinates matrix (generated by NanoNetWeights)
    :return: None
    """
    seq = pad_seq(seq)
    i = 1
    k = 1
    for aa in range(len(seq)):
        if seq[aa] != "-":
            second_space = (4 - len(str(i))) * " "
            b_factor = 0.00
            sixth_space = (6 - len("{:.2f}".format(b_factor))) * " "
            backbone = ["N", "CA", "C", "O", "CB"]
            for j in range(len(backbone)):
                first_space = (7 - len(str(k))) * " "
                third_space = (12 - len("{:.3f}".format(coord_matrix[aa][3*j]))) * " "
                forth_space = (8 - len("{:.3f}".format(coord_matrix[aa][3*j+1]))) * " "
                fifth_space = (8 - len("{:.3f}".format(coord_matrix[aa][3*j+2]))) * " "
                one_letter_code = "UNK" if seq[aa] == "X" else Polypeptide.one_to_three(seq[aa])
                if seq[aa] == "G" and backbone[j] == "CB":
                    continue
                else:
                    pdb_file.write(ATOM_LINE.format(first_space, k, backbone[j]," " * (4 - len(backbone[j])),
                                                    one_letter_code, second_space, i, third_space, coord_matrix[aa][3*j],
                                                    forth_space, coord_matrix[aa][3*j+1],fifth_space, coord_matrix[aa][3*j+2],
                                                    sixth_space, b_factor, backbone[j][0]))
                    k += 1
            i += 1
    pdb_file.write(END_LINE)


def make_alignment_file(pdb_name, sequence):
    """
    makes alignment file for modeller
    """
    with open("temp_alignment.ali", "w") as ali_file:
        ali_file.write(">P1;{}\n".format(pdb_name))
        ali_file.write("sequence:{}:::::::0.00: 0.00\n".format(pdb_name))
        ali_file.write("{}*\n".format(sequence))

    pdb_file = "{}_nanonet_backbone_cb".format(pdb_name)

    env = environ()
    aln = alignment(env)
    mdl = model(env, file=pdb_file)
    aln.append_model(mdl, align_codes=pdb_file, atom_files=pdb_file)
    aln.append(file="temp_alignment.ali", align_codes=pdb_name)
    aln.align2d()
    aln.write(file="alignment_for_modeller.ali", alignment_format='PIR')


def relax_pdb(pdb_name, sequence):
    """
    reconstruct side chains using modeller
    """
    log.none()
    log.level(output=0, notes=0, warnings=0, errors=0, memory=0)
    make_alignment_file(pdb_name, sequence)

    pdb_file = "{}_nanonet_backbone_cb".format(pdb_name)

    # log.verbose()
    env = environ()

    # directories for input atom files
    env.io.atom_files_directory = ['.', '../atom_files']

    a = automodel(env, alnfile='alignment_for_modeller.ali', knowns=pdb_file, sequence=pdb_name)
    a.starting_model = 1
    a.ending_model = 1
    a.make()

    # clean temp files
    for file in os.listdir(os.getcwd()):
        if file[-3:] in ['001', 'rsr', 'csh', 'ini', 'ali', 'sch']:
            os.remove(file)
    os.rename("{}.B99990001.pdb".format(pdb_name), "{}_nanonet_full_relaxed.pdb".format(pdb_name))


def run_nanonet(fasta_path, nanonet_path, single_file, output_dir, modeller, scwrl):
    """
    runs NanoNetWeights structure predictions
    """
    # make input for NanoNetWeights
    sequences = []
    names = []
    i = 0
    for sequence, name in seq_iterator(fasta_path):
        sequences.append(sequence)
        names.append(name + str(i))
        i += 1

    input_matrix = np.zeros((len(sequences), NB_MAX_LENGTH, FEATURE_NUM))
    for i in range(len(input_matrix)):
        input_matrix[i] = generate_input(sequences[i])

    # load model
    logging.getLogger('tensorflow').disabled = True
    nanonet = tf.keras.models.load_model(nanonet_path, compile=False)

    # predict Nb ca coordinates
    backbone_coords = nanonet.predict(np.array(input_matrix))

    # change to output directory
    if not os.path.exists(output_dir):
        os.mkdir(output_dir)
    os.chdir(output_dir)

    # create one ca pdb file
    if single_file:
        backbone_file_path = "nanonet_backbone_cb.pdb"
        with open(backbone_file_path, "w") as file:
            file.write(HEADER.format(""))
            for coords, sequence, name in (zip(backbone_coords, sequences, names)):
                file.write("MODEL {}\n".format(name))
                matrix_to_pdb(file, sequence, coords)
                file.write("ENDMDL\n")

    # create many ca pdb files
    else:
        for coords, sequence, name in (zip(backbone_coords, sequences, names)):
            backbone_file_path = "{}_nanonet_backbone_cb.pdb".format(name)
            with open(backbone_file_path, "w") as file:
                file.write(HEADER.format(name))
                matrix_to_pdb(file, sequence, coords)
            if modeller:
                relax_pdb(name, sequence)
            if scwrl:
                subprocess.run("{} -i {} -o {}_nanonet_full.pdb".format(scwrl, backbone_file_path, name), shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("fasta", help="fasta file with Nbs sequences")
    parser.add_argument("-s", "--single_file", help="Write all the models into a single PDB file with different models (good when predicting many structures, default: False)", action="store_true")
    parser.add_argument("-o", "--output_dir", help="Directory to put the predicted PDB models, (default: ./NanoNetResults)", type=str)
    parser.add_argument("-m", "--modeller", help="Side chains reconstruction using modeller (default: False)",  action="store_true")
    parser.add_argument("-c", "--scwrl", help="Side chains reconstruction using scwrl, path to Scwrl4 executable", type=str)
    parser.add_argument("-t", "--tcr", help="Use this parameter for TCR V-beta modeling", action="store_true")
    args = parser.parse_args()

    # check arguments
    nanonet_dir_path = os.path.abspath(os.path.dirname(sys.argv[0]))
    nanonet_model = os.path.join(nanonet_dir_path, 'NanoNetTCRWeights') if args.tcr else os.path.join(nanonet_dir_path, 'NanoNetWeights')
    scwrl_path = os.path.abspath(args.scwrl) if args.scwrl else None
    output_directory = args.output_dir if args.output_dir else os.path.join(".","NanoNetResults")

    if args.modeller:
        from modeller import *
        from modeller.automodel import *
    if not os.path.exists(args.fasta):
        print("Can't find fasta file '{}', aborting.".format(args.fasta), file=sys.stderr)
        exit(1)
    if not os.path.exists(nanonet_model):
        print("Can't find trained NanoNetWeights '{}', aborting.".format(nanonet_model), file=sys.stderr)
        exit(1)
    if scwrl_path and not os.path.exists(scwrl_path):
        print("Can't find Scwrl4 '{}', aborting.".format(scwrl_path), file=sys.stderr)
        exit(1)
    if args.single_file and (args.modeller or scwrl_path):
        print("Can't reconstruct side chains with single_file option. remove flag -s",file=sys.stderr)
        exit(1)
        
    start = timer()
    run_nanonet(args.fasta, nanonet_model, args.single_file, output_directory, args.modeller, scwrl_path)
    end = timer()

    print("NanoNetWeights ended successfully, models are located in directory:'{}', total time : {}.".format(output_directory, end - start))
