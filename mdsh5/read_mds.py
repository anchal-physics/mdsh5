import mdsthin
from traceback import print_exc
from collections.abc import Iterable
import argparse
import numpy as np
import h5py
import yaml
import shutil
import os
from tqdm import tqdm


def read_mds(shot_numbers=None, trees=None, point_names=None, server=None,
             resample=None, rescale=None, out_filename=None, reread_data=False,
             force_full_data_read=False, config=None, leave_shots_tqdm=True):
    """
    read_mds(shot_numbers=None, trees=None, point_names=None, server=None,
             resample=None, rescale=None, out_filename=None, reread_data=False,
             config=None)

    Read data from MDSPlus server for provided shot numbers, trees, and pointnames.

    Input keyword arguments:
    shot_numbers: <int or str> or <list(int or str)>. Default is None. When str, the
                  string is assumed ot be in format:
                  "<start_shot_number> to <end_shot_number>" with to as the separator
                  word to give a range of shot numbers.
    trees: <str> or list(str) or dict(tress -> list of pointnames). Default is None. If
           list, then the lenght of this list should match length of list provided to
           pointnames arguments for one-to-one mapping.
    point_names: <str> or list(str). Default is  None. If list, then the lenght of this
           list should match length of list provided to trees arguments for one-to-one
           mapping.
    server: <str>. MDSPlus server in the format of username@ip_address:port . Note that
            it is assumed that your ssh configuration is setup to directly access this
            server in case any tunneling is required.
    resample: <lenght 3 iterable like list, tuple of floats> or
              <dict(start: start_time, stop: stop_time, increment: time_step)>. If
              provided as iterable, it should be in order start, stop, increment. It is
              recommended to use dictionary input to ensure correct mapping. All times
              should be float values and would be used in querying from time axis of
              data.
    rescale: <int, float> or <list(int or float)> or <dict(tree -> int or float)>
             Used for rescaling time axis of data before resampling query (if any).
             If <int, float>, same rescaling factor is applied across all trees.
             If <list>, length of this list must be same as length of trees list for
                        one to one mapping of rescaling factor to a particular tree.
             If <dict>, each tree would get it's own rescaling factor. If a tree is not
                        present in this dictionary, rescaling factor will default to 1.
            Resampling factor gets multiplied with stored MDSPlus time axis data, thus
            for example, if time axis data for a tree is in ms, supply rescaling factor
            of 1e-3 to convert the downloaded data in seconds and resample in units of
            seconds.
    out_filename: <str> If provided, downloaded data will be stored in this filename in
                  HDF5 format. Thus `.h5` extension should be provided.
    reread_data: <bool> If True, even if a pointname data is already present in
                 in `out_filename`, it will be downloaded again and overwritten. Can be
                 used if resample or rescale is changed from previous download.
    force_full_data_read: <bool> If True, if resample attempt fails on a pointname,
                           full data reading will be attempted without resampling. This
                           is useful in cases where the pointname stores time dimension
                           in other than dim0 data field.
    config: <str> or <dict>. If <str>, the configuration file in YAML format would be
            read to create the configuration dictionary. Use <dict> if using in
            interactive mode.
            Configuration dictionary can have any of the above arguments present in it.
            Arguments provided by configuration dictionary are overridden by arguments
            directly provided to the function.
    """
    if config is not None:
        if isinstance(config, str):
            with open(config, 'r') as f:
                config = yaml.safe_load(f)
        if 'shot_numbers' in config and shot_numbers is None:
            shot_numbers = config['shot_numbers']
        if 'trees' in config and trees is None:
            trees = config['trees']
        if 'point_names' in config and point_names is None:
            point_names = config['point_names']
        if 'server' in config and server is None:
            server = config['server']
        if 'resample' in config and resample is None:
            resample = config['resample']
        if 'rescale' in config and rescale is None:
            rescale = config['rescale']
        if 'out_filename' in config and out_filename is None:
            out_filename = config['out_filename']
        if 'reread_data' in config and not reread_data:
            reread_data = config['reread_data']
        if 'force_full_data_read' in config and not force_full_data_read:
            force_full_data_read = config['force_full_data_read']
    if isinstance(shot_numbers, int) or isinstance(shot_numbers, str) or isinstance(shot_numbers, dict):
        shot_numbers = [shot_numbers]
    shot_numbers_copy = shot_numbers.copy()
    shot_numbers = []
    for shot in shot_numbers_copy:
        if isinstance(shot, dict):
            shot_numbers += search_shots(shot, server)
        elif isinstance(shot, str):
            if 'to' in shot:
                shotrange = shot.split('to')
                shotstart = int(shotrange[0])
                shotend = int(shotrange[1]) + 1
                shot_numbers += list(range(shotstart, shotend))
            else:
                shot_numbers.append(int(shot))
        else:
            shot_numbers.append(shot)
    if isinstance(point_names, str):
        point_names = [point_names]
    if isinstance(point_names, Iterable):
        point_names = [add_slash(pn) for pn in point_names]
    if isinstance(trees, str):
        tree_dict = {trees.upper(): point_names}
    elif isinstance(trees, list):
        trees = [tree.upper() for tree in trees]
        if len(trees) == 1:
            trees = trees * len(point_names)
        if len(trees) != len(point_names):
            raise ValueError('trees and point_names must be the same length')
        tree_dict = {tree: [] for tree in trees}
        for tree, pn in zip(trees, point_names):
            tree_dict[tree].append(pn)
    elif isinstance(trees, dict):
        trees = {tree.upper(): trees[tree] for tree in trees}
        tree_dict = {tree: [] for tree in trees}
        for tree in trees:
            if tree != "PTDATA":
                if isinstance(trees[tree], str):
                    tree_dict[tree] = [add_slash(trees[tree])]
                else:
                    tree_dict[tree] = [add_slash(pn) for pn in trees[tree]]
    
    rescale_dict = {}
    if isinstance(rescale, (int, float)):
        rescale_dict = {tree: rescale for tree in tree_dict}
    elif isinstance(rescale, list):
        if len(rescale) != len(trees):
            raise ValueError('trees and rescale must be the same length')
        for tree, rs in zip(trees, rescale):
            rescale_dict[tree] = rs
    elif isinstance(rescale, dict):
        rescale_dict = rescale

    try:
        conn = mdsthin.Connection(server)
    except BaseException:
        print_exc()
        return None
    data_dict = {}
    to_write = False
    if out_filename is not None:
        h5 = h5py.File(out_filename, 'a')
        to_write = True
    missed = {}
    DW = 25
    PW = 11
    shot_tqdm = tqdm(shot_numbers, desc="Shots".rjust(DW), leave=leave_shots_tqdm)
    for sn in shot_tqdm:
        shot_tqdm.set_description(f"On #{sn} |".rjust(DW - PW) + " Shots".rjust(PW))
        data_dict[sn] = {tree: {} for tree in tree_dict}
        tree_tqdm = tqdm(tree_dict, desc="Trees".rjust(DW), leave=False)
        for tree in tree_tqdm:
            tree_tqdm.set_description(f"On {tree} |".rjust(DW - PW) + " Trees".rjust(PW))
            rescale_fac = 1
            if tree in rescale_dict:
                rescale_fac = float(rescale_dict[tree])
            if tree != "PTDATA":
                try:
                    conn.openTree(tree, sn)
                except BaseException:
                    if sn not in missed:
                        missed[sn] = {}
                    missed[sn][tree] = 'ALL'
                    continue
                    pass
            pn_tqdm = tqdm(tree_dict[tree], desc="Pointnames".rjust(DW), leave=False)
            for pn in pn_tqdm:
                pn_tqdm.set_description(f"{pn} |".rjust(DW - PW) + " Pointnames".rjust(PW))
                if (not reread_data) and to_write:
                    if check_exists(h5, sn, tree, pn):
                        continue
                try:
                    if tree == "PTDATA":
                        pn = 'PTDATA("' + pn + '")'
                    if pn.startswith("PTDATA"):
                        signal = conn.get(add_resample(pn[:-1] + f", {sn})", resample, rescale_fac))
                    else:
                        signal = conn.get(add_resample(pn, resample, rescale_fac))
                    data = signal.data()
                    if isinstance(data, str):
                        if data == 'bad resample signal in':
                            if force_full_data_read:
                                if pn.startswith("PTDATA"):
                                    signal = conn.get(pn[:-1] + f", {sn})")
                                else:
                                    signal = conn.get(pn)
                                data = signal.data()
                                if isinstance(data, str):
                                    # The data is still a string
                                    if sn not in missed:
                                        missed[sn] = {}
                                    if tree not in missed[sn]:
                                        missed[sn][tree] = {}
                                    missed[sn][tree][pn] = 'ALL data missed due to error: ' + data
                                    continue
                            else:
                                if sn not in missed:
                                    missed[sn] = {}
                                if tree not in missed[sn]:
                                    missed[sn][tree] = {}
                                missed[sn][tree][pn] = 'Bad Resample Request (Try using force_full_data_read option)'
                                continue

                    units = conn.get(units_of(pn)).data()
                    data_dict[sn][tree][pn] = {'data': data, 'units': units}
                    for ii in range(np.ndim(data)):
                        try:
                            if resample is None or ii != 0:
                                dim = conn.get(dim_of(pn, ii)).data() * rescale_fac
                            else:
                                dim = get_time_array(resample)

                            data_dict[sn][tree][pn][f'dim{ii}'] = dim
                        except BaseException as exc:
                            if sn not in missed:
                                missed[sn] = {}
                            if tree not in missed[sn]:
                                missed[sn][tree] = {}
                            missed[sn][tree][pn] = f'Dim{ii}'
                            pass
                    if to_write:
                        append_h5(h5, sn, tree, pn, data_dict)
                except BaseException as exc:
                    if sn not in missed:
                        missed[sn] = {}
                    if tree not in missed[sn]:
                        missed[sn][tree] = {}
                    missed[sn][tree][pn] = 'ALL'
                    pass
            if sn in missed:
                if tree in missed[sn]:
                    all_missed = True
                    for pn in tree_dict[tree]:
                        if pn not in missed[sn][tree]:
                            all_missed = False
                            break
                        all_missed = all_missed and missed[sn][tree][pn] == 'ALL'
                    if all_missed:
                        missed[sn][tree] = 'ALL'
            tree_tqdm.set_description(desc="Trees".rjust(DW))
        if sn in missed:
            all_missed = True
            for tree in tree_dict:
                if tree not in missed[sn]:
                    all_missed = False
                    break
                all_missed = all_missed and missed[sn][tree] == 'ALL'
            if all_missed:
                missed[sn] = 'ALL'
        shot_tqdm.set_description(desc="Shots".rjust(DW))
    
    print("Done!")
    if len(missed) != 0:
        print("Following items could not be downloaded, completely (ALL) or dimension not present (Dim)")
        for sn in missed:
            if missed[sn] == 'ALL':
                print(f"Shot {sn}: ALL")
                continue
            else:
                print(f"Shot {sn}:")
            for tree in missed[sn]:
                if missed[sn][tree] == 'ALL':
                    print(f"  Tree {tree}: ALL")
                    continue
                else:
                    print(f"  Tree {tree}:")
                for pn in missed[sn][tree]:
                    print(f"    {pn}: {missed[sn][tree][pn]}")
    if to_write:
        h5.close()  
    
    return data_dict

def search_shots(search_config, server=None, out_filename=None):
    """
    search_shots(search_config, server=None)

    Function to search through the MDSplus server for a particular condition.

    The search_config dictionary is required to have following parameters:
    search_shots: <int or str> or <list(int or str)>. Default is None. When str, the
                  string is assumed ot be in format:
                  "<start_shot_number> to <end_shot_number>" with to as the separator
                  word to give a range of shot numbers.
    variables: <dict(<variable_name>: {"tree": <tree_name>, "point_name": <point_name>})
               Example: {'x': {'tree': 'PCS_KSTAR', 'point_name': 'EFSIPMEAS'}}. Any
               number of varibales can be defined like this.
    condition: <str> A python executable string.
    The dictionary can have further optional arguments:
    accept_on: <bool>. Default is True. Shot is accepted on condition == accept_on.
    resample: <lenght 3 iterable like list, tuple of floats> or
              <dict(start: start_time, stop: stop_time, increment: time_step)>. If
              provided as iterable, it should be in order start, stop, increment. It is
              recommended to use dictionary input to ensure correct mapping. All times
              should be float values and would be used in querying from time axis of
              data. Default is [-0.1, 20.0, 0.1]. For fast search, try to keep
              resampling at lower sampling rates.
    rescale: <int, float> or <list(int or float)> or <dict(tree -> int or float)>
             Used for rescaling time axis of data before resampling query (if any).
             If <int, float>, same rescaling factor is applied across all trees.
             If <list>, length of this list must be same as length of trees list for
                        one to one mapping of rescaling factor to a particular tree.
             If <dict>, each tree would get it's own rescaling factor. If a tree is not
                        present in this dictionary, rescaling factor will default to 1.
            Resampling factor gets multiplied with stored MDSPlus time axis data, thus
            for example, if time axis data for a tree is in ms, supply rescaling factor
            of 1e-3 to convert the downloaded data in seconds and resample in units of
            seconds. Default is None.
    force_full_data_read: <bool> If True, if resample attempt fails on a pointname,
                           full data reading will be attempted without resampling. This
                           is useful in cases where the pointname stores time dimension
                           in other than dim0 data field. Default is False.
    server: <str>. MDSPlus server in the format of username@ip_address:port . Note that
            it is assumed that your ssh configuration is setup to directly access this
            server in case any tunneling is required. If not provided, server is searched
            in search_config dictionary.
    out_filename: <str> Output filename for saving selected shot numbers. Default is
                  None in which case the selected shots are returned.
    
    Other than search_config, the function can be given server outside of search_config.
    """
    print("Searching...")
    shot_numbers = search_config['search_shots']
    if 'server' in search_config and server is None:
        server = search_config['server']
    if 'out_filename' in search_config and out_filename is None:
        out_filename = search_config['out_filename']
    trees = []
    point_names = []
    for var in search_config['variables']:
        trees += [search_config['variables'][var]['tree']]
        point_names += [search_config['variables'][var]['point_name']]
    if "resample" in search_config:
        resample = search_config["resample"]
    else:
        resample = [-0.1, 20.0, 0.1]
    if "rescale" in search_config:
        rescale = search_config["rescale"]
    else:
        rescale = None
    if "force_full_data_read" in search_config:
        force_full_data_read = search_config["force_full_data_read"]
    else:
        force_full_data_read = False
    if "accept_on" in search_config:
        accept_on = search_config["accept_on"]
    else:
        accept_on = True

    search_data = read_mds(shot_numbers=shot_numbers, trees=trees,
                           point_names=point_names, server=server, 
                           resample=resample, rescale=rescale,
                           force_full_data_read=force_full_data_read,
                           leave_shots_tqdm=False)
    selected_shots = []
    for shot in search_data:
        for var in search_config['variables']:
            tree = search_config['variables'][var]['tree']
            pn = search_config['variables'][var]['point_name']
            exec(f"{var} = search_data[{shot}]['{tree}']['{add_slash(pn)}']['data']")
            if eval(search_config["condition"]) == accept_on:
                selected_shots += [shot]
    if out_filename is not None:
        with open(out_filename, 'a')as f:
            for shot in selected_shots:
                f.write(str(shot) + '\n')
    return selected_shots


def add_slash(s):
    """
    Make the name uppercase and add \\ suffix if not present already or if the name
    does not start with PTDATA.
    """
    if s.startswith("\\") or s.startswith("PTDATA"):
        return s.upper()
    ss = "\\" + s.upper()
    return r'' + ss.encode('unicode_escape').decode('utf-8')[1:]


def add_resample(pn, resample, rescale_fac):
    """
    Add resampling function wrapped in TDI call based on resample and rescale factor.
    """
    if resample is None:
        return pn
    if isinstance(resample, dict):
        resample = [resample['start'], resample['stop'], resample['increment']]
    
    resample = np.array(resample) / rescale_fac
    return f"resample({pn}, {resample[0]}, {resample[1]}, {resample[2]})"

def get_time_array(resample):
    """
    For a resample request, locally generate the time axis.
    """
    if isinstance(resample, dict):
        resample = [resample['start'], resample['stop'], resample['increment']]
    return np.arange(resample[0], resample[1] + resample[2]*0.1, resample[2])


def dim_of(pn, ii):
    """
    Add dim_of() wrapper for extracting dimensional information like time axis.
    """
    return f"dim_of({pn}, {ii})"


def units_of(pn):
    """
    Add units_of wrapper for extracting units of the data.
    """
    return f"units_of({pn})"


def check_exists(h5, shot_number, tree, point_name):
    """
    check_exists(h5, shot_number, tree, point_name)

    Check if data for a point_name, tree, shot_number combination exists in the h5 file
    object.
    """
    sn = str(shot_number)
    if sn in h5:
        if tree in h5[sn]:
            pns = add_slash(point_name)
            if pns in h5[sn][tree]:
                if 'data' in h5[sn][tree][pns]:
                    return True

def append_h5(h5, shot_number, tree, point_name, data_dict):
    """
    append_h5(h5, shot_number, tree, point_name, data_dict)

    Append downloaded data for a point_name, tree, shot_number combination to the h5
    file object. If data already exists, it will be overwritten.
    """
    sntpn_dict = data_dict[shot_number][tree][point_name]
    sn = str(shot_number)
    pn = point_name
    if sn not in h5:
        h5.create_group(sn)
    if tree not in h5[sn]:
        h5[sn].create_group(tree)
    if pn in h5[sn][tree]:
        del h5[sn][tree][pn]
    h5[sn][tree].create_group(pn)
    for key in sntpn_dict:
        if isinstance(sntpn_dict[key], np.str_):
            h5[str(sn)][tree][pn].attrs[key] = sntpn_dict[key].__repr__()
        else:
            h5[str(sn)][tree][pn].create_dataset(key, data=sntpn_dict[key])


def get_args():
    parser = argparse.ArgumentParser(description='Read data from MDSPlus server for '
                                                 'provided shot numbers, trees, and '
                                                 'pointnames.')
    parser.add_argument('-n', '--shot_numbers', nargs='+',
                        help='Shot number(s). You can provide a range using double '
                             'quotes to pass a string.eg. -n "12345 to 12354"')
    parser.add_argument('-t', '--trees', nargs='+', help='Tree name(s)')
    parser.add_argument('-p', '--point_names', nargs='+',
                        help='Point name(s). Must match number of trees provided '
                             'unless a single tree is given.')
    parser.add_argument('-s', '--server', default=None,
                        help='Server address. Default is None')
    parser.add_argument('-r', '--resample', nargs='+', type=float, default=None,
                        help='Resample signal(s) by providing a list of start, stop, '
                             'and increment values. For negative value, enclose them '
                             'withing double quotes and add a space at the beginning.'
                             'Example: --resample " -0.1" 10.0 0.1')
    parser.add_argument('--rescale', nargs='+', type=float, default=None,
                        help='Rescale time dimension of trees to ensure that all of '
                             'are in same units. Especially important if resample is '
                             'used. Provide a rescaling factor to be multiplied by '
                             'time axis for each tree provides in trees option.'
                             'Example: --resample " -0.1" 10.0 0.1')
    parser.add_argument('-o', '--out_filename', default=None,
                        help='Output filename for saving data in file. Default is '
                             'None. in which case it does not save files.')
    parser.add_argument('--reread_data', action='store_true',
                        help='Will overwrite on existing data for corresponding data '
                             'entries in out_file. Default behavior is to skip reading'
                             'pointnames whose data is present.')
    parser.add_argument('-f', '--force_full_data_read', action='store_true',
                        help='If resample fails, full data read will be attempted '
                             'without resampling. This is useful in cases where the '
                             'time axis is stored in other than dim0 data field.')
    parser.add_argument('-c', '--config', default=None, type=str,
                        help='Configuration file containing shot_numbers, trees, '
                             'point_names, server, and other settings. If provided, '
                             'corresponding command line arguments are take precedence'
                             ' over arguments provided in configuration file.')
    parser.add_argument('--configTemplate', action='store_true',
                        help='If provided, configuration templates will be copied to '
                             'current directory. All other arguments will be ignored.')
    args = parser.parse_args()
    return args

def read_mds_cli():
    """
    Command line version of read_mds which gets converted into a script in package.
    """
    args = get_args()
    if args.configTemplate:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.join(root_dir, 'config_examples')
        dest = os.getcwd()
        shutil.copy(os.path.join(src_dir, 'd3d.yml'), dest)
        shutil.copy(os.path.join(src_dir, 'kstar.yml'), dest)
        return 0
    read_mds(shot_numbers=args.shot_numbers,
             trees=args.trees,
             point_names=args.point_names,
             server=args.server,
             resample=args.resample,
             rescale=args.rescale,
             out_filename=args.out_filename,
             reread_data=args.reread_data,
             force_full_data_read=args.force_full_data_read,
             config=args.config,)

if __name__ == '__main__':
    read_mds_cli()
